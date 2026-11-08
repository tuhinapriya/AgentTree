import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class AgentTreeDB:
    def __init__(self, database_path: Optional[str] = None):
        self.database_path = database_path or str(Path(__file__).resolve().parents[1] / "agenttree.db")
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    scenario TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'CREATED',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    parent_agent_id TEXT,
                    branch_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'CREATED',
                    task_state TEXT NOT NULL DEFAULT 'DELEGATING',
                    pid INTEGER,
                    process_create_time TEXT,
                    allowed_tools TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    stopped_at TEXT,
                    PRIMARY KEY (run_id, agent_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
                """
            )

    def create_run(self, run_id: str, scenario: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO runs (run_id, scenario, status) VALUES (?, ?, 'CREATED')",
                (run_id, scenario),
            )

    def run_exists(self, run_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            return row is not None

    def create_agent(
        self,
        run_id: str,
        agent_id: str,
        parent_agent_id: Optional[str],
        role: str,
        allowed_tools: list[str],
        status: str = "CREATED",
        task_state: str = "DELEGATING",
        pid: Optional[int] = None,
        process_create_time: Optional[str] = None,
        started_at: Optional[str] = None,
        stopped_at: Optional[str] = None,
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        branch_id = parent_agent_id or agent_id
        started_at = started_at or timestamp
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agents (
                    agent_id,
                    run_id,
                    parent_agent_id,
                    branch_id,
                    role,
                    status,
                    task_state,
                    pid,
                    process_create_time,
                    allowed_tools,
                    started_at,
                    stopped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    run_id,
                    parent_agent_id,
                    branch_id,
                    role,
                    status,
                    task_state,
                    pid,
                    process_create_time,
                    ",".join(allowed_tools),
                    started_at,
                    stopped_at,
                ),
            )

    def get_agent(self, run_id: str, agent_id: str):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agents WHERE run_id = ? AND agent_id = ?",
                (run_id, agent_id),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_agent(row)

    def update_agent_state(
        self,
        run_id: str,
        agent_id: str,
        status: Optional[str] = None,
        task_state: Optional[str] = None,
        pid: Optional[int] = None,
        process_create_time: Optional[str] = None,
        stopped_at: Optional[str] = None,
    ) -> dict:
        values: list[str] = []
        params: list[object] = []

        if status is not None:
            values.append("status = ?")
            params.append(status)
        if task_state is not None:
            values.append("task_state = ?")
            params.append(task_state)
        if pid is not None:
            values.append("pid = ?")
            params.append(pid)
        if process_create_time is not None:
            values.append("process_create_time = ?")
            params.append(process_create_time)
        if stopped_at is not None:
            values.append("stopped_at = ?")
            params.append(stopped_at)

        if not values:
            return self.get_agent(run_id, agent_id)

        params.extend([run_id, agent_id])
        sql = f"UPDATE agents SET {', '.join(values)} WHERE run_id = ? AND agent_id = ?"
        with self._connect() as connection:
            connection.execute(sql, tuple(params))

        return self.get_agent(run_id, agent_id)

    def get_agents_for_run(self, run_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agents WHERE run_id = ? ORDER BY started_at ASC",
                (run_id,),
            ).fetchall()
            return [self._row_to_agent(row) for row in rows]

    def agent_exists_in_run(self, run_id: str, agent_id: str) -> bool:
        return self.get_agent(run_id, agent_id) is not None

    def get_parent_agent_id(self, run_id: str, agent_id: str) -> Optional[str]:
        agent = self.get_agent(run_id, agent_id)
        if agent is None:
            return None
        return agent.get("parent_agent_id")

    def _row_to_agent(self, row) -> dict:
        return {
            "agent_id": row[0],
            "run_id": row[1],
            "parent_agent_id": row[2],
            "branch_id": row[3],
            "role": row[4],
            "status": row[5],
            "task_state": row[6],
            "pid": row[7],
            "process_create_time": row[8],
            "allowed_tools": [item for item in (row[9].split(",") if row[9] else []) if item],
            "started_at": row[10],
            "stopped_at": row[11],
        }
