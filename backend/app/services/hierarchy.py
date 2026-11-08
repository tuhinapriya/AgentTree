from __future__ import annotations

from typing import Any, Optional

from backend.app.services.demo_policy import BRANCH_POLICIES


class HierarchyService:
    def __init__(self, database):
        self.database = database

    def create_run(self, run_id: str, scenario: str = "customer-operations") -> dict[str, Any]:
        if self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' already exists")
        self.database.create_run(run_id, scenario)
        self.database.create_demo_fixtures(run_id)
        return {"run_id": run_id, "scenario": scenario, "status": "CREATED"}

    def create_agent(
        self,
        run_id: str,
        agent_id: str,
        role: str,
        parent_agent_id: Optional[str] = None,
        allowed_tools: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")
        if self.database.agent_exists_in_run(run_id, agent_id):
            raise ValueError(f"Agent '{agent_id}' already exists in run '{run_id}'")
        if parent_agent_id == agent_id:
            raise ValueError("An agent cannot be its own parent")
        if parent_agent_id is not None and not self.database.agent_exists_in_run(run_id, parent_agent_id):
            raise ValueError(f"Unknown parent agent '{parent_agent_id}'")
        if parent_agent_id is not None and self._creates_cycle(run_id, agent_id, parent_agent_id):
            raise ValueError("Cyclic hierarchy is not allowed")

        policy = BRANCH_POLICIES.get(role)
        if policy is None:
            raise ValueError(f"Unsupported agent role '{role}'")
        if parent_agent_id is None and role != "parent":
            raise ValueError("Only a parent agent can be a run root")
        if parent_agent_id is not None and role not in {"order", "account"}:
            raise ValueError("Children must use a predefined order or account role")
        # Agent registration may narrow a trusted role template, but it cannot
        # grant tools that the application policy does not permit.
        tools = sorted(set(allowed_tools or []).intersection(policy.allowed_tools))
        self.database.create_agent(
            run_id=run_id,
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            role=role,
            allowed_tools=tools,
        )
        return self.database.get_agent(run_id, agent_id)

    def get_hierarchy(self, run_id: str) -> dict[str, Any]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")

        agents = self.database.get_agents_for_run(run_id)
        for agent in agents:
            policy = BRANCH_POLICIES[agent["role"]]
            agent["policy"] = {
                "role": agent["role"],
                "allowed_tools": sorted(set(agent["allowed_tools"]).intersection(policy.allowed_tools)),
                "customer_id": policy.customer_id,
                "order_id": policy.order_id,
                "max_amount_cents": policy.max_amount_cents,
                "commit_on_verified_completion": policy.commit_on_verified_completion,
                "abort_on_scope_violation": policy.abort_on_scope_violation,
            }
        roots = [agent for agent in agents if agent["parent_agent_id"] is None]
        ordered = []
        for root in roots:
            ordered.append(self._build_tree(root, agents))

        return {
            "run_id": run_id,
            "agents": agents,
            "tree": ordered,
        }

    def _creates_cycle(self, run_id: str, candidate_agent_id: str, parent_agent_id: str) -> bool:
        current = parent_agent_id
        visited = set()
        while current is not None:
            if current in visited:
                return True
            visited.add(current)
            if current == candidate_agent_id:
                return True
            current = self.database.get_parent_agent_id(run_id, current)
        return False

    def _build_tree(self, agent: dict[str, Any], agents: list[dict[str, Any]]) -> dict[str, Any]:
        children = [candidate for candidate in agents if candidate["parent_agent_id"] == agent["agent_id"]]
        tree = {
            "agent_id": agent["agent_id"],
            "role": agent["role"],
            "status": agent["status"],
            "task_state": agent["task_state"],
            "allowed_tools": agent["allowed_tools"],
            "policy": agent["policy"],
            "parent_agent_id": agent["parent_agent_id"],
            "children": [self._build_tree(child, agents) for child in children],
        }
        return tree
