# AgentTree

AgentTree is a transactional execution harness for managed AI agents. It routes protected tool calls through a trusted gateway and keeps approved business changes staged until a branch is ready to commit. A policy violation revokes and stops that branch, aborting its pending changes while healthy branches continue.

The primary hackathon demo uses Amazon Bedrock to delegate work to live Order and Account worker processes. The workers decide which protected tools to call; every proposal goes through the gateway. The Account task includes an explicit red-team probe: after staging a $50 credit, it requests a billing change for customer `C999`. The gateway denies the tool call, revokes and stops Account, and aborts its pending credit. Order independently stages a $45 refund, completes its task, and is committed by the trusted supervisor after its state is verified. Events identify their source as `MODEL`, `SUPERVISOR`, or `OPERATOR`.

A deterministic presentation is also available as a no-AWS fallback. Its actions are labeled `CONTROLLED_TEST` and must not be described as model-generated.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer and npm
- AWS credentials with Amazon Bedrock model access for the primary live demo; the controlled fallback runs without AWS credentials

## Install

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
cd frontend
npm ci
cd ..
```

## Run the dashboard and demo

Start the backend in one terminal from the repository root:

```bash
source .venv/bin/activate
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Start the dashboard in another terminal:

```bash
cd frontend
npm run dev
```

Open the Vite URL (normally `http://localhost:5173`). The dashboard selects `agenttree-live-demo` by default and rebuilds its view from persisted backend snapshots.

Run the Bedrock-driven demo from a third terminal at the repository root:

```bash
source .venv/bin/activate
python cli/agenttree.py demo
```

The parent model delegates to Order and Account. Their Bedrock-powered workers call `read_order`, `stage_refund`, `read_account`, and `stage_promo_credit`; the Account worker then proposes `modify_billing`. The gateway denies and contains that branch. The supervisor commits Order only after the Order worker reports completion and the expected staged refund is present. The command prints the model delegation and persisted evidence; the dashboard shows the same run. Set `AWS_REGION` and `AWS_BEDROCK_MODEL_ID` in the backend shell when they differ from the defaults.

For the deterministic no-AWS fallback:

```bash
python cli/agenttree.py demo --controlled
```

To reset either run, stop its managed workers, and restore its fixtures:

```bash
python cli/agenttree.py reset agenttree-live-demo
```

Other useful commands:

```bash
python cli/agenttree.py status agenttree-live-demo
python cli/agenttree.py events agenttree-live-demo --after-seq 0
python cli/agenttree.py stop agenttree-live-demo --branch order-agent
```

## Model-driven worker tasks

To launch managed workers with real Amazon Bedrock Converse calls, configure credentials in the shell that starts the backend and set the region/model if needed:

```bash
export AWS_REGION=us-east-1
export AWS_BEDROCK_MODEL_ID=amazon.nova-micro-v1:0
```

The AWS identity needs permission to call the selected Bedrock model. Use the existing credential helper only in a trusted local environment; never commit its output, credential files, or terminal transcripts. Launch a run and assign a task to a child role:

```bash
python cli/agenttree.py run model-run \
  --task 'order-agent=Review order ORD-882 and summarize the allowed refund action.'
python cli/agenttree.py status model-run
python cli/agenttree.py events model-run
python cli/agenttree.py stop model-run
```

Workers receive no AWS credentials. The backend calls Bedrock and routes proposed tools back through the same role policy and gateway. Account's `modify_billing` schema is visible only to let the live security scenario demonstrate a real model-proposed but unauthorized tool call; it is absent from the trusted Account role policy and is rejected by the gateway.

## Validation

From the repository root:

```bash
pytest -q backend/tests
```

From `frontend/`:

```bash
npm test
npm run build
```

The controlled acceptance flow verifies `stage_refund $45 → COMMITTED`, `stage_promo_credit $50 → ABORTED`, committed promo credit `$0`, branch-specific process termination, and continued Order branch activity. Three consecutive controlled CLI rehearsals and a full Bedrock-driven live run were completed against the local API. The `demo` command runs the live path by default.

## Scope and limits

- Atomic commit applies only to the controlled SQLite transaction. Arbitrary external API operations are not atomic or automatically reversible.
- AgentTree supervises processes it launches and enforces tools routed through its gateway. It is not a general operating-system sandbox.
- Permissions come from the trusted server-side role policy; the model cannot grant itself access.
- The live probe is explicitly requested as a red-team task and is generated as a real model tool call; this is not a claim of autonomous attack discovery or general prompt-injection detection.
- Optional AWS event export is separate from the core local audit trail; the deterministic workflow does not need a cloud database or CloudWatch.
