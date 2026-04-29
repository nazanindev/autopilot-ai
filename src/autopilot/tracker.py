"""DuckDB-backed store for RunState, sessions, and subagent events."""
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import duckdb

from autopilot.config import DB_PATH


class Phase(str, Enum):
    clarify = "clarify"
    plan = "plan"
    execute = "execute"
    verify = "verify"
    ship = "ship"


class RunStatus(str, Enum):
    active = "active"
    blocked = "blocked"
    complete = "complete"
    failed = "failed"


@dataclass
class RunState:
    goal: str
    project: str
    branch: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    phase: Phase = Phase.clarify
    current_step: int = 0
    max_steps: int = 20
    artifacts: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    plan_steps: list = field(default_factory=list)  # [{"id": "1", "description": "...", "status": "pending|done|skipped"}]
    status: RunStatus = RunStatus.active
    context_summary: str = ""
    cost_usd: float = 0.0
    model: str = "claude-sonnet-4-6"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Weighted step budget: accumulates fractional costs per tool type.
    step_budget_used: float = 0.0
    # PR URL written by `ap ship` once the PR is created.
    pr_url: str = ""


def _conn() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH))


def init_db() -> None:
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id VARCHAR PRIMARY KEY,
                project VARCHAR,
                branch VARCHAR,
                goal TEXT,
                phase VARCHAR,
                current_step INTEGER,
                max_steps INTEGER,
                artifacts JSON,
                decisions JSON,
                plan_steps JSON,
                status VARCHAR,
                context_summary TEXT,
                cost_usd DOUBLE,
                model VARCHAR,
                created_at VARCHAR,
                updated_at VARCHAR,
                step_budget_used DOUBLE,
                pr_url VARCHAR
            )
        """)
        # Migrations for columns added after initial schema
        for migration in [
            "ALTER TABLE runs ADD COLUMN IF NOT EXISTS plan_steps JSON",
            "ALTER TABLE runs ADD COLUMN IF NOT EXISTS step_budget_used DOUBLE DEFAULT 0.0",
            "ALTER TABLE runs ADD COLUMN IF NOT EXISTS pr_url VARCHAR DEFAULT ''",
        ]:
            try:
                con.execute(migration)
            except Exception:
                pass
        con.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id VARCHAR PRIMARY KEY,
                run_id VARCHAR,
                project VARCHAR,
                branch VARCHAR,
                phase VARCHAR,
                model VARCHAR,
                tokens_in INTEGER,
                tokens_out INTEGER,
                cost_usd DOUBLE,
                context_tokens INTEGER,
                duration_s DOUBLE,
                created_at VARCHAR
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS subagent_spawns (
                id VARCHAR PRIMARY KEY,
                session_id VARCHAR,
                run_id VARCHAR,
                project VARCHAR,
                phase VARCHAR,
                description TEXT,
                allowed BOOLEAN,
                block_reason VARCHAR,
                created_at VARCHAR
            )
        """)


def save_run(run: RunState) -> None:
    run.updated_at = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute("""
            INSERT OR REPLACE INTO runs (
                run_id, project, branch, goal,
                phase, current_step, max_steps,
                artifacts, decisions, plan_steps,
                status, context_summary, cost_usd,
                model, created_at, updated_at,
                step_budget_used, pr_url
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, [
            run.run_id, run.project, run.branch, run.goal,
            run.phase.value, run.current_step, run.max_steps,
            json.dumps(run.artifacts), json.dumps(run.decisions),
            json.dumps(run.plan_steps),
            run.status.value, run.context_summary, run.cost_usd,
            run.model, run.created_at, run.updated_at,
            run.step_budget_used, run.pr_url,
        ])


def load_run(run_id: str) -> Optional[RunState]:
    cols = ["run_id", "project", "branch", "goal", "phase", "current_step", "max_steps",
            "artifacts", "decisions", "plan_steps", "status", "context_summary", "cost_usd",
            "model", "created_at", "updated_at", "step_budget_used", "pr_url"]
    with _conn() as con:
        row = con.execute(
            f"SELECT {', '.join(cols)} FROM runs WHERE run_id = ?", [run_id]
        ).fetchone()
    if not row:
        return None
    d = dict(zip(cols, row))
    d["artifacts"] = json.loads(d["artifacts"] or "[]")
    d["decisions"] = json.loads(d["decisions"] or "[]")
    d["plan_steps"] = json.loads(d["plan_steps"] or "[]")
    d["phase"] = Phase(d["phase"])
    d["status"] = RunStatus(d["status"])
    d["step_budget_used"] = float(d["step_budget_used"] or 0.0)
    d["pr_url"] = d["pr_url"] or ""
    return RunState(**{k: v for k, v in d.items() if k in RunState.__dataclass_fields__})


def load_active_run(project: str) -> Optional[RunState]:
    with _conn() as con:
        row = con.execute("""
            SELECT run_id FROM runs
            WHERE project = ? AND status = 'active'
            ORDER BY updated_at DESC LIMIT 1
        """, [project]).fetchone()
    return load_run(row[0]) if row else None


def save_session(
    session_id: str, run_id: str, project: str, branch: str, phase: str,
    model: str, tokens_in: int, tokens_out: int, cost_usd: float,
    context_tokens: int = 0, duration_s: float = 0.0,
) -> None:
    with _conn() as con:
        con.execute("""
            INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, [
            session_id, run_id, project, branch, phase, model,
            tokens_in, tokens_out, cost_usd, context_tokens, duration_s,
            datetime.now(timezone.utc).isoformat(),
        ])


def save_subagent_event(
    session_id: str, run_id: str, project: str, phase: str,
    description: str, allowed: bool, block_reason: str = "",
) -> None:
    with _conn() as con:
        con.execute("""
            INSERT INTO subagent_spawns VALUES (?,?,?,?,?,?,?,?,?)
        """, [
            str(uuid.uuid4()), session_id, run_id, project, phase,
            description, allowed, block_reason, datetime.now(timezone.utc).isoformat(),
        ])


def get_cost_today(project: Optional[str] = None) -> float:
    with _conn() as con:
        if project:
            row = con.execute("""
                SELECT COALESCE(SUM(cost_usd), 0) FROM sessions
                WHERE project = ? AND created_at >= current_date::VARCHAR
            """, [project]).fetchone()
        else:
            row = con.execute("""
                SELECT COALESCE(SUM(cost_usd), 0) FROM sessions
                WHERE created_at >= current_date::VARCHAR
            """).fetchone()
    return row[0] if row else 0.0


def get_project_stats() -> list:
    with _conn() as con:
        rows = con.execute("""
            SELECT project,
                   COUNT(*) as sessions,
                   SUM(cost_usd) as total_cost,
                   SUM(tokens_in + tokens_out) as total_tokens,
                   MAX(created_at) as last_active
            FROM sessions
            GROUP BY project
            ORDER BY total_cost DESC
        """).fetchall()
    cols = ["project", "sessions", "total_cost", "total_tokens", "last_active"]
    return [dict(zip(cols, r)) for r in rows]


def get_cost_per_pr(project: Optional[str] = None) -> list:
    """Return cost + step stats for all shipped runs that have a PR URL."""
    with _conn() as con:
        if project:
            rows = con.execute("""
                SELECT run_id, goal, pr_url, cost_usd, step_budget_used, updated_at
                FROM runs WHERE pr_url != '' AND pr_url IS NOT NULL AND project = ?
                ORDER BY updated_at DESC
            """, [project]).fetchall()
        else:
            rows = con.execute("""
                SELECT run_id, goal, pr_url, cost_usd, step_budget_used, updated_at
                FROM runs WHERE pr_url != '' AND pr_url IS NOT NULL
                ORDER BY updated_at DESC
            """).fetchall()
    cols = ["run_id", "goal", "pr_url", "cost_usd", "step_budget_used", "updated_at"]
    return [dict(zip(cols, r)) for r in rows]


def get_recent_runs(project: Optional[str] = None, limit: int = 10) -> list:
    with _conn() as con:
        if project:
            rows = con.execute("""
                SELECT run_id, goal, phase, status, cost_usd, updated_at
                FROM runs WHERE project = ?
                ORDER BY updated_at DESC LIMIT ?
            """, [project, limit]).fetchall()
        else:
            rows = con.execute("""
                SELECT run_id, goal, phase, status, cost_usd, updated_at
                FROM runs ORDER BY updated_at DESC LIMIT ?
            """, [limit]).fetchall()
    cols = ["run_id", "goal", "phase", "status", "cost_usd", "updated_at"]
    return [dict(zip(cols, r)) for r in rows]
