import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psutil

from backend.app.services.demo_policy import EventOrigin


class SupervisorService:
    def __init__(self, database):
        self.database = database
        self.gateway = None
        self.processes: dict[str, dict[str, Any]] = {}

    def _process_alive(self, pid: int) -> bool:
        try:
            proc = psutil.Process(pid)
            return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def launch(self, run_id: str, agent_ids: list[str], tasks: Optional[dict[str, str]] = None) -> dict[str, Any]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")

        started: list[dict[str, Any]] = []
        tasks = tasks or {}
        unknown_task_agents = set(tasks) - set(agent_ids)
        if unknown_task_agents:
            raise ValueError(f"Tasks reference agents that are not being launched: {sorted(unknown_task_agents)}")
        for agent_id in agent_ids:
            agent = self.database.get_agent(run_id, agent_id)
            if agent is None:
                raise ValueError(f"Agent '{agent_id}' does not exist in run '{run_id}'")
            with self.database._connect() as connection:
                branch = connection.execute(
                    "SELECT state FROM branches WHERE run_id = ? AND branch_id = ?",
                    (run_id, agent["branch_id"]),
                ).fetchone()
            if branch is None or branch[0] != "RUNNING":
                raise ValueError(f"Branch '{agent['branch_id']}' is not launchable")

            task = tasks.get(agent_id)
            credential = None
            if task:
                if agent["role"] not in {"order", "account"}:
                    raise ValueError("Only predefined child roles can receive model tasks")
                if self.gateway is None:
                    raise RuntimeError("Gateway is not configured for worker launch")
                credential = self.gateway.issue_credential(
                    run_id, agent_id, origin=EventOrigin.MODEL.value
                )["credential"]
            process, worker_ready = self._spawn_agent_process(run_id, agent, task, credential)
            self.processes.setdefault(run_id, {})[agent_id] = process
            timestamp = datetime.fromtimestamp(
                psutil.Process(process.pid).create_time(), timezone.utc
            ).isoformat()
            self.database.update_agent_state(
                run_id=run_id,
                agent_id=agent_id,
                status="RUNNING",
                task_state="WAITING_FOR_INSTRUCTION",
                pid=process.pid,
                process_create_time=timestamp,
                reset_exit_code=True,
                clear_stopped_at=True,
            )
            started.append({
                "agent_id": agent_id,
                "role": agent["role"],
                "pid": process.pid,
                "status": "RUNNING",
                "process_create_time": timestamp,
                "worker_ready": worker_ready,
            })

        return {"run_id": run_id, "started": started}

    def stop_agent(self, run_id: str, agent_id: str) -> dict[str, Any]:
        agent = self.database.get_agent(run_id, agent_id)
        if agent is None:
            raise ValueError(f"Agent '{agent_id}' does not exist in run '{run_id}'")

        pid = agent.get("pid")
        process = self.processes.get(run_id, {}).get(agent_id)

        if pid is not None:
            self.database.update_agent_state(run_id, agent_id, status="STOPPING")

        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                pass

        if pid is not None:
            try:
                proc = psutil.Process(pid)
                if self._process_alive(pid):
                    proc.terminate()
                    proc.wait(timeout=5)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if pid is not None:
            try:
                proc = psutil.Process(pid)
                if self._process_alive(pid):
                    proc.kill()
                    proc.wait(timeout=5)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if pid is not None and self._process_alive(pid):
            self.database.update_agent_state(run_id, agent_id, status="FAILED")
            raise ValueError(f"Unable to terminate agent '{agent_id}'")

        exit_code = process.returncode if process is not None else None

        self.database.update_agent_state(
            run_id=run_id,
            agent_id=agent_id,
            status="STOPPED",
            exit_code=exit_code,
            stopped_at=datetime.now(timezone.utc).isoformat(),
        )
        self.processes.get(run_id, {}).pop(agent_id, None)
        return {"run_id": run_id, "agent_id": agent_id, "status": "STOPPED", "pid": pid}

    def verify_worker_completion(self, run_id: str, agent_id: str) -> dict[str, Any]:
        """Accept completion only from an authenticated, live managed worker."""
        agent = self.database.get_agent(run_id, agent_id)
        if agent is None:
            raise ValueError(f"Agent '{agent_id}' does not exist in run '{run_id}'")
        process = self.processes.get(run_id, {}).get(agent_id)
        if process is None or process.poll() is not None or agent["status"] != "RUNNING":
            raise ValueError("Managed worker is not running")
        if agent["role"] not in {"order", "account"}:
            raise ValueError("Only child workers can complete a business task")
        updated = self.database.update_agent_state(
            run_id, agent_id, task_state="COMPLETED"
        )
        return {"run_id": run_id, "agent_id": agent_id, "task_state": updated["task_state"]}

    def monitor_run(self, run_id: str) -> dict[str, Any]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")

        updated_agents: list[dict[str, Any]] = []
        for agent in self.database.get_agents_for_run(run_id):
            agent_id = agent["agent_id"]
            status = agent["status"]
            pid = agent.get("pid")

            if status == "STOPPED":
                updated_agents.append(agent)
                continue

            if pid is None:
                status = "FAILED"
            else:
                status = "RUNNING" if self._process_alive(pid) else "FAILED"

            if status != agent["status"]:
                self.database.update_agent_state(
                    run_id=run_id,
                    agent_id=agent_id,
                    status=status,
                    stopped_at=datetime.now(timezone.utc).isoformat() if status == "FAILED" else None,
                    clear_stopped_at=status == "RUNNING",
                )

            updated_agents.append(self.database.get_agent(run_id, agent_id))

        return {"run_id": run_id, "agents": updated_agents}

    def cleanup_run(self, run_id: str) -> dict[str, Any]:
        if not self.database.run_exists(run_id):
            raise ValueError(f"Run '{run_id}' does not exist")

        agents = self.database.get_agents_for_run(run_id)
        for agent in agents:
            if agent["status"] in {"STOPPED", "FAILED"}:
                continue
            try:
                self.stop_agent(run_id, agent["agent_id"])
            except ValueError:
                pass

        self.processes.pop(run_id, None)
        return {"run_id": run_id, "status": "CLEANED"}

    def _spawn_agent_process(
        self,
        run_id: str,
        agent: dict[str, Any],
        task: str | None = None,
        credential: str | None = None,
    ) -> tuple[subprocess.Popen, dict[str, Any]]:
        worker_path = Path(__file__).resolve().parents[3] / "agents" / "worker.py"
        command = [
            sys.executable,
            str(worker_path),
            "--run-id", run_id,
            "--agent-id", agent["agent_id"],
            "--role", agent["role"],
        ]
        worker_env = {key: value for key, value in os.environ.items() if not key.startswith("AWS_")}
        if task and credential:
            worker_env["AGENTTREE_TASK"] = task
            worker_env["AGENTTREE_CREDENTIAL"] = credential
            worker_env["AGENTTREE_BASE_URL"] = os.getenv("AGENTTREE_BASE_URL", "http://127.0.0.1:8000")
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=worker_env,
            start_new_session=True,
        )
        try:
            ready_line = process.stdout.readline() if process.stdout is not None else ""
            ready = json.loads(ready_line)
            if (
                ready.get("type") != "WORKER_READY"
                or ready.get("run_id") != run_id
                or ready.get("agent_id") != agent["agent_id"]
                or ready.get("role") != agent["role"]
                or ready.get("pid") != process.pid
            ):
                raise RuntimeError("Worker startup identity did not match the supervisor assignment")
        except Exception:
            process.terminate()
            process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
            raise
        if process.stdout is not None:
            process.stdout.close()
        return process, ready
