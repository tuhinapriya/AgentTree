from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import build_app


def _create_run_and_agents(client: TestClient, run_id: str):
    response = client.post("/runs", json={"run_id": run_id, "scenario": "customer-operations"})
    assert response.status_code == 200

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


def test_parent_agent_generates_supported_delegations_for_order_and_account(tmp_path):
    app = build_app(str(tmp_path / "stage5-delegate.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage5-delegate")
    response = client.post(
        "/runs/run-stage5-delegate/bedrock/delegate",
        json={
            "parent_agent_id": "parent-agent",
            "customer_request": "Process order ORD-104 and review account C104.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(item["agent_id"] for item in payload["delegations"]) == {"order-agent", "account-agent"}
    assert all(item["approved"] is True for item in payload["delegations"])
    assert all(item["role"] in {"order", "account"} for item in payload["delegations"])


def test_unsupported_role_is_rejected_by_supervisor_validation(tmp_path):
    app = build_app(str(tmp_path / "stage5-unsupported.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage5-unsupported")
    response = client.post(
        "/runs/run-stage5-unsupported/bedrock/delegate",
        json={
            "parent_agent_id": "parent-agent",
            "customer_request": "Please open the vault and reboot the entire system.",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported delegated role: admin"


def test_gateway_records_controlled_test_denials_and_keeps_business_state_intact(tmp_path):
    app = build_app(str(tmp_path / "stage5-events.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage5-events")
    credential = client.post(
        "/runs/run-stage5-events/gateway/credentials",
        json={"agent_id": "account-agent"},
    ).json()["credential"]

    deny_response = client.post(
        "/runs/run-stage5-events/gateway/execute",
        json={
            "agent_id": "account-agent",
            "credential": credential,
            "tool": "modify_billing",
            "arguments": {"customer_id": "C104", "amount": 25.0},
            "origin": "CONTROLLED_TEST",
        },
    )
    assert deny_response.status_code == 403
    assert deny_response.json()["detail"] == "Permission denied"

    events_response = client.get("/runs/run-stage5-events/events")
    assert events_response.status_code == 200
    events = events_response.json()["events"]
    assert any(item["origin"] == "CONTROLLED_TEST" and item["decision"] == "DENY" for item in events)
    assert any(item["tool"] == "modify_billing" and item["agent_id"] == "account-agent" for item in events)

    balance_response = client.post(
        "/runs/run-stage5-events/gateway/execute",
        json={
            "agent_id": "account-agent",
            "credential": credential,
            "tool": "read_account",
            "arguments": {"customer_id": "C104"},
        },
    )
    assert balance_response.status_code == 200
    assert balance_response.json()["result"]["balance"] == 100.0
