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


def test_aws_status_reports_local_fallback_when_sdk_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    app = build_app(str(tmp_path / "stage8-status.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage8-status")
    response = client.get("/runs/run-stage8-status/aws/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "run-stage8-status"
    assert payload["aws_enabled"] is False
    assert payload["mode"] in {"local_fallback", "disabled"}


def test_aws_export_redacts_credentials_and_keeps_local_records(tmp_path):
    app = build_app(str(tmp_path / "stage8-export.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage8-export")
    export_response = client.post(
        "/runs/run-stage8-export/aws/export",
        json={
            "events": [
                {
                    "run_id": "run-stage8-export",
                    "agent_id": "account-agent",
                    "tool": "modify_billing",
                    "decision": "DENY",
                    "reason_code": "TOOL_NOT_DELEGATED",
                    "origin": "CONTROLLED_TEST",
                    "credential": "supersecret-token",
                }
            ]
        },
    )

    assert export_response.status_code == 200
    payload = export_response.json()
    assert payload["record_count"] == 1
    assert "supersecret-token" not in str(payload)

    fetch_response = client.get("/runs/run-stage8-export/aws/events")
    assert fetch_response.status_code == 200
    assert fetch_response.json()["records"][0]["agent_id"] == "account-agent"
