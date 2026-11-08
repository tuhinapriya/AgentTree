from __future__ import annotations

from unittest.mock import Mock, patch

from demo.reset_demo import reset_demo
from demo.run_demo import run_demo_sequence


@patch("demo.reset_demo.requests.post")
def test_reset_demo_calls_backend_reset(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"run_id": "demo-run", "status": "reset"}

    result = reset_demo("http://127.0.0.1:8000", "demo-run")

    assert result["run_id"] == "demo-run"
    assert result["status"] == "reset"
    mock_post.assert_called_once_with(
        "http://127.0.0.1:8000/runs/demo-run/demo/reset",
        timeout=10,
    )


@patch("demo.run_demo.requests.post")
@patch("demo.run_demo.requests.get")
def test_run_demo_sequence_uses_backend_api_for_run_and_state(mock_get, mock_post):
    mock_post.side_effect = [
        Mock(status_code=200, json=lambda: {"run_id": "demo-run", "scenario": "customer-operations"}),
        Mock(status_code=200, json=lambda: {"agent_id": "parent-agent"}),
        Mock(status_code=200, json=lambda: {"agent_id": "order-agent"}),
        Mock(status_code=200, json=lambda: {"agent_id": "account-agent"}),
        Mock(status_code=200, json=lambda: {"started": [{"agent_id": "parent-agent", "pid": 1001, "status": "RUNNING"}]}),
    ]
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "run_id": "demo-run",
        "customer": {"customer_id": "C104", "plan": "basic"},
        "order": {"order_id": "ORD-104", "status": "PENDING", "fulfillment_confirmed": False},
        "account": {"customer_id": "C104", "balance": 100.0},
    }

    result = run_demo_sequence("http://127.0.0.1:8000", "demo-run")

    assert result["run_id"] == "demo-run"
    assert result["customer"]["customer_id"] == "C104"
    assert result["order"]["order_id"] == "ORD-104"
