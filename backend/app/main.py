import json
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.app.db import AgentTreeDB
from backend.app.services.aws_observability import AWSObservabilityService
from backend.app.services.bedrock import BedrockService
from backend.app.services.gateway import GatewayService
from backend.app.services.hierarchy import HierarchyService
from backend.app.services.supervisor import SupervisorService
from backend.app.services.staging import StagingService


class RunCreate(BaseModel):
    run_id: str
    scenario: str = "customer-operations"


class AgentCreate(BaseModel):
    agent_id: str
    role: str
    parent_agent_id: Optional[str] = None
    allowed_tools: list[str] = Field(default_factory=list)


def build_app(database_path: Optional[str] = None) -> FastAPI:
    database = AgentTreeDB(database_path)
    service = HierarchyService(database)
    supervisor = SupervisorService(database)
    gateway = GatewayService(database, supervisor)
    supervisor.gateway = gateway
    staging = StagingService(database)
    bedrock = BedrockService(database)
    observability = AWSObservabilityService(database)
    app = FastAPI(title="AgentTree")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
            "http://0.0.0.0:5173",
            "http://0.0.0.0:5174",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def get_health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/runs")
    def create_run(payload: RunCreate) -> dict[str, Any]:
        try:
            return service.create_run(payload.run_id, payload.scenario)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/agents")
    def create_agent(run_id: str, payload: AgentCreate) -> dict[str, Any]:
        try:
            return service.create_agent(
                run_id=run_id,
                agent_id=payload.agent_id,
                role=payload.role,
                parent_agent_id=payload.parent_agent_id,
                allowed_tools=payload.allowed_tools,
            )
        except ValueError as exc:
            status_code = 404 if "Run" in str(exc) or "Unknown parent" in str(exc) else 409
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/tree")
    def get_hierarchy(run_id: str) -> dict[str, Any]:
        try:
            return service.get_hierarchy(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/supervise")
    def supervise_run(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            agent_ids = payload.get("agent_ids", [])
            tasks = payload.get("tasks", {})
            if not isinstance(agent_ids, list) or not all(isinstance(item, str) for item in agent_ids):
                raise ValueError("agent_ids must be an array of strings")
            if not isinstance(tasks, dict) or not all(isinstance(value, str) for value in tasks.values()):
                raise ValueError("tasks must map agent IDs to task strings")
            return supervisor.launch(run_id, agent_ids, tasks)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/agents/{agent_id}")
    def get_agent_status(run_id: str, agent_id: str) -> dict[str, Any]:
        agent = database.get_agent(run_id, agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' was not found")
        return agent

    @app.post("/runs/{run_id}/agents/{agent_id}/stop")
    def stop_agent(run_id: str, agent_id: str) -> dict[str, Any]:
        try:
            return supervisor.stop_agent(run_id, agent_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/monitor")
    def monitor_run(run_id: str) -> dict[str, Any]:
        try:
            return supervisor.monitor_run(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/cleanup")
    def cleanup_run(run_id: str) -> dict[str, Any]:
        try:
            return supervisor.cleanup_run(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/gateway/credentials")
    def issue_gateway_credential(run_id: str, payload: dict[str, str]) -> dict[str, Any]:
        agent_id = payload.get("agent_id", "")
        try:
            return gateway.issue_credential(run_id, agent_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/gateway/execute")
    def execute_gateway_tool(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = payload.get("agent_id")
        credential = payload.get("credential")
        tool_name = payload.get("tool")
        arguments = payload.get("arguments", {})
        origin = payload.get("origin", "STANDARD")
        idempotency_key = payload.get("idempotency_key")

        try:
            return gateway.execute(run_id, agent_id, credential, tool_name, arguments, origin, idempotency_key)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            status_code = 401 if "credential" in str(exc).lower() else 400
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/branches/{branch_id}/stop")
    def stop_branch(run_id: str, branch_id: str) -> dict[str, Any]:
        try:
            branch_members = gateway.revoke_branch(run_id, branch_id)
            for agent_id in branch_members:
                try:
                    supervisor.stop_agent(run_id, agent_id)
                except ValueError:
                    pass
            return {"run_id": run_id, "branch_id": branch_id, "status": "STOPPED", "agents": branch_members}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/branches/{branch_id}/complete")
    def complete_demo_branch(run_id: str, branch_id: str) -> dict[str, Any]:
        try:
            return staging.mark_ready_to_commit(
                run_id, branch_id, verified_completion=True, origin="OPERATOR"
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/branches/{branch_id}/commit")
    def commit_demo_branch(run_id: str, branch_id: str) -> dict[str, Any]:
        try:
            return staging.commit_branch(run_id, branch_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/bedrock/delegate")
    def delegate_with_bedrock(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        parent_agent_id = payload.get("parent_agent_id")
        customer_request = payload.get("customer_request", "")
        try:
            result = bedrock.delegate(run_id, parent_agent_id, customer_request)
            origin = "MODEL" if bedrock._aws_ready else "CONTROLLED_TEST"
            gateway.record_event(run_id, parent_agent_id, "bedrock.delegate", "ALLOW", None, origin)
            result["origin"] = origin
            return result
        except ValueError as exc:
            status_code = 400 if "Unsupported delegated role" in str(exc) else 404
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/agents/{agent_id}/model/converse")
    def converse_for_agent(
        run_id: str,
        agent_id: str,
        payload: dict[str, Any],
        authorization: Optional[str] = Header(default=None),
    ) -> dict[str, Any]:
        scheme, _, credential = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not credential:
            raise HTTPException(status_code=401, detail="Missing agent credentials")
        try:
            agent = gateway.authenticate_agent(run_id, agent_id, credential)
            messages = payload.get("messages")
            if not isinstance(messages, list) or not messages:
                raise ValueError("messages must be a non-empty array")
            result = bedrock.converse_agent(agent["role"], messages)
            gateway.record_event(run_id, agent_id, "bedrock.converse", "ALLOW", None, "MODEL")
            return result
        except PermissionError as exc:
            gateway.record_event(run_id, agent_id, "bedrock.converse", "DENY", "INVALID_CREDENTIAL", "MODEL")
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/agents/{agent_id}/complete")
    def complete_worker_task(
        run_id: str,
        agent_id: str,
        authorization: Optional[str] = Header(default=None),
    ) -> dict[str, Any]:
        scheme, _, credential = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not credential:
            raise HTTPException(status_code=401, detail="Missing agent credentials")
        try:
            gateway.authenticate_agent(run_id, agent_id, credential)
            supervisor.verify_worker_completion(run_id, agent_id)
            return staging.mark_ready_to_commit(
                run_id, agent_id, verified_completion=True, origin="SUPERVISOR"
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/events")
    def get_run_events(run_id: str, after_seq: int = Query(default=0, ge=0)) -> dict[str, Any]:
        try:
            return {"run_id": run_id, "events": gateway.get_events(run_id, after_seq)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/events/stream")
    def stream_run_events(run_id: str, after_seq: int = Query(default=0, ge=0)):
        def event_generator():
            yield "event: connected\n"
            yield f"data: {json.dumps({'run_id': run_id, 'type': 'connected', 'after_seq': after_seq})}\n\n"
            for event in gateway.get_events(run_id, after_seq):
                yield "event: message\n"
                yield f"id: {event['event_seq']}\n"
                yield f"data: {json.dumps(event)}\n\n"
            yield "event: heartbeat\n"
            yield f"data: {json.dumps({'run_id': run_id, 'type': 'heartbeat'})}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.get("/runs/{run_id}/dashboard")
    def get_dashboard(run_id: str) -> dict[str, Any]:
        try:
            return {
                "run_id": run_id,
                "hierarchy": service.get_hierarchy(run_id),
                "events": gateway.get_events(run_id),
                "effects": staging.get_effects(run_id),
                "business_state": staging.get_business_state(run_id),
            }
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/demo/reset")
    def reset_demo(run_id: str) -> dict[str, Any]:
        try:
            return gateway.reset_demo(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/demo/state")
    def get_demo_state(run_id: str) -> dict[str, Any]:
        try:
            return gateway.get_demo_state(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/effects")
    def get_effects(run_id: str) -> dict[str, Any]:
        try:
            return {
                **staging.get_effects(run_id),
                "business_state": staging.get_business_state(run_id),
            }
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/aws/status")
    def get_aws_status(run_id: str) -> dict[str, Any]:
        try:
            return observability.status(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/runs/{run_id}/aws/export")
    def export_aws_events(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            events = payload.get("events", [])
            return observability.export_events(run_id, events)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/runs/{run_id}/aws/events")
    def get_aws_events(run_id: str) -> dict[str, Any]:
        try:
            return {"run_id": run_id, "records": observability.get_events(run_id)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


app = build_app()
