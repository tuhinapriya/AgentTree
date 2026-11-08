# AgentTree dashboard

This directory contains the React and TypeScript dashboard for the AgentTree demo.
The frontend reads run state from the FastAPI backend at `http://localhost:8000` by
default and polls for new events while a run is active.

From this directory:

```bash
npm ci
npm run dev
```

Start the backend from the repository root with the instructions in the root
[README](../README.md). Use **Run demo again** in the dashboard to start a fresh
Bedrock-backed run while preserving the previous run's history.
