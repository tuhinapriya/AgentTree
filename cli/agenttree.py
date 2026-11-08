#!/usr/bin/env python3
"""Presenter-friendly CLI for AgentTree's local control plane."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_AGENTS = [
    ("parent-agent", "parent", None, []),
    ("order-agent", "order", "parent-agent", ["read_order", "stage_refund", "read_orders", "process_order"]),
    ("account-agent", "account", "parent-agent", ["read_account", "stage_promo_credit"]),
]


def call_json(method: str, url: str, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach AgentTree at {url}: {exc.reason}") from exc


def print_json(value):
    print(json.dumps(value, indent=2, sort_keys=True))


def _base(value: str) -> str:
    return value.rstrip("/")


def run_command(args):
    base_url = _base(args.base_url)
    run_id = args.run_id
    created = call_json("POST", f"{base_url}/runs", {"run_id": run_id, "scenario": args.scenario})
    for agent_id, role, parent_id, tools in DEFAULT_AGENTS:
        call_json(
            "POST",
            f"{base_url}/runs/{run_id}/agents",
            {"agent_id": agent_id, "role": role, "parent_agent_id": parent_id, "allowed_tools": tools},
        )

    tasks = {}
    for assignment in args.task:
        agent_id, separator, task = assignment.partition("=")
        if not separator or not agent_id or not task.strip():
            raise RuntimeError(f"Invalid --task {assignment!r}; expected agent-id=task text")
        tasks[agent_id] = task.strip()
    launch = call_json(
        "POST",
        f"{base_url}/runs/{run_id}/supervise",
        {"agent_ids": args.agents.split(","), "tasks": tasks},
    )
    print_json({"run": created, "launch": launch, "model_tasks": sorted(tasks)})


def status_command(args):
    base_url = _base(args.base_url)
    payload = call_json("GET", f"{base_url}/runs/{args.run_id}/dashboard")
    hierarchy = payload.get("hierarchy", {}).get("agents", [])
    print_json({
        "run_id": args.run_id,
        "agents": [
            {key: agent.get(key) for key in ("agent_id", "role", "status", "task_state", "pid", "exit_code")}
            for agent in hierarchy
        ],
        "effects": payload.get("effects"),
        "business_state": payload.get("business_state"),
        "latest_event_seq": max((event.get("event_seq", 0) for event in payload.get("events", [])), default=0),
    })


def events_command(args):
    base_url = _base(args.base_url)
    query = urllib.parse.urlencode({"after_seq": args.after_seq})
    print_json(call_json("GET", f"{base_url}/runs/{args.run_id}/events?{query}"))


def stop_command(args):
    base_url = _base(args.base_url)
    if args.branch:
        result = call_json("POST", f"{base_url}/runs/{args.run_id}/branches/{args.branch}/stop")
    else:
        result = call_json("POST", f"{base_url}/runs/{args.run_id}/cleanup")
    print_json(result)


def reset_command(args):
    base_url = _base(args.base_url)
    cleanup = call_json("POST", f"{base_url}/runs/{args.run_id}/cleanup")
    reset = call_json("POST", f"{base_url}/runs/{args.run_id}/demo/reset")
    print_json({"cleanup": cleanup, "reset": reset})


def demo_command(args):
    from demo.run_demo import run_demo_sequence

    print_json(run_demo_sequence(_base(args.base_url), args.run_id))


def build_parser():
    parser = argparse.ArgumentParser(prog="agenttree", description="Manage a local AgentTree demo run")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Create a standard hierarchy and launch managed workers")
    run.add_argument("run_id")
    run.add_argument("--scenario", default="customer-operations")
    run.add_argument("--agents", default="parent-agent,order-agent,account-agent")
    run.add_argument("--task", action="append", default=[], metavar="AGENT=TEXT",
                     help="Assign a Bedrock task to an order/account worker; repeatable")
    run.add_argument("--base-url", default=DEFAULT_BASE_URL)
    run.set_defaults(handler=run_command)

    status = subparsers.add_parser("status", help="Show agents, effects, and committed business state")
    status.add_argument("run_id")
    status.add_argument("--base-url", default=DEFAULT_BASE_URL)
    status.set_defaults(handler=status_command)

    events = subparsers.add_parser("events", help="Read ordered audit events")
    events.add_argument("run_id")
    events.add_argument("--after-seq", type=int, default=0)
    events.add_argument("--base-url", default=DEFAULT_BASE_URL)
    events.set_defaults(handler=events_command)

    stop = subparsers.add_parser("stop", help="Stop one branch or clean up every worker in a run")
    stop.add_argument("run_id")
    stop.add_argument("--branch", help="Branch root agent ID; omit to stop the full run")
    stop.add_argument("--base-url", default=DEFAULT_BASE_URL)
    stop.set_defaults(handler=stop_command)

    reset = subparsers.add_parser("reset", help="Stop workers and restore the demo fixture")
    reset.add_argument("run_id")
    reset.add_argument("--base-url", default=DEFAULT_BASE_URL)
    reset.set_defaults(handler=reset_command)

    demo = subparsers.add_parser("demo", help="Run the deterministic staged/abort/commit presentation")
    demo.add_argument("--run-id", default="agenttree-transactional-demo")
    demo.add_argument("--base-url", default=DEFAULT_BASE_URL)
    demo.set_defaults(handler=demo_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        args.handler(args)
    except RuntimeError as exc:
        print(f"agenttree: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
