#!/usr/bin/env python3

import argparse
import json
import sys
import urllib.request


def call_json(method: str, url: str, payload=None):
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def main():
    parser = argparse.ArgumentParser(description="AgentTree CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Launch a run")
    run_parser.add_argument("run_id")
    run_parser.add_argument("--scenario", default="customer-operations")
    run_parser.add_argument("--agents", default="parent-agent,order-agent,account-agent")
    run_parser.add_argument("--base-url", default="http://127.0.0.1:8000")

    args = parser.parse_args()

    if args.command == "run":
        run_id = args.run_id
        base_url = args.base_url.rstrip("/")
        run_payload = call_json("POST", f"{base_url}/runs", {"run_id": run_id, "scenario": args.scenario})
        agent_ids = [item.strip() for item in args.agents.split(",") if item.strip()]
        launch_payload = call_json(
            "POST",
            f"{base_url}/runs/{run_id}/supervise",
            {"agent_ids": agent_ids},
        )
        print(json.dumps({"run": run_payload, "launch": launch_payload}, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
