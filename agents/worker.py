"""Minimal identity-aware worker runtime managed by AgentTree's supervisor."""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading
from datetime import datetime, timezone


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

    while not stopping.wait(1):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
