# AgentTree

AgentTree is a transactional governance framework for multi-agent AI systems. It demonstrates how autonomous agents can operate within scoped permissions, validate tool usage, and commit approved business actions only after verification.

The project models a customer-transaction workflow with a coordinator agent and specialized Order and Account worker agents. Protected operations are routed through a trusted gateway, staged before they are applied, and only committed when the system confirms they are valid and safe. If a branch violates its policy, the system aborts its pending change and keeps the rest of the workflow running.

A live dashboard visualizes the agent hierarchy, tool decisions, staged effects, and final business state in real time. The default demo path can run against Amazon Bedrock when AWS credentials and model access are available, and a deterministic no-AWS fallback is also included for local validation and demo scenarios.

## Why this project matters

Modern AI systems often need more than prompt execution. They need:

- role-based access control for protected actions
- verified task completion before commit
- isolation of unsafe or out-of-scope tool actions
- clear visibility into how decisions are made and recorded

AgentTree is designed to explore that operational layer directly. It treats agent workflows as transactional systems rather than uncontrolled tool invocations.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer and npm
- AWS credentials and Bedrock model access for the live model-driven flow
- An optional no-AWS deterministic demo fallback for local use without cloud access

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

## Run the application

Start the backend in one terminal:

```bash
source .venv/bin/activate
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Start the dashboard in another terminal:

```bash
cd frontend
npm run dev
```

Open the frontend URL in a browser (typically `http://localhost:5173`).

Run the demo from a third terminal:

```bash
source .venv/bin/activate
python cli/agenttree.py demo
```

For the no-AWS deterministic path:

```bash
python cli/agenttree.py demo --controlled
```

## Architecture overview

The system is organized around a few core concepts:

- coordinator delegation: a parent agent splits customer work into tasks
- branch execution: worker agents perform scoped actions and record effects
- gateway enforcement: protected tools are authorized through a trusted policy layer
- staged transactions: valid changes are prepared before being committed
- supervisor validation: branch completion is checked before final commit

This gives the project a clear operational pattern: delegate, validate, stage, and commit.

## Model-driven demo configuration

To run the live Bedrock-backed flow, configure AWS credentials in the shell used to start the backend:

```bash
export AWS_REGION=us-east-1
export AWS_BEDROCK_MODEL_ID=amazon.nova-micro-v1:0
```

The selected AWS identity must have permission to call the configured Bedrock model.

## Useful commands

```bash
python cli/agenttree.py reset agenttree-live-demo
python cli/agenttree.py status agenttree-live-demo
python cli/agenttree.py events agenttree-live-demo --after-seq 0
python cli/agenttree.py stop agenttree-live-demo --branch order-agent
```

## Validation

From the repository root:

```bash
pytest -q backend/tests
```

From the frontend directory:

```bash
npm test
npm run build
```

The repository includes a deterministic acceptance flow and a real live demo path. The no-AWS fallback validates the expected transaction behavior without requiring cloud resources.

## Scope and limits

- The commit model applies to the local transactional workflow used by the application.
- AgentTree manages processes it launches and enforces the tool calls that go through its gateway.
- Permission decisions are controlled by server-side policies, not by the model itself.
- The cloud-backed demo depends on valid AWS credentials, model access, and region configuration.

## License

This project is provided for learning, demonstration, and experimentation. Use it as a local reference implementation for agent governance patterns and workflow orchestration.
