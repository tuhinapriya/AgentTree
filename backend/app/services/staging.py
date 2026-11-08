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
        policy = BRANCH_POLICIES.get(branch_id.removesuffix("-agent"))
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
