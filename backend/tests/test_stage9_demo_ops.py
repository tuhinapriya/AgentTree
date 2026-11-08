from __future__ import annotations

from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.app.db import AgentTreeDB
from backend.app.main import build_app
from demo.reset_demo import reset_demo
from demo.run_demo import run_demo_sequence


@patch("demo.reset_demo.requests.post")
def test_reset_demo_cleans_workers_before_reset(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"run_id": "demo-run", "status": "reset"}

    result = reset_demo("http://127.0.0.1:8000", "demo-run")

    assert result["run_id"] == "demo-run"
    assert result["status"] == "reset"
    assert mock_post.call_args_list[0].args == ("http://127.0.0.1:8000/runs/demo-run/cleanup",)
    assert mock_post.call_args_list[1].args == ("http://127.0.0.1:8000/runs/demo-run/demo/reset",)


@patch("demo.run_demo.requests.post")
@patch("demo.run_demo.requests.get")
def test_run_demo_sequence_stages_contains_and_commits(mock_get, mock_post):
    mock_post.side_effect = [
        Mock(status_code=200, json=lambda: {"run_id": "demo-run", "scenario": "customer-104-transactional"}),
        Mock(status_code=200, json=lambda: {"agent_id": "parent-agent"}),
        Mock(status_code=200, json=lambda: {"agent_id": "order-agent"}),
        Mock(status_code=200, json=lambda: {"agent_id": "account-agent"}),
        Mock(status_code=200, json=lambda: {"started": []}),
        Mock(status_code=200, json=lambda: {"credential": "order-token"}),
        Mock(status_code=200, json=lambda: {"credential": "account-token"}),
        Mock(status_code=200, json=lambda: {"result": {"status": "STAGED"}}),
        Mock(status_code=200, json=lambda: {"result": {"status": "STAGED"}}),
        Mock(status_code=403, text="Permission denied"),
        Mock(status_code=200, json=lambda: {"result": {"refunded_cents": 0}}),
        Mock(status_code=200, json=lambda: {"state": "READY_TO_COMMIT"}),
        Mock(status_code=200, json=lambda: {"state": "COMMITTED"}),
    ]
    mock_get.return_value = Mock(status_code=200, json=lambda: {"run_id": "demo-run"})

    result = run_demo_sequence("http://127.0.0.1:8000", "demo-run")

    assert result["run_id"] == "demo-run"
    assert result["origin"] == "CONTROLLED_TEST"
    assert result["account_probe_status"] == 403
    assert result["order_commit"]["state"] == "COMMITTED"
    assert mock_post.call_args_list[-2].args == (
        "http://127.0.0.1:8000/runs/demo-run/branches/order-agent/complete",
    )
    assert mock_post.call_args_list[-1].args == (
        "http://127.0.0.1:8000/runs/demo-run/branches/order-agent/commit",
    )


def test_transactional_demo_vertical_slice_over_api(tmp_path):
    database_path = str(tmp_path / "demo-vertical-slice.db")
    client = TestClient(build_app(database_path))
    run_id = "demo-vertical-slice"
    assert client.post("/runs", json={"run_id": run_id, "scenario": "customer-104-transactional"}).status_code == 200
    for agent_id, role, parent_id, tools in [
        ("parent-agent", "parent", None, []),
        ("order-agent", "order", "parent-agent", ["read_order", "stage_refund"]),
        ("account-agent", "account", "parent-agent", ["read_account", "stage_promo_credit"]),
    ]:
        assert client.post(
            f"/runs/{run_id}/agents",
            json={"agent_id": agent_id, "role": role, "parent_agent_id": parent_id, "allowed_tools": tools},
        ).status_code == 200
    assert client.post(
        f"/runs/{run_id}/supervise",
        json={"agent_ids": ["parent-agent", "order-agent", "account-agent"]},
    ).status_code == 200
    order_token = client.post(
        f"/runs/{run_id}/gateway/credentials", json={"agent_id": "order-agent"}
    ).json()["credential"]
    account_token = client.post(
        f"/runs/{run_id}/gateway/credentials", json={"agent_id": "account-agent"}
    ).json()["credential"]

    for agent_id, token, tool, arguments in [
        ("order-agent", order_token, "stage_refund", {"order_id": "ORD-882", "amount_cents": 4500}),
        ("account-agent", account_token, "stage_promo_credit", {"customer_id": "C104", "amount_cents": 5000}),
    ]:
        response = client.post(
            f"/runs/{run_id}/gateway/execute",
            json={"agent_id": agent_id, "credential": token, "tool": tool,
                  "arguments": arguments, "origin": "CONTROLLED_TEST"},
        )
        assert response.status_code == 200
        assert response.json()["result"]["committed"] is False

    denied = client.post(
        f"/runs/{run_id}/gateway/execute",
        json={"agent_id": "account-agent", "credential": account_token,
              "tool": "modify_billing", "arguments": {"customer_id": "C999", "amount": 50},
              "origin": "CONTROLLED_TEST"},
    )
    assert denied.status_code == 403
    assert client.get(f"/runs/{run_id}/agents/account-agent").json()["status"] == "STOPPED"
    assert client.get(f"/runs/{run_id}/agents/order-agent").json()["status"] == "RUNNING"

    continued = client.post(
        f"/runs/{run_id}/gateway/execute",
        json={"agent_id": "order-agent", "credential": order_token, "tool": "read_order",
              "arguments": {"order_id": "ORD-882"}, "origin": "CONTROLLED_TEST"},
    )
    assert continued.status_code == 200
    assert continued.json()["result"]["refunded_cents"] == 0
    assert client.post(f"/runs/{run_id}/branches/order-agent/complete").status_code == 200
    commit = client.post(f"/runs/{run_id}/branches/order-agent/commit")
    assert commit.status_code == 200
    assert commit.json()["state"] == "COMMITTED"

    with AgentTreeDB(database_path)._connect() as connection:
        assert connection.execute(
            "SELECT refunded_cents FROM business_orders WHERE run_id = ? AND order_id = 'ORD-882'",
            (run_id,),
        ).fetchone()[0] == 4500
        assert connection.execute(
            "SELECT promo_credit_cents FROM business_accounts WHERE run_id = ? AND customer_id = 'C104'",
            (run_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT state FROM journal WHERE run_id = ? AND branch_id = 'account-agent'",
            (run_id,),
        ).fetchone()[0] == "ABORTED"
    client.post(f"/runs/{run_id}/cleanup")
