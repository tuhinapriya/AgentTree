from __future__ import annotations

import uuid
from typing import Any


class GatewayService:
    def __init__(self, database):
        self.database = database
        self.credentials: dict[str, dict[str, str]] = {}
        self.revoked_credentials: dict[str, set[str]] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}
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

    def issue_credential(self, run_id: str, agent_id: str) -> dict[str, str]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")

        agent = self.database.get_agent(run_id, agent_id)
        if agent is None:
            raise ValueError(f"Agent '{agent_id}' was not found in run '{run_id}'")

        token = f"{run_id}:{agent_id}:{uuid.uuid4().hex}"
        self.credentials.setdefault(run_id, {})[token] = agent_id
        return {"run_id": run_id, "agent_id": agent_id, "credential": token}

    def execute(
        self,
        run_id: str,
        agent_id: str,
        credential: str,
        tool_name: str,
        arguments: dict[str, Any],
        origin: str | None = None,
    ) -> dict[str, Any]:
        origin = origin or "STANDARD"
        if credential is None or credential == "":
            self.record_event(run_id, agent_id, tool_name, "DENY", "MISSING_CREDENTIAL", origin)
            raise ValueError("Missing credentials")

        if credential in self.revoked_credentials.get(run_id, set()):
            self.record_event(run_id, agent_id, tool_name, "DENY", "TOOL_NOT_DELEGATED", origin)
            raise PermissionError("Permission denied")

        token_owner = self.credentials.get(run_id, {}).get(credential)
        if token_owner is None:
            self.record_event(run_id, agent_id, tool_name, "DENY", "INVALID_CREDENTIAL", origin)
            raise ValueError("Invalid credentials")
        if token_owner != agent_id:
            self.record_event(run_id, agent_id, tool_name, "DENY", "TOOL_NOT_DELEGATED", origin)
            raise PermissionError("Permission denied")

        agent = self.database.get_agent(run_id, agent_id)
        if agent is None:
            self.record_event(run_id, agent_id, tool_name, "DENY", "INVALID_CREDENTIAL", origin)
            raise ValueError(f"Agent '{agent_id}' was not found in run '{run_id}'")

        if tool_name not in self._known_tools():
            self.record_event(run_id, agent_id, tool_name, "DENY", "UNKNOWN_TOOL", origin)
            raise KeyError(f"Unknown tool '{tool_name}'")

        if tool_name not in agent["allowed_tools"]:
            self.record_event(run_id, agent_id, tool_name, "DENY", "TOOL_NOT_DELEGATED", origin)
            raise PermissionError("Permission denied")

        if not isinstance(arguments, dict):
            self.record_event(run_id, agent_id, tool_name, "DENY", "INVALID_ARGUMENTS", origin)
            raise ValueError("Tool arguments must be an object")

        result = self._dispatch_tool(tool_name, arguments)
        self.record_event(run_id, agent_id, tool_name, "ALLOW", None, origin)
        return result

    def revoke_branch(self, run_id: str, branch_id: str) -> list[str]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")

        branch_members = self._branch_members(run_id, branch_id)
        for token, owner in list(self.credentials.get(run_id, {}).items()):
            if owner in branch_members:
                self.revoked_credentials.setdefault(run_id, set()).add(token)
                del self.credentials[run_id][token]
        return branch_members

    def get_events(self, run_id: str) -> list[dict[str, Any]]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")
        return self.events.get(run_id, [])

    def reset_demo(self, run_id: str) -> dict[str, Any]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")
        self.business_db = self._initial_business_state()
        self.events[run_id] = []
        self.credentials.pop(run_id, None)
        self.revoked_credentials.pop(run_id, None)
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
        event = {
            "run_id": run_id,
            "agent_id": agent_id,
            "tool": tool,
            "decision": decision,
            "reason_code": reason_code,
            "origin": origin,
        }
        self.events.setdefault(run_id, []).append(event)
        return event

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
        return ["read_orders", "process_order", "read_account", "modify_billing"]

    def _dispatch_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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
            account = self.business_db["accounts"].get(customer_id)
            if account is None:
                raise KeyError(f"Account '{customer_id}' was not found")
            return {"tool": tool_name, "result": dict(account)}

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
