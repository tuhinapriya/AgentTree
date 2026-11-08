# AgentTree

AgentTree is a transactional execution harness for managed AI agents. It routes protected tool calls through a trusted gateway and keeps approved business changes staged until a branch is ready to commit. A policy violation revokes and stops that branch, aborting its pending changes while healthy branches continue.

The hackathon demo uses a controlled SQLite business database. It demonstrates an Order branch staging and committing a $45 refund while an Account branch stages a $50 credit, receives a clearly labeled controlled policy probe, and is contained. The credit is aborted; the committed account credit remains $0. Events marked `CONTROLLED_TEST` are scripted demo actions. They are not represented as model-generated decisions.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer and npm
- AWS credentials with Amazon Bedrock model access only for model-driven tasks; the deterministic demo runs without AWS credentials

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

Open the Vite URL (normally `http://localhost:5173`). The dashboard selects `agenttree-transactional-demo` by default and rebuilds its view from persisted backend snapshots.

Run the repeatable controlled presentation from a third terminal at the repository root:

```bash
source .venv/bin/activate
python cli/agenttree.py demo
```

The demo reuses the stable run ID, cleans up any previous managed workers, resets the fixtures, then stages both effects, runs the labeled policy probe, contains Account, verifies Order can still read its resource, and commits the refund. The command prints a JSON evidence snapshot; the dashboard shows the same persisted state. The Order and parent workers remain running after success so the presenter can inspect the live hierarchy.

To restore fixtures and stop workers:

```bash
python cli/agenttree.py reset agenttree-transactional-demo
```

Other useful commands:

```bash
python cli/agenttree.py status agenttree-transactional-demo
python cli/agenttree.py events agenttree-transactional-demo --after-seq 0
python cli/agenttree.py stop agenttree-transactional-demo --branch order-agent
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

Workers receive no AWS credentials. The backend calls Bedrock and routes proposed tools back through the same role policy and gateway. Model requests and tool proposals are marked `MODEL`; the default transactional presentation remains marked `CONTROLLED_TEST`.

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

The acceptance flow verifies `stage_refund $45 → COMMITTED`, `stage_promo_credit $50 → ABORTED`, committed promo credit `$0`, branch-specific process termination, and continued Order branch activity. Three consecutive end-to-end CLI rehearsals were completed against the local API.

## Scope and limits

- Atomic commit applies only to the controlled SQLite transaction. Arbitrary external API operations are not atomic or automatically reversible.
- AgentTree supervises processes it launches and enforces tools routed through its gateway. It is not a general operating-system sandbox.
- Permissions come from the trusted server-side role policy; the model cannot grant itself access.
- The demo's unauthorized billing probe is intentionally scripted and labeled. A model-generated attack or general prompt-injection detector is not claimed.
- Optional AWS event export is separate from the core local audit trail; the deterministic workflow does not need a cloud database or CloudWatch.
