from fastapi.testclient import TestClient

from backend.app.db import AgentTreeDB
from backend.app.main import build_app


def _create_agents(client, run_id):
    assert client.post(f"/runs", json={"run_id": run_id}).status_code == 200
    for agent_id, role, parent_id, tools in [
        ("parent-agent", "parent", None, []),
        ("order-agent", "order", "parent-agent", ["read_orders", "process_order"]),
        ("account-agent", "account", "parent-agent", ["read_account"]),
    ]:
        response = client.post(
            f"/runs/{run_id}/agents",
            json={"agent_id": agent_id, "role": role, "parent_agent_id": parent_id, "allowed_tools": tools},
        )
        assert response.status_code == 200


def test_gateway_session_is_hashed_persistent_and_bound_to_agent(tmp_path):
    database_path = str(tmp_path / "sessions.db")
    app = build_app(database_path)
    client = TestClient(app)
    run_id = "session-run"
    _create_agents(client, run_id)
    credential = client.post(
        f"/runs/{run_id}/gateway/credentials", json={"agent_id": "account-agent"}
    ).json()["credential"]

    with AgentTreeDB(database_path)._connect() as connection:
        token_hash, owner, branch_id = connection.execute(
            "SELECT token_hash, agent_id, branch_id FROM agent_sessions WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    assert token_hash != credential
    assert owner == "account-agent"
    assert branch_id == "account-agent"

    # A fresh app instance can validate the opaque capability from SQLite.
    restarted = TestClient(build_app(database_path))
    allowed = restarted.post(
        f"/runs/{run_id}/gateway/execute",
        json={"agent_id": "account-agent", "credential": credential,
              "tool": "read_account", "arguments": {"customer_id": "C104"}},
    )
    assert allowed.status_code == 200

    spoofed = restarted.post(
        f"/runs/{run_id}/gateway/execute",
        json={"agent_id": "order-agent", "credential": credential,
              "tool": "read_orders", "arguments": {"order_id": "ORD-104"}},
    )
    assert spoofed.status_code == 403


def test_revoked_session_and_non_running_branch_are_denied(tmp_path):
    app = build_app(str(tmp_path / "revoked.db"))
    client = TestClient(app)
    run_id = "revoked-run"
    _create_agents(client, run_id)
    credential = client.post(
        f"/runs/{run_id}/gateway/credentials", json={"agent_id": "account-agent"}
    ).json()["credential"]

    stopped = client.post(f"/runs/{run_id}/branches/account-agent/stop")
    assert stopped.status_code == 200
    denied = client.post(
        f"/runs/{run_id}/gateway/execute",
        json={"agent_id": "account-agent", "credential": credential,
              "tool": "read_account", "arguments": {"customer_id": "C104"}},
    )
    assert denied.status_code == 403

    with AgentTreeDB(str(tmp_path / "revoked.db"))._connect() as connection:
        revoked_at = connection.execute(
            "SELECT revoked_at FROM agent_sessions WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    assert revoked_at is not None


def test_policy_violation_aborts_pending_effect_and_stops_only_target_branch(tmp_path):
    database_path = str(tmp_path / "policy.db")
    app = build_app(database_path)
    client = TestClient(app)
    run_id = "policy-run"
    assert client.post("/runs", json={"run_id": run_id}).status_code == 200
    for agent_id, role, parent_id, tools in [
        ("parent-agent", "parent", None, []),
        ("order-agent", "order", "parent-agent", ["stage_refund", "read_order"]),
        ("account-agent", "account", "parent-agent", ["read_account", "stage_promo_credit", "modify_billing"]),
    ]:
        assert client.post(
            f"/runs/{run_id}/agents",
            json={"agent_id": agent_id, "role": role, "parent_agent_id": parent_id, "allowed_tools": tools},
        ).status_code == 200
    credential = client.post(
        f"/runs/{run_id}/gateway/credentials", json={"agent_id": "account-agent"}
    ).json()["credential"]
    order_credential = client.post(
        f"/runs/{run_id}/gateway/credentials", json={"agent_id": "order-agent"}
    ).json()["credential"]

    launch = client.post(
        f"/runs/{run_id}/supervise",
        json={"agent_ids": ["parent-agent", "order-agent", "account-agent"]},
    )
    assert launch.status_code == 200

    staged = client.post(
        f"/runs/{run_id}/gateway/execute",
        json={"agent_id": "account-agent", "credential": credential,
              "tool": "stage_promo_credit", "arguments": {"customer_id": "C104", "amount_cents": 5000}},
    )
    assert staged.status_code == 200

    forbidden_tool = client.post(
        f"/runs/{run_id}/gateway/execute",
        json={"agent_id": "account-agent", "credential": credential,
              "tool": "modify_billing", "arguments": {"customer_id": "C104", "amount": 25}},
    )
    assert forbidden_tool.status_code == 403
    assert client.get(f"/runs/{run_id}/agents/account-agent").json()["status"] == "STOPPED"
    assert client.get(f"/runs/{run_id}/agents/order-agent").json()["status"] == "RUNNING"

    revoked = client.post(
        f"/runs/{run_id}/gateway/execute",
        json={"agent_id": "account-agent", "credential": credential,
              "tool": "read_account", "arguments": {"customer_id": "C104"}},
    )
    sibling = client.post(
        f"/runs/{run_id}/gateway/execute",
        json={"agent_id": "order-agent", "credential": order_credential,
              "tool": "read_order", "arguments": {"order_id": "ORD-882"}},
    )
    assert revoked.status_code == 403
    assert sibling.status_code == 200
    with AgentTreeDB(database_path)._connect() as connection:
        committed = connection.execute(
            "SELECT promo_credit_cents FROM business_accounts WHERE run_id = ? AND customer_id = 'C104'",
            (run_id,),
        ).fetchone()[0]
        journal = connection.execute(
            "SELECT state FROM journal WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
    assert committed == 0
    assert journal == "ABORTED"
    account_agent = AgentTreeDB(database_path).get_agent(run_id, "account-agent")
    assert "modify_billing" not in account_agent["allowed_tools"]
    client.post(f"/runs/{run_id}/cleanup")


def test_scope_and_amount_policy_denials_do_not_stage_effects(tmp_path):
    database_path = str(tmp_path / "scope-policy.db")
    app = build_app(database_path)
    client = TestClient(app)
    for run_id, arguments in [
        ("wrong-resource-run", {"customer_id": "C999"}),
        ("amount-limit-run", {"customer_id": "C104", "amount_cents": 5001}),
    ]:
        _create_agents(client, run_id)
        credential = client.post(
            f"/runs/{run_id}/gateway/credentials", json={"agent_id": "account-agent"}
        ).json()["credential"]
        tool = "read_account" if run_id == "wrong-resource-run" else "stage_promo_credit"
        denied = client.post(
            f"/runs/{run_id}/gateway/execute",
            json={"agent_id": "account-agent", "credential": credential,
                  "tool": tool, "arguments": arguments},
        )
        assert denied.status_code == 403
        with AgentTreeDB(database_path)._connect() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM journal WHERE run_id = ?", (run_id,)
            ).fetchone()[0] == 0
