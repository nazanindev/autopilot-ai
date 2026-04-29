"""Langfuse observability wrapper + local logging."""
import os
from typing import Optional
from datetime import datetime, UTC


def _client():
    """Lazy Langfuse client — returns None if keys not configured."""
    pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sk = os.getenv("LANGFUSE_SECRET_KEY", "")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    if not pk or not sk:
        return None
    try:
        from langfuse import Langfuse
        return Langfuse(public_key=pk, secret_key=sk, host=host)
    except Exception:
        return None


def trace_session(
    session_id: str,
    run_id: str,
    project: str,
    branch: str,
    phase: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    context_tokens: int = 0,
    duration_s: float = 0.0,
    metadata: Optional[dict] = None,
) -> None:
    lf = _client()
    if not lf:
        return
    try:
        trace = lf.trace(
            id=session_id,
            name=f"session:{phase}",
            user_id=project,
            session_id=run_id,
            tags=[project, phase, branch],
            metadata={
                "run_id": run_id,
                "project": project,
                "branch": branch,
                "phase": phase,
                "model": model,
                "context_tokens": context_tokens,
                "duration_s": duration_s,
                **(metadata or {}),
            },
        )
        trace.generation(
            name="claude-session",
            model=model,
            usage={
                "input": tokens_in,
                "output": tokens_out,
                "total": tokens_in + tokens_out,
            },
            metadata={"cost_usd": cost_usd},
        )
        lf.flush()
    except Exception:
        pass


def trace_subagent(
    session_id: str,
    run_id: str,
    project: str,
    phase: str,
    allowed: bool,
    block_reason: str = "",
) -> None:
    lf = _client()
    if not lf:
        return
    try:
        lf.event(
            trace_id=session_id,
            name="subagent_spawn",
            metadata={
                "run_id": run_id,
                "project": project,
                "phase": phase,
                "allowed": allowed,
                "block_reason": block_reason,
            },
        )
        lf.flush()
    except Exception:
        pass


def trace_run_event(
    run_id: str,
    project: str,
    event: str,
    metadata: Optional[dict] = None,
) -> None:
    lf = _client()
    if not lf:
        return
    try:
        lf.event(
            trace_id=run_id,
            name=event,
            metadata={"project": project, **(metadata or {})},
        )
        lf.flush()
    except Exception:
        pass
