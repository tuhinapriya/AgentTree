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


def test_dashboard_snapshot_includes_hierarchy_and_events(tmp_path):
    app = build_app(str(tmp_path / "stage7-dashboard.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage7-dashboard")
    credential = client.post(
        "/runs/run-stage7-dashboard/gateway/credentials",
        json={"agent_id": "account-agent"},
    ).json()["credential"]

    deny_response = client.post(
        "/runs/run-stage7-dashboard/gateway/execute",
        json={
            "agent_id": "account-agent",
            "credential": credential,
            "tool": "modify_billing",
            "arguments": {"customer_id": "C104", "amount": 25.0},
            "origin": "CONTROLLED_TEST",
        },
    )
    assert deny_response.status_code == 403

    snapshot = client.get("/runs/run-stage7-dashboard/dashboard")
    assert snapshot.status_code == 200
    payload = snapshot.json()
    assert payload["run_id"] == "run-stage7-dashboard"
    assert {item["agent_id"] for item in payload["hierarchy"]["agents"]} == {"parent-agent", "order-agent", "account-agent"}
    assert any(event["decision"] == "DENY" and event["origin"] == "CONTROLLED_TEST" for event in payload["events"])


def test_sse_stream_emits_current_event_snapshot(tmp_path):
    app = build_app(str(tmp_path / "stage7-stream.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage7-stream")
    with client.stream("GET", "/runs/run-stage7-stream/events/stream") as response:
        assert response.status_code == 200
        body = b"".join(response.iter_bytes()).decode()

    assert "event: connected" in body
    assert "event: message" in body or "event: heartbeat" in body
    assert "run-stage7-stream" in body


def test_dashboard_allows_local_frontend_origin(tmp_path):
    app = build_app(str(tmp_path / "stage7-cors.db"))
    client = TestClient(app)

    create_response = client.post("/runs", json={"run_id": "run-stage7-cors", "scenario": "customer-operations"})
    assert create_response.status_code == 200

    response = client.get(
        "/runs/run-stage7-cors/dashboard",
        headers={"Origin": "http://localhost:5174"},
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") in {"http://localhost:5174", "*"}
