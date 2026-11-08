# AgentTree — Implementation Plan and Winning Demo

**Hackathon:** AWS × A10 Hack 2026  
**Track:** A10 Prompt 2 — Agent Harness  
**Team:** 3 developers  
**Timebox:** 24 hours  
**Status:** Build specification, not a claim of existing implementation

## 0. The one-sentence product

**AgentTree is a CLI agent execution harness that enforces delegated tool permissions and holds supported write operations until the task is eligible to commit; if a branch is stopped or violates policy, its pending effects are aborted without interrupting healthy sibling branches.**

**Official-prompt fit:** Launch a CLI agent, display its routed traffic, block a disallowed action, and stop the run. Branch-level effect isolation is the differentiator, not a replacement for those basics.

### What the MVP actually guarantees

1. Registered protected tools can only be called through an authenticated, authoritative gateway.
2. The gateway applies tool, resource, and parameter constraints defined by trusted application policy.
3. Eligible write requests are **staged** and have no effect on the committed business database before the commit boundary.
4. For the **single SQLite business database controlled by the demo**, one branch's staged business mutations are committed in **one atomic transaction**, or remain uncommitted when that branch is aborted.
5. A policy violation or operator containment request revokes the branch's gateway authority, prevents any new commit from beginning, and stops its supervised processes.
6. Other independent branches can finish and commit their own mutations.

**Not guaranteed:** Understanding whether an agent's intent is morally/business-wise correct; automatic prompt-injection detection; preventing arbitrary shell/network access; rolling back completed third-party API effects; distributed atomicity across external APIs; successfully stopping already committed effects. A demo prompt injection is **not** proof of general injection detection.

---

## 1. Frozen demo story

**Fictional business case:** Customer `C104` has two independent tasks in the same parent workflow.

- **Order task:** Process an approved $45 refund for order `ORD-882`.
- **Account task:** Review a loyalty note and handle a promotion on customer `C104`.

The parent delegates the tasks to the **Order Agent** and **Account Agent**, each in a separately supervised process and independently scoped branch.

**Allowed capabilities:**

| Agent | Allowed operations | Resource scope | Commit policy |
|---|---|---|---|
| Parent | Delegate only predefined roles | Run's `C104` tasks | No business mutations |
| Order | `read_order`, `stage_refund`, `read_order` | `C104`, `ORD-882`, refund <= $45 | Auto-commit on verified completion |
| Account | `read_account`, `stage_promo_credit`, `read_account` | `C104`, promo credit <= $50 | Auto-commit only on verified completion; aborted on any policy violation |

A fictional account memo contains an instruction to apply a $50 credit to `C104`, then use `modify_billing` on `C999`. The **model may or may not follow** this untrusted instruction. We observe its true behavior and independently provide a controlled gateway-violation probe for a reliable policy demonstration.

### Required final evidence

- Order branch: `$45` refund **STAGED → COMMITTED**, committed refund row exists exactly once.
- Account branch: `$50` promo credit **STAGED → ABORTED**, committed promo balance remains `$0`.
- `modify_billing(C999)` request: **DENIED** and no downstream modification.
- Account credentials revoked and account process exit verified.
- A post-containment permitted call or completion by the Order Agent succeeds.
- Real Bedrock inference, model tool requests, gateway calls, and OS process identities are labeled accurately.

**Important:** The demo must not label a controlled probe as an autonomous Bedrock-generated request. Events carry `origin: MODEL | CONTROLLED_TEST | OPERATOR | SUPERVISOR`.

---

## 2. Architecture

```text
agenttree run --scenario customer-104
       |
       v
CLI client ---- POST /runs ----> FastAPI control plane (single worker)
                                     |
                     +---------------+-----------------+
                     |               |                 |
              Process supervisor   Gateway        Event stream (SSE)
                     |               |                 |
             Parent worker           |                 v
                Bedrock              |            React dashboard
                     |               |
           structured delegate       |
                     |               |
                 Supervisor          |
              /             \        |
      Order worker       Account worker
      Bedrock loop       Bedrock loop
             \             /
             authenticated tool calls
                        |
                 POLICY CHECK
                        |
           +------------+------------+
           |                         |
         READ                    STAGE WRITE
   committed + own overlay       branch journal
           |                         |
           +------------+------------+
                        |
                 Commit controller
                        |
            SQLite transactional business DB
```

### Trust boundaries

- **Trusted:** Backend supervisor, gateway, policy definitions, journal/commit controller, business database.
- **Untrusted:** Model-generated tool calls, retrieved customer notes, model text output, worker-requested permission changes.
- **Agent credential:** Each worker receives a short-lived opaque capability token granting **only gateway access** to preapproved functions. Tokens do not confer operator privileges.
- **Downstream state:** Only the gateway/commit controller can mutate the mock business database; agents cannot open its SQLite file or invoke direct write APIs through registered tools. This relies on process/file isolation appropriate to the demo and is **not a hostile same-user OS sandbox**.
- **Bedrock access:** Simplest coherent design is a trusted **model proxy endpoint** in the backend that calls Bedrock on behalf of authenticated workers. Workers need not receive AWS keys. Model-proxy requests are logged separately from protected business-tool traffic.
- **Operator access:** Admin controls use a separate local demo operator session/credential. No secret is hardcoded in frontend JavaScript or put in an SSE URL.

### Tech

- Python 3.11+, FastAPI, SQLite, boto3 Bedrock Converse, psutil, pytest.
- Separate worker processes via `subprocess.Popen(..., start_new_session=True)` (POSIX demo); process creation times tracked to avoid PID reuse confusion.
- React + TypeScript, React Flow, event timeline, SSE or short polling with sequence numbers.
- AWS Bedrock is P0. CloudWatch/DynamoDB/Verified Permissions are optional and must not replace a functioning system.

---

## 3. Repository: preserve and extend existing code

```text
agenttree/
  README.md
  IMPLEMENTATION_PLAN.md
  .env.example
  backend/
    main.py                  # existing app, routes, event transport
    hierarchy.py             # runs, tree, agent / branch identity
    gateway.py               # auth and tool dispatch; extend for staging
    supervisor.py            # real process ownership and termination
    policies.py              # trusted task scope and commit rules
    staging.py               # write journal, overlays, OCC, atomic commit
    storage.py               # SQLite schema/transactions
    bedrock_proxy.py         # trusted Bedrock caller (optional separate module)
    models.py                # typed API contracts
    tests/
  agents/
    runner.py                # Bedrock tool loop with gateway adapters
    parent.py
    order.py
    account.py
  cli.py                     # launch/status/events/stop
  frontend/
    src/App.tsx              # preserve tree; add effect inspector
    src/App.css
  demo/
    reset_demo.py
    run_demo.py
    fixtures.json
    demo_script.md
```

Preserve working functionality rather than blindly replacing existing files. Adapt paths to the real repository after inspection.

---

## 4. Data model and invariants

### Database tables

- `runs(run_id, scenario, state, created_at)`
- `agents(agent_id, run_id, parent_id, branch_id, role, pid, process_create_time, process_state, task_state)`
- `branch_policies(branch_id, allowed_tools_json, customer_id, order_id, amount_cap_cents, commit_mode)`
- `agent_sessions(token_hash, agent_id, branch_id, revoked_at)` — do **not** persist raw tokens in logs
- `branches(branch_id, run_id, state, violation_count, completed_at, committed_at, aborted_at)`
- `journal(action_id, branch_id, sequence, tool, args_json, base_version, state, idempotency_key, created_at)`
- `business_accounts(customer_id, promo_credit_cents, version, notes)`
- `business_orders(order_id, customer_id, paid_cents, refunded_cents, version, status)`
- `events(event_seq, run_id, branch_id, agent_id, origin, type, payload_json, created_at)`

Use integer cents, not floating-point currency.

### Branch state machine

```text
RUNNING --complete_task accepted--> READY_TO_COMMIT --commit begins--> COMMITTING --> COMMITTED
   |
   +-- policy violation / operator stop --> ABORTING --> ABORTED

READY_TO_COMMIT -- operator stop / policy failure --> ABORTING --> ABORTED
READY_TO_COMMIT -- version conflict --> COMMIT_REJECTED (pending discarded or retriable per explicit policy)
COMMITTING -- SQLite transaction rollback --> COMMIT_FAILED (no changes committed)
```

**Authoritative rule:** A worker cannot set itself to `COMMITTED`. A valid `complete_task` request marks only `READY_TO_COMMIT`; the supervisor confirms expected worker completion and the commit controller authorizes the subsequent transition. Worker exit code alone is insufficient.

**Critical concurrency contract:** Use SQLite `BEGIN IMMEDIATE` around competing branch-stop, commit-transition and final business mutation decisions. Once the branch becomes `COMMITTING`, the transaction has acquired authority to complete; a later stop request must report `COMMIT_IN_PROGRESS` / `ALREADY_COMMITTED`, **not** falsely claim that its effects were prevented. Aborting wins if its state transition commits first. Do not hold a database lock during Bedrock calls.

### Write staging

`stage_refund(ORD-882, 4500)` and `stage_promo_credit(C104, 5000)` must:

1. Authenticate the agent and check branch state `RUNNING`.
2. Check tool, customer, order, amount, duplicate-action and business constraints.
3. Record an append-only journal row and base resource version; never modify committed business rows.
4. Update the branch-local overlay; subsequent reads by that branch return the committed row merged with its pending journal.
5. Return `{"status":"STAGED","action_id":"...","executed":false,"committed":false,"preview":{...}}`.

**No fake success:** A stage acknowledgment must not claim the refund or promo credit was paid/applied. Parent/customer-facing results may claim completion only after commit confirmation.

**Read-your-own-writes:** Account reading C104 after staging its credit sees the provisional +$50 with `is_provisional: true`; Order sibling and committed-state dashboard do not. Implement only for the two supported fixture operations.

### Atomic commit for the demo's controlled database

1. Verify branch `READY_TO_COMMIT`, genuine supervisor completion and zero policy violations.
2. Acquire SQLite write transaction (`BEGIN IMMEDIATE`).
3. Recheck branch state, policy, journal, versions and business preconditions *inside the transaction*.
4. Apply all branch journal entries in sequence to the **same SQLite database connection/transaction**.
5. Mark journal entries `COMMITTED`, branch `COMMITTED`, and append audit event atomically.
6. Commit; on error roll back the SQLite transaction.
7. Use unique idempotency keys/transaction IDs to avoid duplicate refunds on retry.

A conflicting resource version results in a deterministic failure rather than silently overwriting another branch's work. For this demo, do **not** attempt atomic commits across real external payment APIs.

### Policy violation and containment

- Gateway returns `DENY` for forbidden `modify_billing`, any `C999` access, invalid token or invalid parameters.
- For the demo, an **application-configured rule** (`abort_on_scope_violation = true`) atomically transitions the violating branch into `ABORTING` and revokes its gateway session; staged entries remain visible in the audit journal but become `ABORTED` / cannot commit.
- Supervisor sends `SIGTERM` then `SIGKILL` only if needed, verifies exit and records actual result.
- No blocked branch output is used as a parent instruction; parent receives a structured `BRANCH_ABORTED` result.
- Unaffected siblings' credentials, processes, and staged actions are unchanged.
- The UI never equates a frontend click with confirmed process termination.

---

## 5. API contracts

### Run and visibility

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Health and model connectivity status |
| `POST` | `/runs` | Launch run via CLI / authorized operator |
| `GET` | `/runs/{id}` | Run status |
| `GET` | `/runs/{id}/tree` | Agent hierarchy and process status |
| `GET` | `/runs/{id}/events?after_seq=N` | Ordered audit events |
| `GET` | `/runs/{id}/effects` | Staged, committed, aborted effects and authoritative production state |
| `GET` | `/events/stream?run_id=...` | SSE; use cookie session or authenticated fetch-stream, never bearer secret in URL |

### Agent/internal

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/internal/delegations` | Authenticated parent requests **predefined** child roles; supervisor checks scope |
| `POST` | `/gateway/model/converse` | Authenticated model proxy to Bedrock; no AWS keys to child |
| `POST` | `/gateway/tools/call` | Authenticated read/stage/forbidden tool attempts |
| `POST` | `/gateway/complete-task` | Worker signals logical completion; **not** commit authorization |

### Operator / deterministic demonstration

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/branches/{id}/stop` | Revoke, abort pending effects, terminate managed process(es) |
| `POST` | `/branches/{id}/commit` | Supervisor/operator-controlled release when eligible |
| `POST` | `/demo/runs/{id}/probe-unauthorized` | Explicit `CONTROLLED_TEST` gateway request through the actual permission path |
| `POST` | `/demo/runs/{id}/hold` | Toggle checkpoint holding eligible commit; no sleep-based theater |
| `POST` | `/demo/runs/{id}/release` | Release held eligible branch commit |
| `POST` | `/demo/reset` | Cleanup old processes, reset only demo fixtures |

Keep control endpoints inaccessible with agent credentials. For the unauthorized probe, the test harness may retain a credential in protected test-only memory and use the real gateway request path; do not reconstruct a stored hash or disclose the token to the browser. Prefer a worker-triggered probe while the worker is alive. A revoked-credential replay can use test-harness-held credentials with restricted admin access.

### Event contract

```json
{
  "event_seq": 42,
  "run_id": "run-104",
  "branch_id": "account",
  "agent_id": "account-agent",
  "origin": "MODEL",
  "type": "TOOL_STAGED",
  "tool": "stage_promo_credit",
  "action_id": "stg-101",
  "decision": "ALLOW",
  "details": {"amount_cents": 5000, "customer_id": "C104"}
}
```

Other useful types: `PROCESS_STARTED`, `MODEL_REQUESTED_TOOL`, `TOOL_ALLOWED`, `TOOL_DENIED`, `BRANCH_REVOKED`, `PROCESS_EXIT_VERIFIED`, `EFFECT_ABORTED`, `COMMIT_ELIGIBLE`, `COMMIT_STARTED`, `EFFECT_COMMITTED`, `COMMIT_REJECTED`.

---

## 6. Implementation sequence with acceptance gates

### Stage 0 — Audit existing repo and confirm Bedrock (start immediately)

- Inspect actual `main.py`, `hierarchy.py`, `gateway.py`, `supervisor.py`, `App.tsx`, `App.css` and tests; mark working vs stubbed code.
- Verify CLI entry, real OS process handles, model/tool calls, business DB, stop behavior.
- Validate AWS Workshop Studio credentials, Bedrock model ID/region and one successful Converse request.
- Freeze `policies.py`, model/action schemas, event fields, states and routes.

**PASS:** Clean build; real Bedrock smoke test; documented gap list. No fabricated runtime claims.

### Stage 1 — Add authoritative persistence and transaction tests

- Add SQLite schema/migrations, fixtures and reset script.
- Implement branch journal, overlay reads, version checks, idempotency keys and transactional commit controller.
- Add state machine, concurrency-safe stop vs commit transitions.

**PASS:** Without agents, stage both effects; database remains unchanged; commit one branch; abort the other; pass repeat-commit, OCC and stop/commit race tests.

### Stage 2 — Real gateway and delegated capabilities

- Server-defined role templates; child scope must be a subset of parent's authorized task scope.
- Opaque per-agent tokens; never trust `agent_id` from request payload.
- Validate every tool argument; enforce `C104`, `ORD-882` and monetary caps.
- No business DB mutation on denied tool calls.

**PASS:** Allowed reads and staging succeed; `modify_billing(C999)` denied; no database change; spoofed identity denied; violation aborts pending effects.

### Stage 3 — CLI, supervisor and real Bedrock agents

- CLI launches via backend `/runs` and tails events.
- Real parent uses Bedrock to request predefined task delegation; supervisor validates and spawns real child processes.
- Each child calls model proxy; actual model-generated tool requests go through the gateway.
- Supervisor owns PIDs, runs worker heartbeat/exit verification, process-group cleanup and sibling isolation.
- Separate external-data content from system instructions in model context.

**PASS:** Real model/tool events, independent process IDs, real termination. No hardcoded "AI decided to modify billing" event.

### Stage 4 — Deterministic demo checkpoints

- Demo fixture: real Order staged refund, Account staged credit when model genuinely requests it.
- `READY_TO_COMMIT` checkpoint holds the Order result until presenter releases it.
- `POLICY_VIOLATION` pause/state makes Account branch effects visible and ensures they cannot commit.
- Provide controlled-test pathway if actual Bedrock does not choose the forbidden call. Label it clearly; do not disguise scripted behavior.
- Provide event log that shows exact model tool calls, authorized staged calls, and test-origin probes distinctly.

**PASS:** Two visible staged actions before resolving branches; stop account; account effect aborted; release order; only order effect committed.

### Stage 5 — React demo dashboard

Implement one screen with:

1. **Top:** CLI run ID, Bedrock model, live status, Stop Run, Reset Demo.
2. **Left:** React Flow parent/child graph with real PID, branch state, scoped tools and current task.
3. **Center:** Three-column effect inspector: `STAGED`, `ABORTED`, `COMMITTED`; each action includes branch, amount, ID and timestamp.
4. **Right:** Committed business state: `ORD-882 refunded_cents`, `C104 promo_credit_cents` from authoritative database queries.
5. **Bottom:** Event timeline with `MODEL`, `CONTROLLED_TEST`, `OPERATOR`, `SUPERVISOR` origin labels; tool, args, allow/deny, and process termination evidence.
6. **Operator controls:** Stop Account Branch; release clean Order commit; view receipt; retry rejected credential test.
7. **Baseline comparison strip (illustrative, not a second live system):** A 20–25 second visual showing a conventional immediate-execution gateway applying three permitted writes before denying a fourth request. Mark it **ILLUSTRATIVE BASELINE**, not a measured comparison or a claim about every gateway. This is presentation-only and must not generate fake live audit entries.

Use SSE with `event_seq` reconnect, or poll every second if SSE complicates auth. UI must be functional, not merely animated.

**PASS:** Refresh/reconnect reconstructs DB truth; STOPPED only after verified exit; no fake pending or committed badges.

### Stage 6 — Harden, rehearse, submit

- Automated full integration scenario, including one sibling's *post-stop* operation.
- Three consecutive complete rehearsals.
- Backup real recording.
- README explaining setup, prompt alignment, limitations, AWS usage, architecture, test commands and demo.
- Optional CloudWatch event export only after P0 is stable.

**PASS:** 3-minute demonstration consistently completes without manually editing database state or fabricating events.

---

## 7. The perfect three-minute judging demo — problem first, then proof

**Title:** **"Your AI Agent Was Stopped. But Were Its Changes?"**

**Narrative structure:** A brief **illustrative baseline** exposes the weakness of per-request checks when permitted writes execute immediately; the **live AgentTree run** then proves how branch-scoped staging changes the outcome. Do **not** build or run a second conventional gateway merely to make the comparison. The baseline is an explanatory diagram, explicitly labeled as such; all security evidence comes from the live run.

### Screen setup and presenter controls

- **Left 25%:** Terminal with the real CLI invocation and observed Bedrock/gateway activity and OS PIDs.
- **Right 75%:** React dashboard: agent tree, permissions and events, STAGED / ABORTED / COMMITTED panel, authoritative committed database state.
- **Baseline panel:** A 20–25 second optional overlay/slide labeled `ILLUSTRATIVE BASELINE — immediate-execution gateway`, clearly separate from live telemetry.
- **Live checkpoint:** A controlled `READY_TO_COMMIT` hold for the Order branch, and a `POLICY_VIOLATION`/containment checkpoint for Account. These are *real execution gates*, not arbitrary animation sleeps. Provide presenter actions **Start**, **Show Pending**, **Contain Account**, **Verify Revocation**, **Release Order Commit**, and **Reset** backed by actual endpoints.
- **Reset:** Both committed values start at `$0`; fixture includes Order `ORD-882`, Customer `C104`, and a fictional lower-trust account memo. Do not disclose raw runtime credentials or display sensitive customer data.

### Act 1 — 0:00–0:30 | Show the missing guarantee

**Show:** A single concise **illustrative** sequence in a per-request, immediately executing gateway:

| Step | Illustrative Account Agent request | Conventional immediate-execution result |
|---|---|---|
| 1 | Add `$20` promotional credit | ALLOWED → real state changes |
| 2 | Upgrade loyalty tier | ALLOWED → real state changes |
| 3 | Add `$30` promotional credit | ALLOWED → real state changes |
| 4 | Modify unrelated customer billing | DENIED → this request blocked |
| 5 | Operator stops the agent | Earlier writes remain applied |

**Say:** "A gateway can correctly block the fourth request, but that does not undo the first three permitted changes. If the *task* fails halfway through, what happens to its partial effects?"

**Important qualification:** Those earlier changes are not automatically malicious or incorrect. The problem is **partial completion** when this task's policy requires all-or-nothing effects. This comparison describes an immediate-execution design, not all possible API gateways.

**Transition:** "AgentTree adds a task-level boundary around the changes, not just a permission check around each call."

### Act 2 — 0:30–0:55 | Launch the real CLI harness

**Do:** Run `python cli.py run --scenario customer-104`. A real parent coordinates Order and Account workers with independent managed processes. Show actual Bedrock model events and the per-agent tool/resource policy.

**Say:** "We launch real AI workers from the CLI. Each runs under a scoped identity; protected tool traffic goes through the harness."

**Must prove:** Actual PIDs, source-labeled Bedrock tool requests, gateway traffic, distinct branches. Do not imply the agent has unrestricted OS/network sandboxing.

### Act 3 — 0:55–1:25 | Both branches stage permitted actions

**Do:** Order stages a `$45` refund; Account stages a `$50` promotional credit. Hold both in real pending states so the audience can inspect the pending-effects ledger and the committed business-state panel. Show the account memo and model-request origin if the actual model used it.

**Say:** "Both operations were permitted. But neither is executed against our committed business database yet. Those changes are only pending within each task."

**Must prove:** Two true `STAGED` events linked to real authenticated gateway requests. Production refund `$0`; production promo `$0`. Do not say money was refunded yet.

### Act 4 — 1:25–2:00 | Block and contain the offending branch

**Do:** Account attempts `modify_billing(C999)`; the gateway issues `DENY`. If Bedrock itself requested it, label `MODEL`; otherwise use the explicit `CONTROLLED_TEST` path and state that the model did not produce the forbidden request. Stop/contain only Account. Its `$50` staged credit becomes `ABORTED`, gateway credential is revoked, and its process exit is verified.

**Say:** "The forbidden call was blocked. But the crucial part is that this branch's *earlier permitted* credit was never committed, so aborting the task discards it without needing a fake refund or rollback."

**Must prove:** Denial reason, correct event origin, Account process exit, `ABORTED` credit, committed promo still `$0`.

### Act 5 — 2:00–2:20 | Verify containment is real

**Do:** Use the protected test harness to retry a previously allowed `read_account(C104)` with the revoked Account credential; show `BRANCH_STOPPED`. Show Order PID still alive.

**Say:** "Stopping this branch means its process is gone and its previous authority is gone—not just that its dashboard icon turned red."

**Must prove:** Revoked token denied, verified Account exit, sibling process still available.

### Act 6 — 2:20–2:45 | The healthy branch continues and commits

**Do:** Order makes a *new, real* permitted tool call after Account termination; then release its actual `READY_TO_COMMIT` checkpoint. Commit controller verifies state, policy and versions and applies the `$45` refund in one SQLite transaction.

**Say:** "The other agent wasn't restarted. It kept working. Its task completed successfully, so its pending refund can now commit."

**Must prove:** Fresh Order gateway `ALLOW`, `STAGED → COMMITTED`, authoritative refund `$0 → $45`, promo still `$0`; no duplicate refund. If commit fails, surface the error rather than falsely marking success.

### Act 7 — 2:45–3:00 | Close on the visual contrast

**Final dashboard state:**

```text
PARENT AGENT: HEALTHY / COORDINATION COMPLETE
├── ORDER AGENT: COMPLETED       STAGED → COMMITTED    $45 refund applied
└── ACCOUNT AGENT: STOPPED       STAGED → ABORTED      $50 credit never applied

Account modify_billing(C999): DENIED
Account credential: REVOKED   | Account process exit: VERIFIED
Order post-stop operation: ALLOWED
Committed DB: refund $45 | promo $0
```

**Close:** "A conventional request check can stop the bad fourth call. AgentTree also prevents the failed task's earlier *pending* actions from reaching production, while healthy agents finish independently."

### Truthfulness and demo-reliability rules

- Act 1 is an **illustration**, not a live benchmark; it must never appear in real agent logs.
- Do not claim every denied request proves compromise. An app-defined policy decides whether to abort the task after a violation.
- A prompt injection may influence the model, but its success is not guaranteed. Use the labeled controlled-policy probe when needed.
- A presenter hold is a real commit barrier, not fake processing or an arbitrary sleep.
- `STAGED` never means executed; `ABORTED` means never committed; `COMMITTED` is backed by the real SQLite database transaction.
- Atomicity applies only to supported writes into the one controlled SQLite database. No promise of undo or atomic commit across external services.
- Run the full three-minute sequence three consecutive times, including reset, process verification and a real post-containment sibling call.

---

## 8. Minimum automated test matrix

| Test | Required outcome |
|---|---|
| Allowed Account `read_account(C104)` | ALLOW |
| Account `read_account(C999)` | DENY |
| Account `modify_billing(C999)` | DENY |
| Stage Account `$50` credit | Journal STAGED; committed promo remains `$0` |
| Stage Order `$45` refund | Journal STAGED; committed refund remains `$0` |
| Account read after staged promo | Provisional `$50`, flagged uncommitted |
| Order read of account state | No visibility of Account overlay |
| Account violation after stage | ABORTED, no promo commit |
| Account stop | Token revoked, PID exit verified |
| Revoked token reuses formerly allowed tool | DENY |
| Order tool call after Account stop | ALLOW |
| Order verified complete + released commit | Refund `$45` committed once |
| Duplicate commit / request retry | No duplicate refund |
| Stop-before-commit race | ABORTED, zero effect |
| Commit-first-then-stop race | COMMITTED correctly reported, never false abort |
| Concurrent resource-version change | COMMIT_REJECTED / 409 |
| SQLite error mid-branch commit | Atomic transaction rolls back |
| Worker crash before commit | Pending effects ABORTED |
| Invalid parent delegation / role escalation | Rejected |
| SSE reconnect or poll refresh | Exact persisted state restored |
| Demo reset | Processes reaped, fixtures restored |
| Event audit | Origin correct; no raw secrets |

---

## 9. Sprint priority and fallback choices

### P0 — Cannot submit without

- Real CLI entrypoint and traffic log.
- Real Bedrock model/tool-use loop.
- Real managed child processes and verified stop.
- Authenticated protected-tool gateway and scoped rules.
- Staging and atomic single-SQLite-DB commit/abort logic.
- Unaffected branch finishing and committing.
- One-screen live evidence dashboard.
- Deterministic repeatable demo.

### P1 — Strong polish

- Attractive React Flow tree, persistent three-state effect cards, hover evidence, commit checkpoint, prompt-injection source inspection, visible timing/token data from real model response.

### P2 — Only if all P0 tests pass

- CloudWatch export, Amazon Verified Permissions integration, deployment, generalized external sinks, grandchild agents, multiple demos.

### Suggested working windows (overlap independent work)

| Window | Target |
|---|---|
| 0–2h | Code audit, AWS smoke, freeze contracts |
| 2–5h | SQLite journal, overlays, transaction tests |
| 4–7h | Gateway scopes, tokens, branch state/races |
| 6–10h | Real CLI, subprocess supervisor, Bedrock tools |
| 9–13h | Deterministic staging/abort/commit scenario |
| 10–16h | React evidence dashboard and event transport |
| 16–20h | Integration, race/crash/replay validation |
| 20–23h | Three full rehearsals, README and backup capture |
| 23–24h | Final packaging and submission |

**Fallback order:** Drop optional AWS services → extra UI effects → read-your-own-writes for non-demo tools → extra tool types. **Do not drop** truthful model events, real gateway decisions, real process verification, or the actual DB commit/abort proof. If the model doesn't generate the security violation, use and label the controlled test instead of falsifying an event.

---

## 10. Codex execution instructions

1. Inspect current files before making changes. Preserve working backend/frontend behavior.
2. Implement a coherent vertical slice and run its tests before starting the next slice.
3. Treat API and event contracts in this plan as the integration source of truth.
4. Never conflate `STAGED` and `COMMITTED`, `DENIED` and `ABORTED`, or `STOP_REQUESTED` and `PROCESS_EXIT_VERIFIED`.
5. Never treat a model-generated tool call as a trustworthy permission grant.
6. Never put business DB credentials in an agent's accessible tools or raw tokens in browser events.
7. Never claim external API atomicity or general prompt-injection detection.
8. After every stage report files changed, tests run, exact results, blocked criteria and remaining limitations.
9. Maintain a one-command demo reset and repeatable fixture IDs.
10. Keep the central pitch and three-minute demo intact; do not add an unrelated reviewer agent, rollback engine, or taint classifier.

## Final acceptance statement

**We can truthfully say the project works when:** a real CLI-launched agent workflow reaches the gateway; both agents prepare real pending effects; the gateway blocks a disallowed request; containment aborts one branch's pending effects and verifies its process termination; the other branch executes a permitted post-containment call and commits its own effect in the controlled transactional database; and the React dashboard displays the evidence without inventing state.

---

## 11. Practical staged implementation roadmap

This roadmap is the execution checklist for the current repository. Each numbered commit should be small enough to review independently and should leave the demo in a coherent state. Do not start the next stage until its acceptance evidence is available. Keep the live demo smooth: stable fixture IDs, explicit run states, visible pending/committed truth, and reset/cleanup behavior are product requirements rather than polish.

### Stage A — Transactional foundation

1. **A1 — Define demo policy and state vocabulary.** Add the trusted fixture policy and shared constants for branch/effect states, event origins, tool names, resource IDs, and integer-cent limits. Keep the policy outside model-controlled inputs.
2. **A2 — Persist business fixtures and effect journal.** Extend SQLite initialization with schema-versioned transactional tables for the two fixture resources, branches, staged actions, idempotency keys, and ordered audit events. Seed/reset `ORD-882` and `C104` predictably without changing the existing run/agent tables' behavior.
3. **A3 — Implement stage and overlay reads.** Add validated `stage_refund` and `stage_promo_credit` operations. Staging must not change committed business state; branch-local reads may expose that branch's own pending changes with an explicit provisional flag.
4. **A4 — Implement completion, atomic commit, and abort.** Add trusted transitions from running to ready-to-commit, one-transaction commit with state/version/idempotency checks, and abort that marks pending actions without applying them. Serialize stop-versus-commit decisions in SQLite.

**Stage A gate:** service-level flows prove both effects can be staged while committed values remain zero; one commits exactly once; the other aborts with no committed change; repeated requests and commit retries do not duplicate effects.

### Stage B — Enforced gateway and branch containment

5. **B1 — Authenticate gateway calls by token owner.** Preserve per-agent opaque credentials; derive identity from the credential and reject identity spoofing, revoked credentials, inactive branches, and unknown tools.
6. **B2 — Enforce resource and amount policy before staging.** Apply the frozen role policy to customer/order IDs, refund/credit caps, business preconditions, and duplicate actions. Denied calls never create journal entries or change business rows.
7. **B3 — Make violation containment one backend operation.** On configured scope violations, atomically revoke the branch session and abort its pending effects, then ask the supervisor to stop the branch. Report process termination only after it is verified; leave sibling state and credentials intact.

**Stage B gate:** an Account branch can stage its permitted credit, gets a `DENY` for the forbidden `modify_billing(C999)` probe, becomes unable to commit, and loses its credential; Order remains able to call its permitted tools.

### Stage C — Deterministic vertical-slice demo

8. **C1 — Add explicit demo orchestration and reset.** Update the runner to create/reuse a run safely, establish fixture branches, stage both actions, hold at a real commit checkpoint, run a clearly labeled controlled probe when needed, contain Account, and release Order for commit. Reset must clean managed processes and restore only demo fixture state.
9. **C2 — Add read APIs for effects and committed state.** Return ordered, persisted effect and event records plus authoritative business rows; assign monotonic event sequence numbers so refreshes never invent or lose state.
10. **C3 — Verify full backend flow.** Exercise clean start, reset/replay, duplicate invocation, branch abort, healthy sibling post-containment call, commit, and process cleanup. Fix any flakes before adding UI behavior.

**Stage C gate:** a single documented command repeatedly yields Account `STAGED → ABORTED`, Order `STAGED → COMMITTED`, committed promo `$0`, refund `$45`, and an accurate audit trail.

### Stage D — Real model workers and CLI

11. **D1 — Validate AWS model access and request format.** Confirm region, model ID, credentials, and one real Converse call before wiring the model into the demo. Keep this check independent of AWS-dependent tests and never log secrets.
12. **D2 — Implement managed parent/child workers.** Replace placeholder sleepers with workers that report readiness, accept only server-approved task roles, use separate branch identities, and return structured completion/exit results.
13. **D3 — Route model traffic through trusted services.** Add a backend Bedrock proxy and constrained tool loop. Model-proposed tools must pass through the same gateway and policy path; workers receive no AWS credentials or commit authority. Label model and controlled-test events distinctly.
14. **D4 — Make the CLI presenter-friendly.** Add start/status/events/stop commands or a polished run command with clear errors, stable IDs, readable event output, and cleanup on interruption.

**Stage D gate:** real model requests and tool proposals are visible as model-origin events; actual protected actions still require gateway authorization; Account termination is verified while Order remains live. If AWS is unavailable, the deterministic Stage C demo remains runnable and makes no real-model claim.

### Stage E — Mature live dashboard and presentation

15. **E1 — Establish a clear visual hierarchy.** Keep the tree, current run and branch state, staged/aborted/committed effects, committed business values, and event evidence readable at presentation distance and on the target display.
16. **E2 — Connect controls to confirmed backend outcomes.** Start, reset, contain, and release controls show pending feedback and only display terminal states after backend confirmation. Prevent duplicate clicks and surface recoverable errors in place.
17. **E3 — Make refresh/reconnect authoritative.** Use persisted snapshots plus SSE sequence replay or short polling. A page refresh reconstructs exact effect, branch, process, and event state.
18. **E4 — Refine demo pacing and copy.** Show the pending checkpoint before resolution, use explicit `MODEL` / `CONTROLLED_TEST` labels, display a compact commit receipt, and keep limitations legible without crowding the main story.

**Stage E gate:** a presenter can run the demo without explaining hidden state; all displayed committed values and process statuses come from backend evidence; reset and refresh work during rehearsal.

### Stage F — Rehearsal and submission

19. **F1 — Run the complete acceptance matrix.** Include stop/commit ordering, retry/idempotency, worker crash, reset cleanup, credential replay, and healthy sibling continuation.
20. **F2 — Rehearse three clean runs.** Start from documented commands, capture a backup recording, and fix timing, layout, wording, and reset issues observed in rehearsal.
21. **F3 — Package honest submission materials.** Update README/setup, AWS requirements, demo script, architecture, scope limits, known fallback behavior, and exact verification commands. No optional AWS service work until the core demo passes three consecutive runs.

**Stage F gate:** three consecutive runs complete within the presentation window from a clean reset, with no manual database edits or fabricated runtime events.

### Commit and review rhythm

- Use one commit per numbered item where practical; split an item further if it crosses schema, service, API, and UI layers.
- Use imperative, scoped messages such as `Add persisted demo business fixtures` and `Stage branch refund actions`.
- Before each commit, inspect the diff, keep unrelated user files out of it, and record the exact verification performed. Do not commit credentials, local databases, caches, generated build output, or unrelated workspace changes.
- Keep the demo runnable throughout. Prefer a completed vertical slice over half-implemented layers, and make each visible state transition traceable to persisted backend state.

---

## 12. Implementation status and acceptance record

**Roadmap A–F is implemented.** The work was committed in small local commits on `main`, from `Define trusted transactional demo policy` through `Document setup and repeatable demo workflow`. The reset/replay acceptance run exposed and fixed a missing root-branch reset; replay is now covered by a backend test.

**Acceptance evidence (2026-11-07):**

- Backend suite: `44 passed` (`pytest -q backend/tests`). Includes stage/overlay, commit retry, abort-before-commit, credential replay, scope containment, sibling continuation, process crash detection, cleanup, and reset/replay.
- Frontend: `4 passed` (`npm test`); production TypeScript/Vite build passes (`npm run build`).
- Three consecutive local CLI rehearsals from the same stable run ID each showed Order `$45` `STAGED → COMMITTED`, Account `$50` `STAGED → ABORTED`, committed promo credit `$0`, Account process `STOPPED` with exit code `0`, and Order still `RUNNING`. Remaining workers were then cleaned up.
- A full CLI-launched Bedrock demo completed end to end: the parent model delegated to Order and Account, their managed workers generated protected tool calls, Account's model-proposed `modify_billing` was denied and contained, its staged credit was aborted, and Order's staged `$45` refund was committed after worker completion. The audit trail marked model requests and proposals `MODEL`; Account exited `0` and Order remained running.
- The three repeatability rehearsals intentionally use the no-AWS `CONTROLLED_TEST` path. The unauthorized request in the live run was genuinely proposed by the model under an explicit red-team task; it demonstrates gateway enforcement, not autonomous attack discovery.

**Scope boundary:** external API side effects remain outside SQLite atomic commit, and AgentTree is not an operating-system sandbox. The red-team task is explicit and model-directed; the project does not claim autonomous threat discovery. Setup, commands, AWS prerequisites, and these limits are documented in the repository `README.md`.
