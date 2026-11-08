"""Stage supported demo mutations without changing committed business state."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.app.services.demo_policy import (
    BRANCH_POLICIES,
    CUSTOMER_ID,
    ORDER_ID,
    BranchState,
    EffectState,
    EventOrigin,
    TOOL_STAGE_PROMO_CREDIT,
    TOOL_STAGE_REFUND,
)


class StagingService:
    """Journal the two supported demo writes and provide branch-local reads.

    Authentication and public gateway routing are intentionally left to the
    gateway integration stage. Callers must supply a branch identity that has
    already been authenticated by the trusted backend.
    """

    def __init__(self, database):
        self.database = database

    def read_order(self, run_id: str, branch_id: str, order_id: str = ORDER_ID) -> dict[str, Any]:
        self._require_run(run_id)
        if order_id != ORDER_ID:
            raise ValueError("Order is outside the demo policy scope")
        with self.database._connect() as connection:
            row = connection.execute(
                """SELECT order_id, customer_id, paid_cents, refunded_cents, version, status
                   FROM business_orders WHERE run_id = ? AND order_id = ?""",
                (run_id, order_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"Order '{order_id}' was not found")
            pending = connection.execute(
                """SELECT COALESCE(SUM(CAST(json_extract(args_json, '$.amount_cents') AS INTEGER)), 0)
                   FROM journal WHERE run_id = ? AND branch_id = ? AND tool = ? AND state = ?""",
                (run_id, branch_id, TOOL_STAGE_REFUND, EffectState.STAGED.value),
            ).fetchone()[0]
        return {
            "order_id": row[0],
            "customer_id": row[1],
            "paid_cents": row[2],
            "refunded_cents": row[3],
            "pending_refund_cents": pending,
            "effective_refunded_cents": row[3] + pending,
            "version": row[4],
            "status": row[5],
            "is_provisional": pending > 0,
        }

    def read_account(self, run_id: str, branch_id: str, customer_id: str = CUSTOMER_ID) -> dict[str, Any]:
        self._require_run(run_id)
        if customer_id != CUSTOMER_ID:
            raise ValueError("Customer is outside the demo policy scope")
        with self.database._connect() as connection:
            row = connection.execute(
                """SELECT customer_id, promo_credit_cents, version, notes
                   FROM business_accounts WHERE run_id = ? AND customer_id = ?""",
                (run_id, customer_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"Account '{customer_id}' was not found")
            pending = connection.execute(
                """SELECT COALESCE(SUM(CAST(json_extract(args_json, '$.amount_cents') AS INTEGER)), 0)
                   FROM journal WHERE run_id = ? AND branch_id = ? AND tool = ? AND state = ?""",
                (run_id, branch_id, TOOL_STAGE_PROMO_CREDIT, EffectState.STAGED.value),
            ).fetchone()[0]
        return {
            "customer_id": row[0],
            "promo_credit_cents": row[1],
            "pending_promo_credit_cents": pending,
            "effective_promo_credit_cents": row[1] + pending,
            "version": row[2],
            "notes": row[3],
            "is_provisional": pending > 0,
        }

    def get_business_state(self, run_id: str) -> dict[str, Any]:
        self._require_run(run_id)
        with self.database._connect() as connection:
            account = connection.execute(
                "SELECT * FROM business_accounts WHERE run_id = ? AND customer_id = ?",
                (run_id, CUSTOMER_ID),
            ).fetchone()
            order = connection.execute(
                "SELECT * FROM business_orders WHERE run_id = ? AND order_id = ?",
                (run_id, ORDER_ID),
            ).fetchone()
        if account is None or order is None:
            raise ValueError("Transactional demo fixtures are missing")
        return {
            "account": {
                "customer_id": account[1],
                "promo_credit_cents": account[2],
                "version": account[3],
                "notes": account[4],
            },
            "order": {
                "order_id": order[1],
                "customer_id": order[2],
                "paid_cents": order[3],
                "refunded_cents": order[4],
                "version": order[5],
                "status": order[6],
            },
        }

    def get_effects(self, run_id: str) -> dict[str, Any]:
        self._require_run(run_id)
        with self.database._connect() as connection:
            branches = connection.execute(
                """SELECT branch_id, state, violation_count, completed_at, committed_at, aborted_at
                   FROM branches WHERE run_id = ? ORDER BY branch_id""",
                (run_id,),
            ).fetchall()
            rows = connection.execute(
                """SELECT action_id, branch_id, sequence, tool, args_json, base_version,
                          state, idempotency_key, created_at
                   FROM journal WHERE run_id = ? ORDER BY created_at, branch_id, sequence""",
                (run_id,),
            ).fetchall()
        return {
            "run_id": run_id,
            "branches": [
                {"branch_id": row[0], "state": row[1], "violation_count": row[2],
                 "completed_at": row[3], "committed_at": row[4], "aborted_at": row[5]}
                for row in branches
            ],
            "effects": [
                {"action_id": row[0], "branch_id": row[1], "sequence": row[2],
                 "tool": row[3], "arguments": json.loads(row[4]), "base_version": row[5],
                 "state": row[6], "idempotency_key": row[7], "created_at": row[8]}
                for row in rows
            ],
        }

    def stage_refund(
        self,
        run_id: str,
        branch_id: str,
        order_id: str,
        amount_cents: int,
        idempotency_key: str | None = None,
        origin: str = EventOrigin.CONTROLLED_TEST.value,
    ) -> dict[str, Any]:
        return self._stage(
            run_id=run_id,
            branch_id=branch_id,
            tool=TOOL_STAGE_REFUND,
            arguments={"order_id": order_id, "amount_cents": amount_cents},
            resource_id=order_id,
            idempotency_key=idempotency_key,
            origin=origin,
        )

    def stage_promo_credit(
        self,
        run_id: str,
        branch_id: str,
        customer_id: str,
        amount_cents: int,
        idempotency_key: str | None = None,
        origin: str = EventOrigin.CONTROLLED_TEST.value,
    ) -> dict[str, Any]:
        return self._stage(
            run_id=run_id,
            branch_id=branch_id,
            tool=TOOL_STAGE_PROMO_CREDIT,
            arguments={"customer_id": customer_id, "amount_cents": amount_cents},
            resource_id=customer_id,
            idempotency_key=idempotency_key,
            origin=origin,
        )

    def mark_ready_to_commit(
        self,
        run_id: str,
        branch_id: str,
        verified_completion: bool,
        origin: str = EventOrigin.SUPERVISOR.value,
    ) -> dict[str, Any]:
        """Accept supervisor-verified completion; workers cannot commit directly."""
        self._require_run(run_id)
        if verified_completion is not True:
            raise PermissionError("Supervisor must verify branch completion")
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.database._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            branch = connection.execute(
                "SELECT state, violation_count FROM branches WHERE run_id = ? AND branch_id = ?",
                (run_id, branch_id),
            ).fetchone()
            if branch is None:
                connection.rollback()
                raise ValueError(f"Branch '{branch_id}' does not exist in run '{run_id}'")
            if branch[0] == BranchState.READY_TO_COMMIT.value:
                connection.commit()
                return {"run_id": run_id, "branch_id": branch_id, "state": branch[0]}
            if branch[0] != BranchState.RUNNING.value or branch[1] != 0:
                connection.rollback()
                raise ValueError("Branch is not eligible to commit")
            connection.execute(
                "UPDATE branches SET state = ?, completed_at = ? WHERE run_id = ? AND branch_id = ?",
                (BranchState.READY_TO_COMMIT.value, timestamp, run_id, branch_id),
            )
            self._append_event(connection, run_id, branch_id, f"{branch_id}-agent",
                               origin, "COMMIT_ELIGIBLE", {}, timestamp)
            connection.commit()
        return {"run_id": run_id, "branch_id": branch_id, "state": BranchState.READY_TO_COMMIT.value}

    def commit_branch(self, run_id: str, branch_id: str) -> dict[str, Any]:
        """Apply every staged action for a branch in one SQLite transaction."""
        self._require_run(run_id)
        timestamp = datetime.now(timezone.utc).isoformat()
        connection = self.database._connect()
        connection.row_factory = sqlite3.Row
        commit_started = False
        try:
            connection.execute("BEGIN IMMEDIATE")
            branch = connection.execute(
                "SELECT state, violation_count FROM branches WHERE run_id = ? AND branch_id = ?",
                (run_id, branch_id),
            ).fetchone()
            if branch is None:
                raise ValueError(f"Branch '{branch_id}' does not exist in run '{run_id}'")
            if branch[0] == BranchState.COMMITTED.value:
                connection.commit()
                return {"run_id": run_id, "branch_id": branch_id, "state": branch[0], "actions": []}
            if branch[0] != BranchState.READY_TO_COMMIT.value or branch[1] != 0:
                raise ValueError("Branch is not eligible to commit")

            actions = connection.execute(
                """SELECT action_id, tool, args_json, base_version, state
                   FROM journal WHERE run_id = ? AND branch_id = ? ORDER BY sequence""",
                (run_id, branch_id),
            ).fetchall()
            if any(action[4] != EffectState.STAGED.value for action in actions):
                raise ValueError("Branch has an action that is no longer staged")

            # Check every resource against the version observed when the first
            # action for it was staged, before applying any mutation.
            resources: dict[tuple[str, str], sqlite3.Row] = {}
            for action in actions:
                args = json.loads(action[2])
                if action[1] == TOOL_STAGE_REFUND:
                    key = (action[1], args["order_id"])
                elif action[1] == TOOL_STAGE_PROMO_CREDIT:
                    key = (action[1], args["customer_id"])
                else:
                    raise ValueError(f"Unsupported staged tool '{action[1]}'")
                resource = resources.get(key)
                if resource is None:
                    resource = self._resource_row(connection, run_id, action[1], key[1])
                    resources[key] = resource
                if resource["version"] != action[3]:
                    self._reject_conflict(connection, run_id, branch_id, actions, timestamp)
                    connection.commit()
                    return {"run_id": run_id, "branch_id": branch_id,
                            "state": BranchState.COMMIT_REJECTED.value, "actions": []}

            connection.execute(
                "UPDATE branches SET state = ? WHERE run_id = ? AND branch_id = ?",
                (BranchState.COMMITTING.value, run_id, branch_id),
            )
            commit_started = True
            for action in actions:
                args = json.loads(action[2])
                if action[1] == TOOL_STAGE_REFUND:
                    order = connection.execute(
                        "SELECT paid_cents, refunded_cents FROM business_orders WHERE run_id = ? AND order_id = ?",
                        (run_id, args["order_id"]),
                    ).fetchone()
                    if order is None or order[1] + args["amount_cents"] > order[0]:
                        raise ValueError("Refund precondition failed at commit")
                    connection.execute(
                        """UPDATE business_orders SET refunded_cents = refunded_cents + ?,
                           version = version + 1, status = CASE WHEN refunded_cents + ? >= paid_cents
                           THEN 'REFUNDED' ELSE status END WHERE run_id = ? AND order_id = ?""",
                        (args["amount_cents"], args["amount_cents"], run_id, args["order_id"]),
                    )
                elif action[1] == TOOL_STAGE_PROMO_CREDIT:
                    connection.execute(
                        """UPDATE business_accounts SET promo_credit_cents = promo_credit_cents + ?,
                           version = version + 1 WHERE run_id = ? AND customer_id = ?""",
                        (args["amount_cents"], run_id, args["customer_id"]),
                    )
                connection.execute(
                    "UPDATE journal SET state = ? WHERE action_id = ?",
                    (EffectState.COMMITTED.value, action[0]),
                )
            connection.execute(
                "UPDATE branches SET state = ?, committed_at = ? WHERE run_id = ? AND branch_id = ?",
                (BranchState.COMMITTED.value, timestamp, run_id, branch_id),
            )
            self._append_event(connection, run_id, branch_id, f"{branch_id}-agent",
                               EventOrigin.SUPERVISOR.value, "BRANCH_COMMITTED",
                               {"action_ids": [action[0] for action in actions]}, timestamp)
            connection.commit()
            return {"run_id": run_id, "branch_id": branch_id,
                    "state": BranchState.COMMITTED.value,
                    "actions": [action[0] for action in actions]}
        except Exception as exc:
            connection.rollback()
            if commit_started:
                # The business transaction rolled back. Persist an explicit
                # terminal outcome so the dashboard cannot leave this branch
                # looking eligible for a commit that already failed.
                with self.database._connect() as failure_connection:
                    failure_connection.execute("BEGIN IMMEDIATE")
                    failure_connection.execute(
                        """UPDATE journal SET state = ? WHERE run_id = ? AND branch_id = ?
                           AND state = ?""",
                        (EffectState.ABORTED.value, run_id, branch_id, EffectState.STAGED.value),
                    )
                    failure_connection.execute(
                        "UPDATE branches SET state = ?, aborted_at = ? WHERE run_id = ? AND branch_id = ?",
                        (BranchState.COMMIT_FAILED.value, timestamp, run_id, branch_id),
                    )
                    self._append_event(
                        failure_connection, run_id, branch_id, f"{branch_id}-agent",
                        EventOrigin.SUPERVISOR.value, "COMMIT_FAILED",
                        {"error": str(exc)}, timestamp,
                    )
            raise
        finally:
            connection.close()

    def abort_branch(self, run_id: str, branch_id: str, reason: str = "CONTAINED") -> dict[str, Any]:
        """Atomically prevent future commit and mark all pending effects aborted."""
        self._require_run(run_id)
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.database._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            branch = connection.execute(
                "SELECT state FROM branches WHERE run_id = ? AND branch_id = ?",
                (run_id, branch_id),
            ).fetchone()
            if branch is None:
                connection.rollback()
                raise ValueError(f"Branch '{branch_id}' does not exist in run '{run_id}'")
            if branch[0] == BranchState.COMMITTED.value:
                connection.commit()
                return {"run_id": run_id, "branch_id": branch_id,
                        "state": BranchState.COMMITTED.value, "aborted_actions": []}
            if branch[0] == BranchState.ABORTED.value:
                connection.commit()
                return {"run_id": run_id, "branch_id": branch_id,
                        "state": BranchState.ABORTED.value, "aborted_actions": []}

            connection.execute(
                "UPDATE branches SET state = ? WHERE run_id = ? AND branch_id = ?",
                (BranchState.ABORTING.value, run_id, branch_id),
            )
            action_rows = connection.execute(
                """SELECT action_id FROM journal WHERE run_id = ? AND branch_id = ? AND state = ?""",
                (run_id, branch_id, EffectState.STAGED.value),
            ).fetchall()
            action_ids = [row[0] for row in action_rows]
            connection.execute(
                """UPDATE journal SET state = ? WHERE run_id = ? AND branch_id = ? AND state = ?""",
                (EffectState.ABORTED.value, run_id, branch_id, EffectState.STAGED.value),
            )
            connection.execute(
                "UPDATE branches SET state = ?, aborted_at = ? WHERE run_id = ? AND branch_id = ?",
                (BranchState.ABORTED.value, timestamp, run_id, branch_id),
            )
            self._append_event(connection, run_id, branch_id, f"{branch_id}-agent",
                               EventOrigin.SUPERVISOR.value, "BRANCH_ABORTED",
                               {"reason": reason, "action_ids": action_ids}, timestamp)
            connection.commit()
        return {"run_id": run_id, "branch_id": branch_id,
                "state": BranchState.ABORTED.value, "aborted_actions": action_ids}

    def contain_branch(
        self,
        run_id: str,
        branch_id: str,
        reason: str,
        policy_violation: bool = False,
    ) -> dict[str, Any]:
        """Revoke branch authority and abort pending actions in one DB transaction."""
        self._require_run(run_id)
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.database._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            branch = connection.execute(
                "SELECT state FROM branches WHERE run_id = ? AND branch_id = ?",
                (run_id, branch_id),
            ).fetchone()
            if branch is None:
                connection.rollback()
                raise ValueError(f"Branch '{branch_id}' does not exist in run '{run_id}'")

            connection.execute(
                """UPDATE agent_sessions SET revoked_at = ?
                   WHERE run_id = ? AND branch_id = ? AND revoked_at IS NULL""",
                (timestamp, run_id, branch_id),
            )
            if branch[0] in {BranchState.COMMITTED.value, BranchState.COMMITTING.value}:
                connection.commit()
                return {"run_id": run_id, "branch_id": branch_id,
                        "state": branch[0], "aborted_actions": []}
            if branch[0] == BranchState.ABORTED.value:
                connection.commit()
                return {"run_id": run_id, "branch_id": branch_id,
                        "state": BranchState.ABORTED.value, "aborted_actions": []}

            connection.execute(
                """UPDATE branches SET state = ?, violation_count = violation_count + ?
                   WHERE run_id = ? AND branch_id = ?""",
                (BranchState.ABORTING.value, int(policy_violation), run_id, branch_id),
            )
            action_rows = connection.execute(
                """SELECT action_id FROM journal WHERE run_id = ? AND branch_id = ? AND state = ?""",
                (run_id, branch_id, EffectState.STAGED.value),
            ).fetchall()
            action_ids = [row[0] for row in action_rows]
            connection.execute(
                """UPDATE journal SET state = ? WHERE run_id = ? AND branch_id = ? AND state = ?""",
                (EffectState.ABORTED.value, run_id, branch_id, EffectState.STAGED.value),
            )
            connection.execute(
                "UPDATE branches SET state = ?, aborted_at = ? WHERE run_id = ? AND branch_id = ?",
                (BranchState.ABORTED.value, timestamp, run_id, branch_id),
            )
            self._append_event(
                connection, run_id, branch_id, f"{branch_id}-agent",
                EventOrigin.SUPERVISOR.value,
                "POLICY_VIOLATION_CONTAINED" if policy_violation else "BRANCH_STOPPED",
                {"reason": reason, "action_ids": action_ids}, timestamp,
            )
            connection.commit()
        return {"run_id": run_id, "branch_id": branch_id,
                "state": BranchState.ABORTED.value, "aborted_actions": action_ids}

    def _reject_conflict(self, connection, run_id, branch_id, actions, timestamp):
        action_ids = [action[0] for action in actions]
        connection.execute(
            """UPDATE journal SET state = ? WHERE run_id = ? AND branch_id = ? AND state = ?""",
            (EffectState.ABORTED.value, run_id, branch_id, EffectState.STAGED.value),
        )
        connection.execute(
            """UPDATE branches SET state = ?, aborted_at = ?
               WHERE run_id = ? AND branch_id = ?""",
            (BranchState.COMMIT_REJECTED.value, timestamp, run_id, branch_id),
        )
        self._append_event(connection, run_id, branch_id, f"{branch_id}-agent",
                           EventOrigin.SUPERVISOR.value, "COMMIT_REJECTED",
                           {"reason": "RESOURCE_VERSION_CONFLICT", "action_ids": action_ids}, timestamp)

    def _stage(
        self,
        run_id: str,
        branch_id: str,
        tool: str,
        arguments: dict[str, Any],
        resource_id: str,
        idempotency_key: str | None,
        origin: str,
    ) -> dict[str, Any]:
        self._require_run(run_id)
        agent = self.database.get_agent(run_id, branch_id)
        policy_key = agent["role"] if agent is not None else branch_id.removesuffix("-agent")
        policy = BRANCH_POLICIES.get(policy_key)
        if policy is None or tool not in policy.allowed_tools:
            raise PermissionError("Tool is not allowed for this branch")
        if resource_id != (policy.order_id if tool == TOOL_STAGE_REFUND else policy.customer_id):
            raise PermissionError("Resource is outside the branch policy scope")
        amount_cents = arguments.get("amount_cents")
        if isinstance(amount_cents, bool) or not isinstance(amount_cents, int) or amount_cents <= 0:
            raise ValueError("amount_cents must be a positive integer")
        if policy.max_amount_cents is None or amount_cents > policy.max_amount_cents:
            raise PermissionError("Amount exceeds the branch policy limit")

        key = idempotency_key or uuid.uuid4().hex
        if not isinstance(key, str) or not key.strip():
            raise ValueError("idempotency_key must be a non-empty string")
        action_id = f"stg-{uuid.uuid4().hex}"
        created_at = datetime.now(timezone.utc).isoformat()

        with self.database._connect() as connection:
            connection.row_factory = sqlite3.Row
            branch = connection.execute(
                "SELECT state FROM branches WHERE run_id = ? AND branch_id = ?",
                (run_id, branch_id),
            ).fetchone()
            if branch is None:
                raise ValueError(f"Branch '{branch_id}' does not exist in run '{run_id}'")
            if branch["state"] != BranchState.RUNNING.value:
                raise PermissionError("Branch is not accepting staged actions")

            previous = connection.execute(
                "SELECT * FROM journal WHERE run_id = ? AND idempotency_key = ?",
                (run_id, key),
            ).fetchone()
            if previous is not None:
                if previous["branch_id"] != branch_id or previous["tool"] != tool or json.loads(previous["args_json"]) != arguments:
                    raise ValueError("Idempotency key was already used for a different action")
                return self._stage_result(previous["action_id"], arguments, previous["state"])

            resource = self._resource_row(connection, run_id, tool, resource_id)
            staged_total = connection.execute(
                """SELECT COALESCE(SUM(CAST(json_extract(args_json, '$.amount_cents') AS INTEGER)), 0)
                   FROM journal WHERE run_id = ? AND branch_id = ? AND tool = ? AND state = ?""",
                (run_id, branch_id, tool, EffectState.STAGED.value),
            ).fetchone()[0]
            if tool == TOOL_STAGE_REFUND:
                available = resource["paid_cents"] - resource["refunded_cents"]
                if amount_cents + staged_total > available:
                    raise ValueError("Refund exceeds the remaining paid amount")
                base_version = resource["version"]
            else:
                if amount_cents + staged_total > policy.max_amount_cents:
                    raise ValueError("Promo credit total exceeds the branch policy limit")
                base_version = resource["version"]

            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM journal WHERE run_id = ? AND branch_id = ?",
                (run_id, branch_id),
            ).fetchone()[0]
            connection.execute(
                """INSERT INTO journal
                   (action_id, run_id, branch_id, sequence, tool, args_json, base_version,
                    state, idempotency_key, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (action_id, run_id, branch_id, sequence, tool, json.dumps(arguments, sort_keys=True),
                 base_version, EffectState.STAGED.value, key, created_at),
            )
            self._append_event(
                connection,
                run_id,
                branch_id,
                f"{branch_id}-agent",
                origin,
                "TOOL_STAGED",
                {"tool": tool, "action_id": action_id, **arguments},
                created_at,
            )

        return self._stage_result(action_id, arguments, EffectState.STAGED.value)

    @staticmethod
    def _resource_row(connection, run_id: str, tool: str, resource_id: str) -> sqlite3.Row:
        if tool == TOOL_STAGE_REFUND:
            row = connection.execute(
                "SELECT * FROM business_orders WHERE run_id = ? AND order_id = ?",
                (run_id, resource_id),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT * FROM business_accounts WHERE run_id = ? AND customer_id = ?",
                (run_id, resource_id),
            ).fetchone()
        if row is None:
            raise ValueError(f"Resource '{resource_id}' was not found")
        return row

    def _require_run(self, run_id: str) -> None:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")

    @staticmethod
    def _append_event(connection, run_id, branch_id, agent_id, origin, event_type, payload, created_at):
        connection.execute(
            """INSERT INTO audit_events
               (run_id, branch_id, agent_id, origin, type, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, branch_id, agent_id, origin, event_type, json.dumps(payload, sort_keys=True), created_at),
        )

    @staticmethod
    def _stage_result(action_id: str, arguments: dict[str, Any], state: str) -> dict[str, Any]:
        preview = dict(arguments)
        return {
            "status": state,
            "action_id": action_id,
            "executed": False,
            "committed": state == EffectState.COMMITTED.value,
            "preview": preview,
        }
