from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any

from backend.app.services.demo_policy import (
    BRANCH_POLICIES,
    BranchState,
    EventOrigin,
    KNOWN_TOOLS,
)
from backend.app.services.staging import StagingService


class GatewayService:
    def __init__(self, database, supervisor=None):
        self.database = database
        self.supervisor = supervisor
        self.staging = StagingService(database)
        self.business_db = self._initial_business_state()

    def _initial_business_state(self) -> dict[str, dict[str, Any]]:
        return {
            "orders": {
                "ORD-104": {
                    "order_id": "ORD-104",
                    "customer_id": "C104",
                    "status": "PENDING",
                    "fulfillment_confirmed": False,
                }
            },
            "accounts": {
                "C104": {
                    "customer_id": "C104",
                    "plan": "basic",
                    "balance": 100.0,
                }
            },
        }

    def issue_credential(
        self, run_id: str, agent_id: str,
        origin: str = EventOrigin.CONTROLLED_TEST.value,
    ) -> dict[str, str]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")

        agent = self.database.get_agent(run_id, agent_id)
        if agent is None:
            raise ValueError(f"Agent '{agent_id}' was not found in run '{run_id}'")

        with self.database._connect() as connection:
            branch = connection.execute(
                "SELECT state FROM branches WHERE run_id = ? AND branch_id = ?",
                (run_id, agent["branch_id"]),
            ).fetchone()
        if branch is None or branch[0] != BranchState.RUNNING.value:
            raise PermissionError("Branch is stopped")

        token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(token)
        with self.database._connect() as connection:
            connection.execute(
                """INSERT INTO agent_sessions
                   (token_hash, run_id, agent_id, branch_id, origin, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (token_hash, run_id, agent_id, agent["branch_id"], origin,
                 datetime.now(timezone.utc).isoformat()),
            )
        return {"run_id": run_id, "agent_id": agent_id, "credential": token}

    def authenticate_agent(self, run_id: str, agent_id: str, credential: str) -> dict[str, Any]:
        """Resolve a capability token to its persisted owner and live branch."""
        if not credential:
            raise ValueError("Missing credentials")
        with self.database._connect() as connection:
            session = connection.execute(
                """SELECT agent_id, branch_id, revoked_at FROM agent_sessions
                   WHERE run_id = ? AND token_hash = ?""",
                (run_id, self._hash_token(credential)),
            ).fetchone()
        if session is None:
            raise ValueError("Invalid credentials")
        if session[2] is not None or session[0] != agent_id:
            raise PermissionError("Permission denied")
        agent = self.database.get_agent(run_id, agent_id)
        if agent is None:
            raise ValueError(f"Agent '{agent_id}' was not found in run '{run_id}'")
        with self.database._connect() as connection:
            branch = connection.execute(
                "SELECT state FROM branches WHERE run_id = ? AND branch_id = ?",
                (run_id, session[1]),
            ).fetchone()
        if branch is None or branch[0] != BranchState.RUNNING.value:
            raise PermissionError("Permission denied")
        return agent

    def execute(
        self,
        run_id: str,
        agent_id: str,
        credential: str,
        tool_name: str,
        arguments: dict[str, Any],
        origin: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        origin = EventOrigin.CONTROLLED_TEST.value
        if credential is None or credential == "":
            self.record_event(run_id, agent_id, tool_name, "DENY", "MISSING_CREDENTIAL", origin)
            raise ValueError("Missing credentials")

        with self.database._connect() as connection:
            session = connection.execute(
                """SELECT agent_id, branch_id, revoked_at, origin FROM agent_sessions
                   WHERE run_id = ? AND token_hash = ?""",
                (run_id, self._hash_token(credential)),
            ).fetchone()
        if session is None:
            self.record_event(run_id, agent_id, tool_name, "DENY", "INVALID_CREDENTIAL", origin)
            raise ValueError("Invalid credentials")
        origin = session[3]
        if session[2] is not None:
            self.record_event(run_id, agent_id, tool_name, "DENY", "BRANCH_STOPPED", origin)
            raise PermissionError("Permission denied")
        if session[0] != agent_id:
            self.record_event(run_id, agent_id, tool_name, "DENY", "TOOL_NOT_DELEGATED", origin)
            raise PermissionError("Permission denied")

        agent = self.database.get_agent(run_id, agent_id)
        if agent is None:
            self.record_event(run_id, agent_id, tool_name, "DENY", "INVALID_CREDENTIAL", origin)
            raise ValueError(f"Agent '{agent_id}' was not found in run '{run_id}'")

        with self.database._connect() as connection:
            branch = connection.execute(
                "SELECT state FROM branches WHERE run_id = ? AND branch_id = ?",
                (run_id, session[1]),
            ).fetchone()
        if branch is None or branch[0] != BranchState.RUNNING.value:
            self.record_event(run_id, agent_id, tool_name, "DENY", "BRANCH_STOPPED", origin)
            raise PermissionError("Permission denied")

        if tool_name not in self._known_tools():
            self.record_event(run_id, agent_id, tool_name, "DENY", "UNKNOWN_TOOL", origin)
            raise KeyError(f"Unknown tool '{tool_name}'")

        policy = BRANCH_POLICIES.get(agent["role"])
        if policy is None or tool_name not in policy.allowed_tools or tool_name not in agent["allowed_tools"]:
            self.record_event(run_id, agent_id, tool_name, "DENY", "TOOL_NOT_DELEGATED", origin)
            self._contain_policy_violation(run_id, agent_id, session[1], tool_name, policy)
            raise PermissionError("Permission denied")

        if not isinstance(arguments, dict):
            self.record_event(run_id, agent_id, tool_name, "DENY", "INVALID_ARGUMENTS", origin)
            raise ValueError("Tool arguments must be an object")

        try:
            result = self._dispatch_tool(run_id, session[1], tool_name, arguments, origin, idempotency_key)
        except PermissionError:
            self.record_event(run_id, agent_id, tool_name, "DENY", "TOOL_NOT_DELEGATED", origin)
            self._contain_policy_violation(run_id, agent_id, session[1], tool_name, policy)
            raise
        except ValueError:
            self.record_event(run_id, agent_id, tool_name, "DENY", "INVALID_ARGUMENTS", origin)
            raise
        self.record_event(run_id, agent_id, tool_name, "ALLOW", None, origin)
        return result

    def revoke_branch(self, run_id: str, branch_id: str) -> list[str]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")

        branch_members = self._branch_members(run_id, branch_id)
        branch_ids = {self.database.get_agent(run_id, member)["branch_id"] for member in branch_members}
        for member_branch_id in branch_ids:
            self.staging.contain_branch(run_id, member_branch_id, "OPERATOR_STOP")
        return branch_members

    def _contain_policy_violation(self, run_id, agent_id, branch_id, tool_name, policy):
        if policy is None or not policy.abort_on_scope_violation:
            return
        result = self.staging.contain_branch(
            run_id, branch_id, f"DISALLOWED_TOOL:{tool_name}", policy_violation=True
        )
        if result["state"] in {BranchState.COMMITTED.value, BranchState.COMMITTING.value}:
            return
        if self.supervisor is None:
            return
        for member_id in self._branch_members(run_id, branch_id):
            try:
                self.supervisor.stop_agent(run_id, member_id)
            except ValueError:
                pass

    def get_events(self, run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")
        with self.database._connect() as connection:
            rows = connection.execute(
                """SELECT event_seq, branch_id, agent_id, origin, type, payload_json, created_at
                   FROM audit_events WHERE run_id = ? AND event_seq > ? ORDER BY event_seq""",
                (run_id, after_seq),
            ).fetchall()
        events = []
        for row in rows:
            payload = json.loads(row[5])
            events.append({
                "event_seq": row[0],
                "run_id": run_id,
                "branch_id": row[1],
                "agent_id": row[2],
                "origin": row[3],
                "type": row[4],
                "timestamp": row[6],
                "tool": payload.get("tool"),
                "decision": payload.get("decision"),
                "reason_code": payload.get("reason_code"),
                "detail": payload.get("detail") or payload.get("reason_code"),
                "payload": payload,
            })
        return events

    def reset_demo(self, run_id: str) -> dict[str, Any]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")
        self.database.reset_demo_fixtures(run_id)
        self.business_db = self._initial_business_state()
        with self.database._connect() as connection:
            connection.execute("DELETE FROM agent_sessions WHERE run_id = ?", (run_id,))
        return self.get_demo_state(run_id)

    def get_demo_state(self, run_id: str) -> dict[str, Any]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")
        account = dict(self.business_db["accounts"]["C104"])
        order = dict(self.business_db["orders"]["ORD-104"])
        return {
            "run_id": run_id,
            "customer": account,
            "account": account,
            "order": order,
            "transactional": self.staging.get_business_state(run_id),
        }

    def record_event(
        self,
        run_id: str,
        agent_id: str | None,
        tool: str,
        decision: str,
        reason_code: str | None,
        origin: str,
    ) -> dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {"tool": tool, "decision": decision, "reason_code": reason_code}
        with self.database._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO audit_events
                   (run_id, branch_id, agent_id, origin, type, payload_json, created_at)
                   VALUES (?, ?, ?, ?, 'TOOL_DECISION', ?, ?)""",
                (run_id, None, agent_id, origin, json.dumps(payload, sort_keys=True), timestamp),
            )
            event_seq = cursor.lastrowid
        return {
            "event_seq": event_seq,
            "run_id": run_id,
            "agent_id": agent_id,
            "tool": tool,
            "decision": decision,
            "reason_code": reason_code,
            "origin": origin,
            "timestamp": timestamp,
        }

    def _branch_members(self, run_id: str, branch_id: str) -> list[str]:
        root = self.database.get_agent(run_id, branch_id)
        if root is None:
            raise ValueError(f"Agent '{branch_id}' was not found in run '{run_id}'")

        agents = self.database.get_agents_for_run(run_id)
        descendants = [branch_id]
        stack = [branch_id]
        seen = {branch_id}

        while stack:
            current = stack.pop()
            for agent in agents:
                if agent["agent_id"] in seen:
                    continue
                if agent["parent_agent_id"] == current:
                    seen.add(agent["agent_id"])
                    descendants.append(agent["agent_id"])
                    stack.append(agent["agent_id"])

        return descendants

    def _known_tools(self) -> list[str]:
        return sorted(KNOWN_TOOLS | {"read_orders", "process_order"})

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _dispatch_tool(
        self, run_id: str, branch_id: str, tool_name: str,
        arguments: dict[str, Any], origin: str, idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if tool_name == "read_order":
            order_id = self._require_str(arguments, "order_id")
            return {"tool": tool_name, "result": self.staging.read_order(run_id, branch_id, order_id)}

        if tool_name == "stage_refund":
            order_id = self._require_str(arguments, "order_id")
            amount_cents = arguments.get("amount_cents")
            staged = self.staging.stage_refund(
                run_id, branch_id, order_id, amount_cents,
                idempotency_key=idempotency_key, origin=origin,
            )
            return {"tool": tool_name, "result": staged}

        if tool_name == "stage_promo_credit":
            customer_id = self._require_str(arguments, "customer_id")
            amount_cents = arguments.get("amount_cents")
            staged = self.staging.stage_promo_credit(
                run_id, branch_id, customer_id, amount_cents,
                idempotency_key=idempotency_key, origin=origin,
            )
            return {"tool": tool_name, "result": staged}

        if tool_name == "read_orders":
            order_id = self._require_str(arguments, "order_id")
            order = self.business_db["orders"].get(order_id)
            if order is None:
                raise KeyError(f"Order '{order_id}' was not found")
            return {"tool": tool_name, "result": dict(order)}

        if tool_name == "process_order":
            order_id = self._require_str(arguments, "order_id")
            order = self.business_db["orders"].get(order_id)
            if order is None:
                raise KeyError(f"Order '{order_id}' was not found")
            if order["status"] != "PENDING" or order["fulfillment_confirmed"]:
                raise ValueError("Business precondition not satisfied")
            order["status"] = "PROCESSED"
            order["fulfillment_confirmed"] = True
            return {"tool": tool_name, "result": dict(order)}

        if tool_name == "read_account":
            customer_id = self._require_str(arguments, "customer_id")
            if customer_id != "C104":
                raise PermissionError("Permission denied")
            account = self.staging.read_account(run_id, branch_id, customer_id)
            # Preserve the legacy display fields while exposing the
            # transaction-specific committed/provisional values.
            account.update({"plan": "basic", "balance": 100.0})
            return {"tool": tool_name, "result": account}

        if tool_name == "modify_billing":
            customer_id = self._require_str(arguments, "customer_id")
            amount = arguments.get("amount")
            if not isinstance(amount, (int, float)):
                raise ValueError("Billing amount is required")
            account = self.business_db["accounts"].get(customer_id)
            if account is None:
                raise KeyError(f"Account '{customer_id}' was not found")
            account["balance"] = round(float(account["balance"]) + float(amount), 2)
            return {"tool": tool_name, "result": dict(account)}

        raise KeyError(f"Unknown tool '{tool_name}'")

    @staticmethod
    def _require_str(arguments: dict[str, Any], field_name: str) -> str:
        value = arguments.get(field_name)
        if not isinstance(value, str) or value == "":
            raise ValueError(f"'{field_name}' is required")
        return value
