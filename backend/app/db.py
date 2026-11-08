import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.app.services.demo_policy import CUSTOMER_ID, ORDER_ID


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
                    exit_code INTEGER,
                    PRIMARY KEY (run_id, agent_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
                """
            )
            agent_columns = {row[1] for row in connection.execute("PRAGMA table_info(agents)")}
            if "exit_code" not in agent_columns:
                connection.execute("ALTER TABLE agents ADD COLUMN exit_code INTEGER")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS branches (
                    run_id TEXT NOT NULL,
                    branch_id TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'RUNNING',
                    violation_count INTEGER NOT NULL DEFAULT 0,
                    completed_at TEXT,
                    committed_at TEXT,
                    aborted_at TEXT,
                    PRIMARY KEY (run_id, branch_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    token_hash TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    branch_id TEXT NOT NULL,
                    origin TEXT NOT NULL DEFAULT 'CONTROLLED_TEST',
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY (run_id, agent_id) REFERENCES agents(run_id, agent_id),
                    FOREIGN KEY (run_id, branch_id) REFERENCES branches(run_id, branch_id)
                )
                """
            )
            session_columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_sessions)")}
            if "origin" not in session_columns:
                connection.execute(
                    "ALTER TABLE agent_sessions ADD COLUMN origin TEXT NOT NULL DEFAULT 'CONTROLLED_TEST'"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS business_accounts (
                    run_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    promo_credit_cents INTEGER NOT NULL DEFAULT 0,
                    version INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (run_id, customer_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS business_orders (
                    run_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    paid_cents INTEGER NOT NULL,
                    refunded_cents INTEGER NOT NULL DEFAULT 0,
                    version INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'PAID',
                    PRIMARY KEY (run_id, order_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS journal (
                    action_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    branch_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    tool TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    base_version INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'STAGED',
                    idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (run_id, branch_id, sequence),
                    UNIQUE (run_id, idempotency_key),
                    FOREIGN KEY (run_id, branch_id) REFERENCES branches(run_id, branch_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    branch_id TEXT,
                    agent_id TEXT,
                    origin TEXT NOT NULL,
                    type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                )
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (1, ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )

    def create_demo_fixtures(self, run_id: str) -> None:
        """Create stable business fixtures for a run without overwriting state."""
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO business_accounts
                   (run_id, customer_id, promo_credit_cents, version, notes)
                   VALUES (?, ?, 0, 0, ?)""",
                (run_id, CUSTOMER_ID, "Loyalty promotion review"),
            )
            connection.execute(
                """INSERT OR IGNORE INTO business_orders
                   (run_id, order_id, customer_id, paid_cents, refunded_cents, version, status)
                   VALUES (?, ?, ?, 4500, 0, 0, 'PAID')""",
                (run_id, ORDER_ID, CUSTOMER_ID),
            )
            connection.execute(
                """INSERT OR IGNORE INTO branches (run_id, branch_id, state)
                   VALUES (?, 'order-agent', 'RUNNING'), (?, 'account-agent', 'RUNNING')""",
                (run_id, run_id),
            )

    def reset_demo_fixtures(self, run_id: str) -> None:
        """Reset only transactional demo data for a run."""
        with self._connect() as connection:
            connection.execute("DELETE FROM audit_events WHERE run_id = ?", (run_id,))
            connection.execute("DELETE FROM journal WHERE run_id = ?", (run_id,))
            connection.execute("DELETE FROM branches WHERE run_id = ?", (run_id,))
            connection.execute("DELETE FROM business_orders WHERE run_id = ?", (run_id,))
            connection.execute("DELETE FROM business_accounts WHERE run_id = ?", (run_id,))
        self.create_demo_fixtures(run_id)

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
        parent = self.get_agent(run_id, parent_agent_id) if parent_agent_id else None
        branch_id = agent_id if parent is None or parent.get("parent_agent_id") is None else parent["branch_id"]
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
            if branch_id == agent_id:
                connection.execute(
                    "INSERT OR IGNORE INTO branches (run_id, branch_id, state) VALUES (?, ?, 'RUNNING')",
                    (run_id, branch_id),
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
        exit_code: Optional[int] = None,
        reset_exit_code: bool = False,
        stopped_at: Optional[str] = None,
        clear_stopped_at: bool = False,
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
        if reset_exit_code:
            values.append("exit_code = NULL")
        elif exit_code is not None:
            values.append("exit_code = ?")
            params.append(exit_code)
        if clear_stopped_at:
            values.append("stopped_at = NULL")
        elif stopped_at is not None:
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
            "exit_code": row[12] if len(row) > 12 else None,
        }
