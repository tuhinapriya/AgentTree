import os
import signal

from fastapi.testclient import TestClient

from backend.app.main import build_app


def _create_run(client, run_id):
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


def test_supervisor_launches_run_and_children(tmp_path):
    app = build_app(str(tmp_path / "stage2-launch.db"))
    client = TestClient(app)

    _create_run(client, "run-stage2-launch")

    launch_response = client.post(
        "/runs/run-stage2-launch/supervise",
        json={"agent_ids": ["parent-agent", "order-agent", "account-agent"]},
    )
    assert launch_response.status_code == 200
    payload = launch_response.json()

    assert {item["agent_id"] for item in payload["started"]} == {"parent-agent", "order-agent", "account-agent"}
    assert all(item["pid"] is not None for item in payload["started"])
    assert all(item["status"] == "RUNNING" for item in payload["started"])
    assert all(item["worker_ready"]["type"] == "WORKER_READY" for item in payload["started"])
    assert {item["role"] for item in payload["started"]} == {"parent", "order", "account"}

    for item in payload["started"]:
        os.kill(item["pid"], 0)


def test_child_termination_does_not_stop_sibling(tmp_path):
    app = build_app(str(tmp_path / "stage2-terminate.db"))
    client = TestClient(app)

    _create_run(client, "run-stage2-stop")
    launch_response = client.post(
        "/runs/run-stage2-stop/supervise",
        json={"agent_ids": ["parent-agent", "order-agent", "account-agent"]},
    )
    assert launch_response.status_code == 200

    stop_response = client.post("/runs/run-stage2-stop/agents/account-agent/stop")
    assert stop_response.status_code == 200
    stopped_payload = stop_response.json()
    assert stopped_payload["status"] == "STOPPED"
    stopped_agent = client.get("/runs/run-stage2-stop/agents/account-agent").json()
    assert stopped_agent["exit_code"] == 0
    assert stopped_agent["process_create_time"] is not None

    order_status_response = client.get("/runs/run-stage2-stop/agents/order-agent")
    assert order_status_response.status_code == 200
    order_status_payload = order_status_response.json()
    assert order_status_payload["status"] == "RUNNING"


def test_unexpected_exit_is_marked_failed(tmp_path):
    app = build_app(str(tmp_path / "stage2-failed.db"))
    client = TestClient(app)

    _create_run(client, "run-stage2-failed")
    launch_response = client.post(
        "/runs/run-stage2-failed/supervise",
        json={"agent_ids": ["account-agent"]},
    )
    assert launch_response.status_code == 200
    pid = launch_response.json()["started"][0]["pid"]

    os.kill(pid, signal.SIGKILL)

    monitor_response = client.post("/runs/run-stage2-failed/monitor")
    assert monitor_response.status_code == 200
    failed_payload = monitor_response.json()
    assert any(item["agent_id"] == "account-agent" and item["status"] == "FAILED" for item in failed_payload["agents"])


def test_cleanup_removes_orphans(tmp_path):
    app = build_app(str(tmp_path / "stage2-cleanup.db"))
    client = TestClient(app)

    _create_run(client, "run-stage2-cleanup")
    launch_response = client.post(
        "/runs/run-stage2-cleanup/supervise",
        json={"agent_ids": ["account-agent"]},
    )
    assert launch_response.status_code == 200
    pid = launch_response.json()["started"][0]["pid"]

    cleanup_response = client.post("/runs/run-stage2-cleanup/cleanup")
    assert cleanup_response.status_code == 200

    try:
        os.kill(pid, 0)
        raise AssertionError("Process should not still exist after cleanup")
    except ProcessLookupError:
        pass
