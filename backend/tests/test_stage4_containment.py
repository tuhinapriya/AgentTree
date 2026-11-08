import os

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


def _issue_credential(client: TestClient, run_id: str, agent_id: str):
    response = client.post(f"/runs/{run_id}/gateway/credentials", json={"agent_id": agent_id})
    assert response.status_code == 200
    return response.json()["credential"]


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


def test_branch_stop_revokes_credentials_and_stops_selected_branch(tmp_path):
    app = build_app(str(tmp_path / "stage4-account.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage4-account")
    account_credential = _issue_credential(client, "run-stage4-account", "account-agent")

    launch_response = client.post(
        "/runs/run-stage4-account/supervise",
        json={"agent_ids": ["parent-agent", "order-agent", "account-agent"]},
    )
    assert launch_response.status_code == 200

    stop_response = client.post("/runs/run-stage4-account/branches/account-agent/stop")
    assert stop_response.status_code == 200
    stopped_payload = stop_response.json()
    assert stopped_payload["branch_id"] == "account-agent"
    assert stopped_payload["status"] == "STOPPED"

    denied = _execute_tool(
        client,
        "run-stage4-account",
        "account-agent",
        account_credential,
        "read_account",
        {"customer_id": "C104"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Permission denied"

    agent_status = client.get("/runs/run-stage4-account/agents/account-agent")
    assert agent_status.status_code == 200
    assert agent_status.json()["status"] == "STOPPED"


def test_branch_stop_only_affects_selected_branch(tmp_path):
    app = build_app(str(tmp_path / "stage4-scope.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage4-scope")
    order_credential = _issue_credential(client, "run-stage4-scope", "order-agent")

    launch_response = client.post(
        "/runs/run-stage4-scope/supervise",
        json={"agent_ids": ["parent-agent", "order-agent", "account-agent"]},
    )
    assert launch_response.status_code == 200

    stop_response = client.post("/runs/run-stage4-scope/branches/account-agent/stop")
    assert stop_response.status_code == 200

    order_status = client.get("/runs/run-stage4-scope/agents/order-agent")
    assert order_status.status_code == 200
    assert order_status.json()["status"] == "RUNNING"

    parent_status = client.get("/runs/run-stage4-scope/agents/parent-agent")
    assert parent_status.status_code == 200
    assert parent_status.json()["status"] == "RUNNING"

    allowed = _execute_tool(
        client,
        "run-stage4-scope",
        "order-agent",
        order_credential,
        "read_orders",
        {"order_id": "ORD-104"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["result"]["order_id"] == "ORD-104"


def test_branch_stop_requests_are_idempotent(tmp_path):
    app = build_app(str(tmp_path / "stage4-idempotent.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage4-idempotent")
    launch_response = client.post(
        "/runs/run-stage4-idempotent/supervise",
        json={"agent_ids": ["account-agent"]},
    )
    assert launch_response.status_code == 200

    first = client.post("/runs/run-stage4-idempotent/branches/account-agent/stop")
    assert first.status_code == 200
    second = client.post("/runs/run-stage4-idempotent/branches/account-agent/stop")
    assert second.status_code == 200
    assert second.json()["status"] == "STOPPED"

def test_branch_stop_releases_managed_processes_cleanly(tmp_path):
    app = build_app(str(tmp_path / "stage4-cleanup.db"))
    client = TestClient(app)

    _create_run_and_agents(client, "run-stage4-cleanup")
    launch_response = client.post(
        "/runs/run-stage4-cleanup/supervise",
        json={"agent_ids": ["account-agent"]},
    )
    assert launch_response.status_code == 200
    pid = launch_response.json()["started"][0]["pid"]

    stop_response = client.post("/runs/run-stage4-cleanup/branches/account-agent/stop")
    assert stop_response.status_code == 200

    try:
        os.kill(pid, 0)
        raise AssertionError("Process should not still exist after branch stop")
    except ProcessLookupError:
        pass
