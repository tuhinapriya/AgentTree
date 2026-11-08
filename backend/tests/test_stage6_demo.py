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


def test_demo_fixtures_match_required_customer_and_order_state(tmp_path):
    app = build_app(str(tmp_path / "stage6-initial.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage6-initial")
    reset_response = client.post("/runs/run-stage6-initial/demo/reset")
    assert reset_response.status_code == 200

    state = client.get("/runs/run-stage6-initial/demo/state")
    assert state.status_code == 200
    payload = state.json()

    assert payload["customer"]["customer_id"] == "C104"
    assert payload["customer"]["plan"] == "basic"
    assert payload["order"]["order_id"] == "ORD-104"
    assert payload["order"]["status"] == "PENDING"
    assert payload["order"]["fulfillment_confirmed"] is False
    assert payload["account"]["balance"] == 100.0


def test_demo_reset_restores_initial_business_state_after_mutation(tmp_path):
    app = build_app(str(tmp_path / "stage6-reset.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage6-reset")
    client.post("/runs/run-stage6-reset/demo/reset")

    order_credential = client.post(
        "/runs/run-stage6-reset/gateway/credentials",
        json={"agent_id": "order-agent"},
    ).json()["credential"]
    account_credential = client.post(
        "/runs/run-stage6-reset/gateway/credentials",
        json={"agent_id": "account-agent"},
    ).json()["credential"]

    order_process = client.post(
        "/runs/run-stage6-reset/gateway/execute",
        json={
            "agent_id": "order-agent",
            "credential": order_credential,
            "tool": "process_order",
            "arguments": {"order_id": "ORD-104"},
        },
    )
    assert order_process.status_code == 200

    blocked = client.post(
        "/runs/run-stage6-reset/gateway/execute",
        json={
            "agent_id": "account-agent",
            "credential": account_credential,
            "tool": "modify_billing",
            "arguments": {"customer_id": "C104", "amount": 25.0},
        },
    )
    assert blocked.status_code == 403

    reset = client.post("/runs/run-stage6-reset/demo/reset")
    assert reset.status_code == 200

    state = client.get("/runs/run-stage6-reset/demo/state")
    payload = state.json()
    assert payload["order"]["status"] == "PENDING"
    assert payload["order"]["fulfillment_confirmed"] is False
    assert payload["account"]["balance"] == 100.0
