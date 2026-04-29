"""Context injection — builds session briefing from RunState (not chat history)."""
from autopilot.tracker import RunState


def build_briefing(run: RunState) -> str:
    """Compact structured briefing injected at the start of each Claude session."""
    artifacts_str = "\n".join(f"  - {a}" for a in run.artifacts) or "  (none yet)"
    decisions_str = "\n".join(f"  - {d}" for d in run.decisions) or "  (none yet)"

    return f"""## AUTOPILOT SESSION BRIEFING
> This is a structured run context, not a chat history. Do not reference prior conversation.

**Run ID:** {run.run_id}
**Goal:** {run.goal}
**Phase:** {run.phase.value.upper()} (step {run.current_step}/{run.max_steps})
**Status:** {run.status.value}
**Cost so far:** ${run.cost_usd:.4f}

**Artifacts:**
{artifacts_str}

**Key decisions:**
{decisions_str}

**Context summary:**
{run.context_summary or "(no prior summary — this is the first session for this run)"}

---
Continue from the current phase. Do not re-litigate decisions already recorded above.
"""


def summarize_for_new_session(run: RunState, anthropic_client) -> str:
    """Ask Haiku to compress the run state into a tight context summary."""
    prompt = f"""Compress this run state into a tight context summary (max 300 words).
Preserve: goal, plan steps, key decisions, artifacts created, current status.
Discard: conversational detail, repeated information.

Run ID: {run.run_id}
Goal: {run.goal}
Phase: {run.phase.value} step {run.current_step}/{run.max_steps}
Artifacts: {run.artifacts}
Decisions: {run.decisions}
Existing summary: {run.context_summary}
"""
    try:
        resp = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception:
        return run.context_summary
