from __future__ import annotations

import importlib.util
import json
import os
from typing import Any


class BedrockService:
    def __init__(self, database):
        self.database = database
        self.supported_roles = {"order", "account"}
        self.role_aliases = {
            "order": ["order", "fulfillment", "shipment"],
            "account": ["account", "billing", "customer"],
        }
        self.model_id = os.getenv("AWS_BEDROCK_MODEL_ID", "amazon.nova-micro-v1:0")
        self._boto3_available = importlib.util.find_spec("boto3") is not None
        self._aws_ready = self._boto3_available and all(
            os.getenv(key) for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
        )

    def delegate(self, run_id: str, parent_agent_id: str, customer_request: str) -> dict[str, Any]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")
        parent = self.database.get_agent(run_id, parent_agent_id)
        if parent is None:
            raise ValueError(f"Agent '{parent_agent_id}' was not found in run '{run_id}'")

        request = (customer_request or "").lower()
        if any(keyword in request for keyword in ["vault", "reboot", "system", "admin"]):
            raise ValueError("Unsupported delegated role: admin")

        requested_roles = self._infer_roles(request)
        if not requested_roles:
            requested_roles = ["order", "account"]

        delegated: list[dict[str, Any]] = []
        for role in requested_roles:
            if role not in self.supported_roles:
                raise ValueError(f"Unsupported delegated role: {role}")

            agent = self._find_agent_by_role(run_id, role)
            if agent is None:
                raise ValueError(f"No agent configured for role '{role}'")

            task = self._build_task(role, customer_request)
            delegated.append(
                {
                    "agent_id": agent["agent_id"],
                    "role": role,
                    "task": task,
                    "approved": True,
                }
            )

        if self._aws_ready:
            model_result = self._call_bedrock_for_delegation(customer_request, requested_roles)
            if model_result is not None:
                delegated = model_result

        return {
            "run_id": run_id,
            "parent_agent_id": parent_agent_id,
            "delegations": delegated,
        }

    def validate_role(self, role: str) -> str:
        if role not in self.supported_roles:
            raise ValueError(f"Unsupported delegated role: {role}")
        return role

    def _infer_roles(self, request: str) -> list[str]:
        matched: list[str] = []
        for role, aliases in self.role_aliases.items():
            if any(alias in request for alias in aliases):
                matched.append(role)
        return matched

    def _find_agent_by_role(self, run_id: str, role: str):
        for agent in self.database.get_agents_for_run(run_id):
            if agent["role"] == role:
                return agent
        return None

    def _call_bedrock_for_delegation(self, customer_request: str, requested_roles: list[str]) -> list[dict[str, Any]] | None:
        try:
            import boto3

            client = boto3.client(
                "bedrock-runtime",
                region_name=os.getenv("AWS_REGION", "us-east-1"),
            )
            prompt = (
                "Return a JSON object with a 'delegations' array containing objects with "
                "'agent_id', 'role', and 'task'. For this request, only propose roles "
                f"{requested_roles}. Request: {customer_request}"
            )
            payload = {
                "anthropic_version": "bedrock-2023-05-31",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 256,
            }
            response = client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(payload),
                accept="application/json",
                contentType="application/json",
            )
            raw = response.get("body")
            if isinstance(raw, bytes):
                data = json.loads(raw.decode("utf-8"))
            else:
                data = json.loads(raw.read().decode("utf-8")) if hasattr(raw, "read") else raw

            if isinstance(data, dict) and "content" in data:
                text = data["content"][0].get("text", "")
                parsed = json.loads(text)
                if isinstance(parsed, dict) and "delegations" in parsed:
                    return parsed["delegations"]
            if isinstance(data, dict) and "delegations" in data:
                return data["delegations"]
        except Exception:
            return None
        return None

    @staticmethod
    def _build_task(role: str, customer_request: str) -> str:
        if role == "order":
            return "Process the order in the customer request while verifying fulfillment state."
        if role == "account":
            return "Review the customer account and any billing implications in the request."
        return customer_request
