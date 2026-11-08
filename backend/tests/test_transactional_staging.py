from backend.app.db import AgentTreeDB
from backend.app.services.hierarchy import HierarchyService
from backend.app.services.staging import StagingService


def _service(tmp_path, run_id="transactional-run"):
    database = AgentTreeDB(str(tmp_path / "transactional.db"))
    HierarchyService(database).create_run(run_id)
    return database, StagingService(database), run_id


def test_staged_effects_are_provisional_then_commit_or_abort_atomically(tmp_path):
    database, staging, run_id = _service(tmp_path)

    refund = staging.stage_refund(run_id, "order-agent", "ORD-882", 4500, "refund-1")
    credit = staging.stage_promo_credit(run_id, "account-agent", "C104", 5000, "credit-1")

    assert refund["status"] == "STAGED"
    assert refund["executed"] is False
    assert refund["committed"] is False
    assert staging.read_order(run_id, "order-agent")["refunded_cents"] == 0
    assert staging.read_order(run_id, "order-agent")["effective_refunded_cents"] == 4500
    assert staging.read_account(run_id, "account-agent")["promo_credit_cents"] == 0
    assert staging.read_account(run_id, "account-agent")["effective_promo_credit_cents"] == 5000
    assert staging.read_account(run_id, "order-agent")["effective_promo_credit_cents"] == 0

    staging.mark_ready_to_commit(run_id, "order-agent", verified_completion=True)
    staging.mark_ready_to_commit(run_id, "account-agent", verified_completion=True)
    committed = staging.commit_branch(run_id, "order-agent")
    aborted = staging.abort_branch(run_id, "account-agent", reason="POLICY_VIOLATION")

    assert committed["state"] == "COMMITTED"
    assert committed["actions"] == [refund["action_id"]]
    assert aborted["state"] == "ABORTED"
    assert aborted["aborted_actions"] == [credit["action_id"]]

    with database._connect() as connection:
        assert connection.execute(
            "SELECT refunded_cents FROM business_orders WHERE run_id = ? AND order_id = 'ORD-882'",
            (run_id,),
        ).fetchone()[0] == 4500
        assert connection.execute(
            "SELECT promo_credit_cents FROM business_accounts WHERE run_id = ? AND customer_id = 'C104'",
            (run_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT state FROM journal WHERE action_id = ?", (refund["action_id"],)
        ).fetchone()[0] == "COMMITTED"
        assert connection.execute(
            "SELECT state FROM journal WHERE action_id = ?", (credit["action_id"],)
        ).fetchone()[0] == "ABORTED"


def test_commit_retry_is_idempotent_and_worker_cannot_claim_verified_completion(tmp_path):
    _, staging, run_id = _service(tmp_path)
    action = staging.stage_refund(run_id, "order-agent", "ORD-882", 4500, "refund-retry")

    try:
        staging.mark_ready_to_commit(run_id, "order-agent", verified_completion=False)
    except PermissionError:
        pass
    else:
        raise AssertionError("unverified completion must not become commit eligible")

    staging.mark_ready_to_commit(run_id, "order-agent", verified_completion=True)
    first = staging.commit_branch(run_id, "order-agent")
    second = staging.commit_branch(run_id, "order-agent")

    assert first["actions"] == [action["action_id"]]
    assert second["state"] == "COMMITTED"
    assert second["actions"] == []
    assert staging.read_order(run_id, "order-agent")["refunded_cents"] == 4500
