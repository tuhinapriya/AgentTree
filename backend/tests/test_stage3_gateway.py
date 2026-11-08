from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import build_app


def _create_run_and_agents(client: TestClient, run_id: str):
    run_response = client.post("/runs", json={"run_id": run_id, "scenario": "customer-operations"})
    assert run_response.status_code == 200

    for agent_id, role, parent_agent_id, allowed_tools in [
        ("parent-agent", "parent", None, ["read_orders", "process_order", "read_account", "modify_billing"]),
        ("order-agent", "order", "parent-agent", ["read_orders", "process_order"]),
        ("account-agent", "account", "parent-agent", ["read_account"]),
    ]:
        agent_response = client.post(
            f"/runs/{run_id}/agents",
            json={
                "agent_id": agent_id,
                "role": role,
                "parent_agent_id": parent_agent_id,
                "allowed_tools": allowed_tools,
            },
        )
        assert agent_response.status_code == 200


def _issue_credential(client: TestClient, run_id: str, agent_id: str):
    response = client.post(f"/runs/{run_id}/gateway/credentials", json={"agent_id": agent_id})
    assert response.status_code == 200
    return response.json()


def _execute_tool(client: TestClient, run_id: str, agent_id: str, credential: str, tool_name: str, arguments: dict):
    return client.post(
        f"/runs/{run_id}/gateway/execute",
        json={
            "agent_id": agent_id,
            "credential": credential,
            "tool": tool_name,
            "arguments": arguments,
        },
    )


def test_order_agent_can_read_orders_and_process_when_preconditions_are_met(tmp_path):
    app = build_app(str(tmp_path / "stage3-order.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage3-order")
    credential = _issue_credential(client, "run-stage3-order", "order-agent")["credential"]

    read_response = _execute_tool(
        client,
        "run-stage3-order",
        "order-agent",
        credential,
        "read_orders",
        {"order_id": "ORD-104"},
    )
    assert read_response.status_code == 200
    assert read_response.json()["result"]["order_id"] == "ORD-104"

    process_response = _execute_tool(
        client,
        "run-stage3-order",
        "order-agent",
        credential,
        "process_order",
        {"order_id": "ORD-104"},
    )
    assert process_response.status_code == 200
    assert process_response.json()["result"]["status"] == "PROCESSED"


def test_account_agent_can_read_account_but_cannot_modify_billing(tmp_path):
    app = build_app(str(tmp_path / "stage3-account.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage3-account")
    credential = _issue_credential(client, "run-stage3-account", "account-agent")["credential"]

    read_response = _execute_tool(
        client,
        "run-stage3-account",
        "account-agent",
        credential,
        "read_account",
        {"customer_id": "C104"},
    )
    assert read_response.status_code == 200
    assert read_response.json()["result"]["customer_id"] == "C104"

    modify_response = _execute_tool(
        client,
        "run-stage3-account",
        "account-agent",
        credential,
        "modify_billing",
        {"customer_id": "C104", "amount": 25.0},
    )
    assert modify_response.status_code == 403
    assert modify_response.json()["detail"] == "Permission denied"

    follow_up = _execute_tool(
        client,
        "run-stage3-account",
        "account-agent",
        credential,
        "read_account",
        {"customer_id": "C104"},
    )
    assert follow_up.status_code == 200
    assert follow_up.json()["result"]["balance"] == 100.0


def test_missing_invalid_and_unknown_requests_are_rejected(tmp_path):
    app = build_app(str(tmp_path / "stage3-reject.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage3-reject")
    credential = _issue_credential(client, "run-stage3-reject", "order-agent")["credential"]

    missing_credential = client.post(
        f"/runs/run-stage3-reject/gateway/execute",
        json={
            "agent_id": "order-agent",
            "tool": "read_orders",
            "arguments": {"order_id": "ORD-104"},
        },
    )
    assert missing_credential.status_code == 401

    invalid_credential = _execute_tool(
        client,
        "run-stage3-reject",
        "order-agent",
        "bad-token",
        "read_orders",
        {"order_id": "ORD-104"},
    )
    assert invalid_credential.status_code == 401

    unknown_tool = _execute_tool(
        client,
        "run-stage3-reject",
        "order-agent",
        credential,
        "read_unknown",
        {"order_id": "ORD-104"},
    )
    assert unknown_tool.status_code == 404


def test_spoofed_agent_identity_cannot_escalate_permissions(tmp_path):
    app = build_app(str(tmp_path / "stage3-spoof.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage3-spoof")
    account_credential = _issue_credential(client, "run-stage3-spoof", "account-agent")["credential"]

    spoofed = _execute_tool(
        client,
        "run-stage3-spoof",
        "order-agent",
        account_credential,
        "read_account",
        {"customer_id": "C104"},
    )
    assert spoofed.status_code == 403
    assert spoofed.json()["detail"] == "Permission denied"
