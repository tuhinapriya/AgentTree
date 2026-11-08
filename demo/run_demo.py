from __future__ import annotations

import requests


def run_demo_sequence(base_url: str = "http://127.0.0.1:8000", run_id: str = "demo-run") -> dict:
    run_response = requests.post(
        f"{base_url}/runs",
        json={"run_id": run_id, "scenario": "customer-operations"},
        timeout=10,
    )
    if run_response.status_code == 409:
        requests.post(f"{base_url}/runs/{run_id}/demo/reset", timeout=10)
    else:
        run_response.raise_for_status()

    for agent_id, role, parent_agent_id, allowed_tools in [
        ("parent-agent", "parent", None, ["read_orders", "process_order", "read_account", "modify_billing"]),
        ("order-agent", "order", "parent-agent", ["read_orders", "process_order"]),
        ("account-agent", "account", "parent-agent", ["read_account"]),
    ]:
        agent_response = requests.post(
            f"{base_url}/runs/{run_id}/agents",
            json={
                "agent_id": agent_id,
                "role": role,
                "parent_agent_id": parent_agent_id,
                "allowed_tools": allowed_tools,
            },
            timeout=10,
        )
        if agent_response.status_code not in (200, 409):
            agent_response.raise_for_status()

    launch_response = requests.post(
        f"{base_url}/runs/{run_id}/supervise",
        json={"agent_ids": ["parent-agent", "order-agent", "account-agent"]},
        timeout=10,
    )
    launch_response.raise_for_status()

    credential_response = requests.post(
        f"{base_url}/runs/{run_id}/gateway/credentials",
        json={"agent_id": "account-agent"},
        timeout=10,
    )
    credential_response.raise_for_status()
    account_credential = credential_response.json()["credential"]

    allowed = requests.post(
        f"{base_url}/runs/{run_id}/gateway/execute",
        json={
            "agent_id": "account-agent",
            "credential": account_credential,
            "tool": "read_account",
            "arguments": {"customer_id": "C104"},
        },
        timeout=10,
    )
    allowed.raise_for_status()

    denied = requests.post(
        f"{base_url}/runs/{run_id}/gateway/execute",
        json={
            "agent_id": "account-agent",
            "credential": account_credential,
            "tool": "modify_billing",
            "arguments": {"customer_id": "C104", "amount": 25.0},
        },
        timeout=10,
    )
    if denied.status_code != 403:
        raise RuntimeError(f"Expected denied billing call, got {denied.status_code}: {denied.text}")

    stop_response = requests.post(
        f"{base_url}/runs/{run_id}/branches/account-agent/stop",
        timeout=10,
    )
    stop_response.raise_for_status()

    dashboard_response = requests.get(f"{base_url}/runs/{run_id}/dashboard", timeout=10)
    dashboard_response.raise_for_status()
    return dashboard_response.json()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create and launch the demo run")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--run-id", default="demo-run")
    args = parser.parse_args()
    print(run_demo_sequence(args.base_url, args.run_id))
