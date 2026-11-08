# AgentTree — AWS × A10 Hackathon 2026

## Implementation Guide and Acceptance Criteria

**Project:** AgentTree  
**Track:** A10 — Prompt 2: Agent Harness  
**Team:** 3 developers  
**Development time:** 24 hours  
**Strategy:** Backend-first security validation, parallel development, early end-to-end integration.

**Primary objective:** Build a working agent-security harness that can block an unauthorized tool operation, terminate one managed AI-agent branch, and prove that unaffected agents continue executing.

### Important Requirement Checkpoint

Before implementation, confirm whether the official Prompt 2 requires:

- an existing CLI coding agent or permits custom CLI-launched agents
- an MCP gateway specifically or permits an HTTP-based tool gateway

This plan assumes custom Bedrock-powered CLI agents and a FastAPI HTTP tool gateway are acceptable.

If MCP is mandatory, use the MCP Python SDK while preserving the same authorization logic.

---

# 1. Project Overview

## 1.1 Problem Statement

AI agents increasingly delegate tasks to specialized subagents.

These subagents may operate independently, invoke tools, access business systems, and perform actions on behalf of a parent agent.

When one subagent attempts an unauthorized operation, organizations need a mechanism to:

1. identify the responsible agent
2. block unauthorized operations
3. revoke its access
4. terminate its execution
5. preserve unaffected agents and workflows

Monitoring alone cannot provide these guarantees.

## 1.2 Solution

**AgentTree** is an execution and authorization harness for managed multi-agent workflows.

It provides:

- real-time agent hierarchy visualization
- independently managed agent processes
- explicitly delegated tool permissions
- centralized gateway authorization
- live tool-traffic monitoring
- unauthorized-operation blocking
- selective branch termination
- immediate revocation of protected-tool access
- continued execution of unaffected agents
- auditable execution history

## 1.3 Primary USP — Surgical Containment

AgentTree can terminate one problematic agent branch without shutting down the entire multi-agent workflow.

The system must prove three capabilities:

**Enforcement:** Unauthorized tool requests are rejected before execution.

**Containment:** The selected branch loses protected-tool access and its managed processes terminate.

**Continuity:** Unaffected agents continue executing legitimate operations.

## 1.4 Hackathon Requirements

The MVP must demonstrate:

- launching a CLI agent
- launching independently managed subagents
- routing protected tool requests through a central gateway
- displaying real agent traffic
- blocking an unauthorized action
- stopping a running agent
- preserving unrelated agent execution

## 1.5 Explicit Non-Goals

Do not implement:

- automatic rollback
- universal shell-command interception
- full operating-system sandboxing
- general-purpose workflow orchestration
- AI-generated security policies
- automatic malicious-intent detection
- support for every agent framework
- production multi-tenant authentication
- complex cloud deployment

AgentTree controls agents launched by its supervisor and protected business tools routed through its gateway.

---

# 2. Technical Architecture

## 2.1 Architecture Overview

```text
                    AGENTTREE CLI
        agenttree run --scenario customer-operations
                           |
                           v
                  FASTAPI BACKEND
                           |
             ┌─────────────┼─────────────┐
             |             |             |
             v             v             v
       SUPERVISOR    AUTHORIZATION    EVENT SERVICE
             |          GATEWAY           |
             |             |              |
             |             v              v
             |        BUSINESS DB      SSE STREAM
             |          SQLite            |
             |                            v
             |                      REACT DASHBOARD
             |
             v
       PARENT AI AGENT
       Amazon Bedrock
             |
       Delegation Request
             |
             v
         SUPERVISOR
             |
       ┌─────┴─────┐
       |           |
       v           v
   ORDER AGENT  ACCOUNT AGENT
     Bedrock       Bedrock
       |              |
       └──────┬───────┘
              |
              v
        TOOL GATEWAY
              |
       AUTHORIZATION
              |
       ALLOW / DENY
```

## 2.2 Technology Stack

| Component           | Technology                   | Purpose                                       |
| ------------------- | ---------------------------- | --------------------------------------------- |
| Backend             | Python 3.11+, FastAPI        | API and orchestration                         |
| AI reasoning        | Amazon Bedrock               | Parent and child agent reasoning              |
| Agent framework     | boto3 Converse API           | Baseline agent implementation                 |
| Optional agent SDK  | Strands Agents               | Use only if integration is straightforward    |
| Process execution   | Python subprocess            | Independent agent processes                   |
| Process supervision | psutil                       | Process identity and termination verification |
| Authorization       | Python policy evaluator      | Tool-level permissions                        |
| Runtime identity    | Per-agent bearer credentials | Authenticate gateway requests                 |
| Database            | SQLite                       | Agent state, audit events, mock business data |
| Frontend            | React + TypeScript           | Dashboard                                     |
| Visualization       | React Flow                   | Agent hierarchy                               |
| Styling             | Tailwind CSS                 | UI                                            |
| Live updates        | Server-Sent Events           | Event streaming                               |
| Testing             | pytest, httpx, Vitest        | Automated validation                          |
| AWS integration     | boto3 + IAM                  | Bedrock access                                |
| Optional AWS        | DynamoDB, CloudWatch         | Persistence and observability                 |

## 2.3 Runtime Architecture

Use one authoritative FastAPI backend process.

The backend owns:

- Agent registry
- Process supervisor
- Agent credentials
- Authorization state
- Gateway execution
- Branch termination
- Audit events

The CLI communicates with the backend through `POST /runs`.

The CLI does not independently own child-process handles.

For the local demonstration, run Uvicorn with one worker and without automatic reload.

## 2.4 Security Boundary

Only trusted backend code can access the protected mock business database.

Agent processes must use the gateway for registered business operations.

The gateway derives agent identity from its runtime credential rather than trusting caller-provided identifiers.

A separate operator credential protects administrative endpoints.

**Limitation:** This is not a hostile-process sandbox. Agents running under the same operating-system user may have access to local resources outside the gateway. The MVP does not claim to prevent those actions.

---

# 3. Repository Structure

```text
agenttree/
├── README.md
├── IMPLEMENTATION_PLAN.md
├── .env.example
├── .gitignore
│
├── contracts/
│   ├── openapi.yaml
│   ├── events.schema.json
│   └── permissions.json
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── models/
│   │   ├── routes/
│   │   ├── services/
│   │   │   ├── hierarchy.py
│   │   │   ├── authorization.py
│   │   │   ├── gateway.py
│   │   │   ├── supervisor.py
│   │   │   ├── demo_control.py
│   │   │   └── events.py
│   │   ├── tools/
│   │   └── storage/
│   ├── requirements.txt
│   └── tests/
│
├── agents/
│   ├── runner.py
│   ├── parent_agent.py
│   ├── order_agent.py
│   ├── account_agent.py
│   ├── bedrock_client.py
│   └── gateway_client.py
│
├── cli/
│   └── agenttree.py
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── services/
│   │   └── types/
│   └── package.json
│
├── demo/
│   ├── fixtures/
│   ├── run_demo.py
│   ├── reset_demo.py
│   └── DEMO_SCRIPT.md
│
└── infrastructure/
    └── aws/
```

---

# 4. Shared Contracts

## 4.1 Core Entities

### Run

```text
run_id
status
scenario
created_at
stopped_at
```

### Agent

```text
agent_id
run_id
parent_agent_id
branch_id
role
status
task_state
pid
process_create_time
allowed_tools
started_at
stopped_at
```

### Event

```text
event_id
run_id
agent_id
event_type
tool_name
arguments
decision
reason_code
origin
timestamp
details
```

### Branch

A branch consists of a selected agent and its managed descendants.

Stopping a child branch must not terminate its parent or siblings.

## 4.2 Process States

```text
CREATED
RUNNING
STOPPING
STOPPED
COMPLETED
FAILED
```

## 4.3 Task States

```text
DELEGATING
READING
WAITING_FOR_FULFILLMENT
WAITING_FOR_INSTRUCTION
PROCESSING
DONE
```

Task states are separate from process states.

An agent can remain `RUNNING` while waiting for an external event.

## 4.4 Authorization Decisions

```text
ALLOW
DENY
```

Denial reasons:

```text
TOOL_NOT_DELEGATED
BRANCH_STOPPED
INVALID_AGENT_IDENTITY
UNKNOWN_TOOL
RUN_STOPPED
INVALID_ARGUMENTS
```

## 4.5 Permission Configuration

| Agent         | Allowed tools                                            |
| ------------- | -------------------------------------------------------- |
| Parent Agent  | read_orders, process_order, read_account, modify_billing |
| Order Agent   | read_orders, process_order                               |
| Account Agent | read_account                                             |

Permissions are defined in server-side configuration.

The LLM cannot grant permissions.

A delegated permission set must be a subset of the parent's permissions and the approved child-role template.

## 4.6 API Endpoints

| Method | Endpoint                                  | Purpose                     |
| ------ | ----------------------------------------- | --------------------------- |
| GET    | `/health`                                 | Backend health              |
| POST   | `/runs`                                   | Launch run                  |
| GET    | `/runs/{run_id}`                          | Run status                  |
| GET    | `/runs/{run_id}/tree`                     | Agent hierarchy             |
| GET    | `/runs/{run_id}/events`                   | Audit events                |
| GET    | `/events/stream`                          | Live SSE events             |
| POST   | `/branches/{branch_id}/stop`              | Stop selected branch        |
| GET    | `/branches/{branch_id}/status`            | Branch status               |
| POST   | `/gateway/tools/call`                     | Protected tool execution    |
| POST   | `/demo/runs/{run_id}/probe-unauthorized`  | Controlled security test    |
| POST   | `/demo/runs/{run_id}/release-fulfillment` | Release waiting Order Agent |
| GET    | `/demo/runs/{run_id}/evidence`            | Demo evidence               |

Administrative endpoints require operator authorization.

Agent credentials cannot invoke administrative operations.

## 4.7 Runtime Credentials

Generate an independent credential for each agent using:

```python
secrets.token_urlsafe(32)
```

Requirements:

- bind each credential to an agent, run, branch, and permissions
- store credential hashes or secure references server-side
- never log raw credentials
- derive agent identity from the credential
- reject missing or invalid credentials
- revoke credentials when the branch stops
- prevent child agents from modifying permission records

For the local MVP, credentials may be delivered through a narrowly scoped process-launch mechanism.

## 4.8 Protected Business Tools

**`read_orders(order_id)`**

Returns order information.

**`process_order(order_id)`**

Changes an order from `PENDING` to `COMPLETED`, provided fulfillment has been confirmed.

**`read_account(customer_id)`**

Returns account information.

**`modify_billing(customer_id, new_plan)`**

Registered protected operation used for authorization testing.

The Account Agent is not permitted to invoke it.

## 4.9 Authorization and Revocation

Every gateway call must validate:

1. runtime credential
2. run status
3. branch status
4. registered tool name
5. delegated permission
6. argument schema
7. business preconditions

Denied calls must never reach the business executor.

For state-changing operations, synchronize authorization and database mutation with branch revocation.

Once revocation commits, no new protected mutation from that branch may commit.

Already completed operations are not rolled back.

---

# 5. Stage-by-Stage Implementation

## Stage 0 — Setup and Architecture Freeze

**Target: Hours 0–2**

### Implement

- Repository structure.
- Python environment and dependencies.
- FastAPI application.
- `/health` endpoint.
- React/Vite application.
- Tailwind configuration.
- React Flow dependency.
- pytest and Vitest configuration.
- `.env.example`.
- Shared API schemas.
- AWS credential validation.
- Bedrock connectivity test.

Verify the AWS Workshop Studio role, region, model access, and temporary credentials.

Use a short Strands SDK integration test if desired. Otherwise, proceed with boto3 Converse.

### Acceptance Criteria

- Backend starts.
- Frontend starts.
- Health endpoint returns 200.
- API contracts are committed.
- Real Bedrock request succeeds.
- AWS credentials are not committed.
- Tests execute successfully.

### Exit Gate

Both applications run independently and the API contracts are frozen.

---

## Stage 1 — Agent Hierarchy

**Target: Hours 2–4**

### Implement

- SQLite run registry.
- Agent registry.
- Parent-child relationships.
- Branch identification.
- Agent status persistence.
- Hierarchy retrieval endpoint.
- Initial React Flow hierarchy.

### Acceptance Criteria

- One parent and two children can be registered.
- Every agent has a unique ID.
- Parent-child relationships are correct.
- Invalid parent references are rejected.
- Cyclic relationships are rejected.
- API returns the expected hierarchy.
- Frontend renders the hierarchy.

### Validation

Test:

- valid parent creation
- valid child creation
- duplicate agent ID
- unknown parent
- cyclic hierarchy
- persisted hierarchy retrieval

### Exit Gate

The backend represents the hierarchy correctly and the frontend renders the same structure.

---

## Stage 2 — CLI Launcher and Process Supervisor

**Target: Hours 2–5, parallel with Stage 1**

### Implement

The FastAPI backend owns the supervisor.

The CLI calls:

```http
POST /runs
```

The supervisor launches independently managed agent processes using Python subprocesses.

For macOS/Linux, use separate process sessions:

```python
subprocess.Popen(
    command,
    start_new_session=True
)
```

Track:

- Agent ID.
- PID.
- Process creation time.
- Process handle.
- Branch ID.
- Parent ID.
- Process status.

Implement:

- process monitoring
- unexpected-exit detection
- graceful shutdown
- forced termination
- descendant cleanup
- supervisor shutdown cleanup

Use a single Uvicorn worker without `--reload` for the live demonstration.

### Acceptance Criteria

- CLI launches a run.
- Supervisor launches independently managed processes.
- Parent and children have distinct identities.
- One child can terminate without stopping another.
- Unexpected process exit becomes FAILED.
- No orphaned managed processes remain after cleanup.

### Exit Gate

Real process ownership and independent termination work.

---

## Stage 3 — Central Gateway and Authorization

**Target: Hours 4–6**

### Implement

- Gateway endpoint.
- Agent credential issuance.
- Credential verification.
- Permission registry.
- Tool dispatcher.
- Strict argument validation.
- Mock business database.
- ALLOW/DENY decisions.
- Audit events.

All protected business operations must pass through the gateway.

### Acceptance Criteria

- Order Agent can invoke `read_orders`.
- Order Agent can invoke `process_order` when business preconditions are satisfied.
- Account Agent can invoke `read_account`.
- Account Agent cannot invoke `modify_billing`.
- Missing credentials are rejected.
- Invalid credentials are rejected.
- Unknown tools are rejected.
- Spoofed agent identities cannot escalate permissions.
- Denied operations cause no database mutation.

### Exit Gate

The gateway performs real authorization and execution.

---

## Stage 4 — Branch-Level Containment

**Target: Hours 6–8**

### Implement

- Branch descendant lookup.
- Administrative stop endpoint.
- Branch-state revocation.
- Credential invalidation.
- Process termination.
- Process-exit verification.
- Audit logging.
- Idempotent stop requests.

### Termination Sequence

1. Identify the selected branch and descendants.
2. Atomically mark the branch inactive.
3. Revoke protected-tool access.
4. Reject subsequent gateway requests.
5. Signal managed processes to terminate.
6. Wait for graceful exit.
7. Force termination after timeout.
8. Verify process exit.
9. Mark STOPPED only after confirmation.

If termination cannot be confirmed, return a termination error rather than incorrectly marking STOPPED.

### Acceptance Criteria

- Account Agent loses gateway access.
- Account Agent process exits.
- Revoked credentials cannot execute protected tools.
- Order Agent remains alive.
- Parent remains alive.
- Order Agent successfully invokes another permitted tool after termination.
- Repeated stop requests are idempotent.
- No orphaned managed descendants remain.

### Mandatory Milestone

**By approximately Hour 8, demonstrate real backend-only selective containment.**

Bedrock and the frontend are not required for this initial technical proof.

### Exit Gate

Surgical containment works independently of the dashboard.

---

## Stage 5 — Real Amazon Bedrock Agents

**Target: Hours 8–11**

### Implement

- Bedrock client.
- Parent Agent.
- Order Agent.
- Account Agent.
- Structured delegation requests.
- Supervisor-side delegation validation.
- Gateway tool adapters.
- Model activity events.
- Model timeouts and error handling.

### Delegation Workflow

1. Parent receives customer-operations request.
2. Parent uses Bedrock to identify tasks.
3. Bedrock returns structured requests for approved roles.
4. Supervisor validates each role.
5. Supervisor launches child processes.
6. Children use Bedrock for their assigned tasks.
7. Children invoke authorized tools through the gateway.

The parent cannot choose arbitrary executables, credentials, or permissions.

### Acceptance Criteria

- Parent makes a real Bedrock call.
- Both children make real Bedrock calls.
- Parent produces valid delegation requests.
- Supervisor rejects unsupported roles.
- Both children invoke legitimate protected tools.
- Gateway records their requests.
- Authorization does not depend on LLM judgment.
- Model errors are visible and bounded.

### Exit Gate

Real Bedrock agents execute tasks through the protected gateway.

---

## Stage 6 — Deterministic Demo Scenario

**Target: Hours 11–14**

### Business Fixtures

Customer:

```text
Customer ID: C104
Account Plan: basic
```

Order:

```text
Order ID: ORD-104
Status: PENDING
Fulfillment Confirmed: false
```

### Order Agent Workflow

1. Receive order-processing task.
2. Call `read_orders`.
3. Validate the order.
4. Enter `WAITING_FOR_FULFILLMENT`.
5. Remain alive while waiting.
6. Receive fulfillment confirmation.
7. Call `process_order`.
8. Complete the order.

### Account Agent Workflow

1. Receive account-review task.
2. Call `read_account`.
3. Enter `WAITING_FOR_INSTRUCTION`.
4. Remain alive.
5. Become the target of a controlled unauthorized-operation test.
6. Receive gateway denial.
7. Continue waiting until terminated.

Use application events or controlled polling for waiting.

Do not depend on arbitrary sleep durations or repeated Bedrock calls.

### Unauthorized Operation

A demo-controlled test invokes:

```json
{
  "tool": "modify_billing",
  "arguments": {
    "customer_id": "C104",
    "new_plan": "premium"
  }
}
```

The request must use the Account Agent's runtime credential and the real gateway authorization path.

Expected:

```json
{
  "decision": "DENY",
  "reason_code": "TOOL_NOT_DELEGATED"
}
```

The billing record remains unchanged.

**Important:** Label the event `CONTROLLED_TEST` if the request originates from the demo driver. Do not present it as a spontaneous Bedrock-generated attack.

### Acceptance Criteria

- Both child processes remain alive during the violation.
- Unauthorized request is genuinely denied.
- Billing remains unchanged.
- Account Agent can be stopped while running.
- Revoked credential is denied.
- Order Agent continues after Account Agent stops.
- Order becomes COMPLETED.

### Exit Gate

The complete scenario runs reliably through backend APIs.

---

## Stage 7 — Live Dashboard Integration

**Target: Hours 11–17, parallel with Stage 6**

### Implement

One main dashboard containing:

- Agent hierarchy.
- Parent-child connections.
- Process status.
- Task status.
- Delegated permissions.
- Live gateway activity.
- ALLOW/DENY decisions.
- Denial reasons.
- Event origin labels.
- Stop Branch button.
- Process-termination evidence.
- Business-state evidence.

### Real-Time Communication

Use:

```http
GET /events/stream
```

The frontend first retrieves a hierarchy snapshot, then subscribes to SSE updates.

Support reconnection and recovery of missed events.

### Stop Branch UI

When clicked:

1. Request confirmation.
2. Call the real backend stop endpoint.
3. Display STOPPING.
4. Wait for backend-confirmed termination.
5. Display STOPPED.
6. Show errors if termination fails.

Do not display STOPPED based only on a successful button click.

### Acceptance Criteria

- Real agents appear in the hierarchy.
- Gateway events appear without refreshing.
- Unauthorized operations display actual denial reasons.
- Stop Branch invokes backend termination.
- Process status reflects verified backend state.
- Order Agent continues producing events.
- Reconnecting reconstructs the current hierarchy.

### Exit Gate

The dashboard accurately represents real backend execution.

---

## Stage 8 — Optional AWS Persistence and Observability

**Only after all P0 requirements pass.**

### Optional Implementations

- DynamoDB-backed event persistence.
- DynamoDB run and hierarchy records.
- CloudWatch application logs.
- AWS trace identifiers.
- least-privilege IAM policies.

Keep SQLite available.

DynamoDB must not replace the local supervisor's ownership of live process handles.

### Acceptance Criteria

If implemented:

- records persist successfully
- events remain retrievable
- logs contain no credentials
- frontend continues functioning
- AWS failures produce visible errors
- local fallback remains operational

### Exit Gate

Optional AWS functionality does not destabilize the core demonstration.

---

# 6. Final Three-Minute Demo

## Demo Title

**AgentTree: Stop One Rogue AI Agent, Not the Entire Team**

## Demo Sequence

| Time      | Action                               | Technical evidence                          |
| --------- | ------------------------------------ | ------------------------------------------- |
| 0:00–0:30 | Launch AgentTree                     | CLI, Bedrock delegation, child processes    |
| 0:30–1:00 | Execute legitimate operations        | Gateway ALLOW events                        |
| 1:00–1:30 | Trigger controlled billing violation | Gateway DENY, unchanged billing             |
| 1:30–2:00 | Stop Account Branch                  | Revocation and verified process exit        |
| 2:00–2:20 | Verify revoked credential            | Gateway denies further access               |
| 2:20–2:45 | Release fulfillment confirmation     | Order Agent processes order                 |
| 2:45–3:00 | Show evidence                        | Audit trail, process status, business state |

## Expected Final State

```text
CUSTOMER OPERATIONS AGENT
Status: RUNNING
│
├── ORDER AGENT
│   Status: RUNNING
│   Tool: process_order
│   Decision: ALLOW
│   Order: COMPLETED
│
└── ACCOUNT AGENT
    Status: STOPPED
    Tool: modify_billing
    Decision: DENY
    Reason: TOOL_NOT_DELEGATED
    Process Exit: VERIFIED
```

## Final Evidence

The dashboard must prove:

- Account Agent's unauthorized billing request was denied.
- Billing remained unchanged.
- Account Agent's process exited.
- Its credential no longer works.
- Parent Agent remained active.
- Order Agent successfully completed an operation after containment.

## Closing Statement

"AgentTree doesn't just monitor AI agents. It enforces their permissions, stops a problematic branch, and proves the rest of the autonomous workflow can continue."

---

# 7. Demo Setup and Reliability

## Required Commands

### Start Backend

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use one worker and no automatic reload.

### Start Frontend

```bash
cd frontend
npm install
npm run dev
```

### Reset Demo

```bash
python demo/reset_demo.py
```

### Launch Demo

```bash
python demo/run_demo.py
```

### Backend Tests

```bash
python -m pytest backend/tests -q
```

### Frontend Tests

```bash
cd frontend
npm test -- --run
npm run build
```

Document any required package-installation or environment-activation steps so these commands work from the intended directories.

## Demo Reset Requirements

The reset command must:

1. Stop existing managed demo processes.
2. Verify cleanup.
3. Reset demo agent records.
4. Reset mock business data.
5. Restore the initial order and account state.
6. Preserve unrelated records.

Do not manually edit the database during the presentation.

## Reliability Requirements

- Use actual Bedrock calls.
- Use actual gateway requests.
- Use actual process termination.
- Use deterministic demo checkpoints.
- Use bounded timeouts.
- Surface AWS/model failures.
- Never silently replace failed operations with simulated success.
- Complete three consecutive successful rehearsals.
- Record one successful real demonstration as backup.

---

# 8. Security and Reliability Testing

| Test                               | Expected Result                                  |
| ---------------------------------- | ------------------------------------------------ |
| Missing agent credential           | DENY                                             |
| Invalid agent credential           | DENY                                             |
| Agent identity impersonation       | DENY                                             |
| Child permission escalation        | Rejected                                         |
| Unknown tool                       | DENY                                             |
| Invalid tool arguments             | DENY                                             |
| Account modifies billing           | DENY                                             |
| Billing after denied request       | Unchanged                                        |
| Stop Account Branch                | Credential revoked                               |
| Account process termination        | Verified                                         |
| Reuse revoked credential           | DENY                                             |
| Duplicate stop request             | Idempotent                                       |
| Unexpected child crash             | FAILED                                           |
| Termination timeout                | Error; never false STOPPED                       |
| Order operation after Account stop | ALLOW                                            |
| Parent after Account stop          | Still active                                     |
| Revocation versus mutation race    | No new mutation commits after revocation commits |
| SSE reconnect                      | Current state recovered                          |
| Demo reset                         | Clean initial state                              |
| Repeated demo                      | No stale processes                               |
| Audit inspection                   | No leaked credentials                            |

All mandatory tests must pass before submission.

---

# 9. Development Priorities

## P0 — Mandatory

- CLI launch
- real parent and child processes
- real Bedrock inference
- validated task delegation
- central protected-tool gateway
- per-agent credentials
- explicit permissions
- unauthorized-operation denial
- branch credential revocation
- verified process termination
- healthy sibling continuation
- live hierarchy
- audit events
- repeatable demo

## P1 — Important

- dashboard polish
- event filtering
- better process details
- clear error messages
- demo recording
- presentation improvements

## P2 — Optional

- DynamoDB
- CloudWatch
- cloud deployment
- additional agent types
- advanced visualizations

Do not implement P2 until P0 is stable.

---

# 10. Development Time Budget

| Time        | Milestone                                          |
| ----------- | -------------------------------------------------- |
| Hours 0–2   | Setup, contracts, Bedrock connectivity             |
| Hours 2–4   | Agent hierarchy and process supervisor             |
| Hours 4–6   | Gateway, credentials, permissions                  |
| Hours 6–8   | Real branch containment                            |
| Hours 8–11  | Bedrock parent/child integration                   |
| Hours 11–14 | Deterministic demo scenario                        |
| Hours 14–17 | Live dashboard integration and testing             |
| Hours 17–20 | Reliability improvements and optional AWS features |
| Hours 20–23 | Full rehearsals, documentation, backup recording   |
| Hours 23–24 | Final submission                                   |

These are target milestones, not strictly sequential work assignments. Independent components should be developed in parallel.

**Mandatory milestone:** A working backend-only containment demonstration by approximately Hour 8.

If delayed, remove optional AWS features and UI enhancements before reducing security functionality.

---

# 11. Rules for AI Coding Agents

Every coding agent must:

1. implement only the assigned stage or explicitly scoped component
2. preserve agreed API contracts
3. avoid implementing unrelated future features
4. add automated tests
5. execute tests before reporting completion
6. report exact test results
7. identify incomplete functionality
8. document security limitations
9. never simulate successful authorization or termination
10. never mark a stage complete if mandatory acceptance criteria fail
11. keep the main branch runnable
12. never commit AWS credentials

## Required Report After Each Stage

**Implemented:** Features completed.

**Files changed:** Exact files added or modified.

**Tests executed:** Commands and results.

**Acceptance criteria:** PASS or FAIL for each condition.

**Known limitations:** Unsupported behavior or remaining issues.

**Next stage:** Identify but do not start automatically.

---

# 12. Definition of Done

AgentTree is submission-ready when:

- [ ] CLI launches a managed run.
- [ ] Parent uses real Amazon Bedrock inference.
- [ ] Both child agents use real Bedrock inference.
- [ ] Delegation is restricted to approved roles.
- [ ] Supervisor launches independently managed processes.
- [ ] Agent hierarchy is visible.
- [ ] Protected tools execute through the gateway.
- [ ] Agent identity is authenticated.
- [ ] Delegated permissions are enforced.
- [ ] Unauthorized billing modification is denied.
- [ ] Billing data remains unchanged.
- [ ] Operator can stop a selected branch.
- [ ] Branch credentials are revoked.
- [ ] Managed processes terminate.
- [ ] Process exit is verified.
- [ ] Revoked credentials cannot invoke protected tools.
- [ ] Parent remains active.
- [ ] Order Agent successfully processes an order after Account Agent termination.
- [ ] Dashboard shows real events and verified states.
- [ ] Demo reset works.
- [ ] Full demo succeeds three consecutive times.
- [ ] README includes setup, architecture, tests, limitations, and demo instructions.

---

# 13. AWS Integration Strategy

## Confirmed Access

AWS Workshop Studio access is available.

Validate the current IAM role, AWS region, Bedrock model permissions, and credential lifetime during Stage 0.

## AWS Priorities

**Required:** Amazon Bedrock, boto3, AWS IAM credentials.

**Optional:** DynamoDB and CloudWatch.

Meaningful AWS integration comes from actual Bedrock reasoning and tool selection in the managed agents.

Additional AWS services should not be introduced merely to increase the number of AWS components.

---

# 14. Judging Strategy

## Technology

Demonstrate real process supervision, permission enforcement, Bedrock integration, and selective termination.

## Polish

Present one cohesive dashboard with a live hierarchy, readable tool events, and clear termination evidence.

## Innovativeness

Emphasize branch-level surgical containment rather than generic agent monitoring.

## AWS Usage

Show actual Bedrock-powered delegation and agent tool use.

## Completeness

Demonstrate the full workflow without manual database manipulation or simulated security outcomes.

## Primary Story

"We built an execution and authorization harness that can stop one problematic AI subagent without shutting down the rest of the autonomous workflow. AgentTree proves this through real Bedrock agents, gateway-enforced permissions, verified process termination, and successful continuation of unaffected agents."

---

# 15. Final Development Principle

**Build the smallest working system that proves surgical containment is real.**

Prioritize:

1. real gateway authorization
2. real agent processes
3. verified branch termination
4. revoked credentials
5. successful sibling continuation
6. real Bedrock integration
7. clear live visualization

A reliable, complete demonstration is more valuable than additional AWS services, complex orchestration, or decorative features.
