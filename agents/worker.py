"""Minimal identity-aware worker runtime managed by AgentTree's supervisor."""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading
from datetime import datetime, timezone

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentTree managed worker")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--role", choices=("parent", "order", "account"), required=True)
    args = parser.parse_args()

    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    print(json.dumps({
        "type": "WORKER_READY",
        "run_id": args.run_id,
        "agent_id": args.agent_id,
        "role": args.role,
        "pid": os.getpid(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }), flush=True)

    task = os.getenv("AGENTTREE_TASK")
    credential = os.getenv("AGENTTREE_CREDENTIAL")
    base_url = os.getenv("AGENTTREE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    if task and credential:
        _run_agent_task(base_url, args.run_id, args.agent_id, args.role, task, credential)

    while not stopping.wait(1):
        pass
    return 0


def _run_agent_task(base_url, run_id, agent_id, role, task, credential):
    messages = [{"role": "user", "content": [{"text": task}]}]
    headers = {"Authorization": f"Bearer {credential}"}

    for _ in range(6):
        model_response = requests.post(
            f"{base_url}/runs/{run_id}/agents/{agent_id}/model/converse",
            json={"messages": messages},
            headers=headers,
            timeout=60,
        )
        model_response.raise_for_status()
        result = model_response.json()
        message = result["message"]
        messages.append(message)
        tool_uses = [block["toolUse"] for block in message.get("content", []) if "toolUse" in block]
        if not tool_uses:
            if result.get("stop_reason") != "end_turn":
                raise RuntimeError(f"Model ended unexpectedly: {result.get('stop_reason')}")
            completed = requests.post(
                f"{base_url}/runs/{run_id}/agents/{agent_id}/complete",
                headers=headers,
                timeout=10,
            )
            completed.raise_for_status()
            return

        tool_results = []
        for tool_use in tool_uses:
            response = requests.post(
                f"{base_url}/runs/{run_id}/gateway/execute",
                json={
                    "agent_id": agent_id,
                    "credential": credential,
                    "tool": tool_use["name"],
                    "arguments": tool_use.get("input", {}),
                    "origin": "MODEL",
                    "idempotency_key": tool_use.get("toolUseId"),
                },
                timeout=10,
            )
            if response.status_code == 403:
                agent_state = requests.get(
                    f"{base_url}/runs/{run_id}/agents/{agent_id}", timeout=10
                )
                if agent_state.ok and agent_state.json().get("status") in {"STOPPING", "STOPPED", "FAILED"}:
                    return
            if response.ok:
                content = [{"json": response.json()}]
                status = "success"
            else:
                content = [{"text": response.text[:1000]}]
                status = "error"
            tool_results.append({
                "toolResult": {
                    "toolUseId": tool_use["toolUseId"],
                    "content": content,
                    "status": status,
                }
            })
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError("Agent reached the model-turn limit without completing the task")


if __name__ == "__main__":
    raise SystemExit(main())
