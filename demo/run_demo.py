from __future__ import annotations

import time

import requests


DEFAULT_RUN_ID = "agenttree-transactional-demo"
AGENTS = [
    ("parent-agent", "parent", None, []),
    ("order-agent", "order", "parent-agent", ["read_order", "stage_refund"]),
    ("account-agent", "account", "parent-agent", ["read_account", "stage_promo_credit"]),
]


def _post(base_url: str, path: str, payload: dict | None = None):
    response = requests.post(f"{base_url}{path}", json=payload, timeout=10)
    return response


def run_demo_sequence(
    base_url: str = "http://127.0.0.1:8000",
    run_id: str = DEFAULT_RUN_ID,
) -> dict:
    base_url = base_url.rstrip("/")
    run_response = _post(
        base_url,
        "/runs",
        {"run_id": run_id, "scenario": "customer-104-transactional"},
    )
    if run_response.status_code == 409:
        # A repeat run first reaps any old workers, then restores the exact
        # fixture and branch state used by the presentation.
        _post(base_url, f"/runs/{run_id}/cleanup").raise_for_status()
        _post(base_url, f"/runs/{run_id}/demo/reset").raise_for_status()
    else:
        run_response.raise_for_status()

    for agent_id, role, parent_agent_id, allowed_tools in AGENTS:
        response = _post(
            base_url,
            f"/runs/{run_id}/agents",
            {
                "agent_id": agent_id,
                "role": role,
                "parent_agent_id": parent_agent_id,
                "allowed_tools": allowed_tools,
            },
        )
        if response.status_code not in (200, 409):
            response.raise_for_status()

    started = _post(
        base_url,
        f"/runs/{run_id}/supervise",
        {"agent_ids": [agent[0] for agent in AGENTS]},
    )
    started.raise_for_status()
    process_started = True
    try:
        order_credential = _post(
            base_url, f"/runs/{run_id}/gateway/credentials", {"agent_id": "order-agent"}
        ).json()["credential"]
        account_credential = _post(
            base_url, f"/runs/{run_id}/gateway/credentials", {"agent_id": "account-agent"}
        ).json()["credential"]

        order_stage = _post(
            base_url,
            f"/runs/{run_id}/gateway/execute",
            {
                "agent_id": "order-agent",
                "credential": order_credential,
                "tool": "stage_refund",
                "arguments": {"order_id": "ORD-882", "amount_cents": 4500},
                "origin": "CONTROLLED_TEST",
            },
        )
        order_stage.raise_for_status()
        # Hold each visible checkpoint long enough to narrate in a screen recording.
        time.sleep(1.2)
        account_stage = _post(
            base_url,
            f"/runs/{run_id}/gateway/execute",
            {
                "agent_id": "account-agent",
                "credential": account_credential,
                "tool": "stage_promo_credit",
                "arguments": {"customer_id": "C104", "amount_cents": 5000},
                "origin": "CONTROLLED_TEST",
            },
        )
        account_stage.raise_for_status()
        time.sleep(1.2)

        # The scripted probe is intentionally labeled. It demonstrates policy
        # enforcement; it is not presented as a model-generated decision.
        denied = _post(
            base_url,
            f"/runs/{run_id}/gateway/execute",
            {
                "agent_id": "account-agent",
                "credential": account_credential,
                "tool": "modify_billing",
                "arguments": {"customer_id": "C999", "amount": 50},
                "origin": "CONTROLLED_TEST",
            },
        )
        if denied.status_code != 403:
            raise RuntimeError(f"Expected the controlled billing probe to be denied: {denied.status_code} {denied.text}")
        time.sleep(1.5)

        order_after_containment = _post(
            base_url,
            f"/runs/{run_id}/gateway/execute",
            {
                "agent_id": "order-agent",
                "credential": order_credential,
                "tool": "read_order",
                "arguments": {"order_id": "ORD-882"},
                "origin": "CONTROLLED_TEST",
            },
        )
        order_after_containment.raise_for_status()
        time.sleep(1.2)

        # Until real workers are added, completion is an explicit operator
        # checkpoint for this deterministic controlled-test sequence.
        complete = _post(base_url, f"/runs/{run_id}/branches/order-agent/complete")
        complete.raise_for_status()
        time.sleep(1.2)
        commit = _post(base_url, f"/runs/{run_id}/branches/order-agent/commit")
        commit.raise_for_status()

        dashboard = requests.get(f"{base_url}/runs/{run_id}/dashboard", timeout=10)
        dashboard.raise_for_status()
        return {
            "run_id": run_id,
            "origin": "CONTROLLED_TEST",
            "order_staged": order_stage.json(),
            "account_staged": account_stage.json(),
            "account_probe_status": denied.status_code,
            "order_post_containment": order_after_containment.json(),
            "order_commit": commit.json(),
            "dashboard": dashboard.json(),
        }
    except Exception:
        if process_started:
            _post(base_url, f"/runs/{run_id}/cleanup")
        raise


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Run the controlled transactional AgentTree demo")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    args = parser.parse_args()
    print(json.dumps(run_demo_sequence(args.base_url, args.run_id), indent=2))
