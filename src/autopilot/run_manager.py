"""RunState lifecycle: create, update, phase transitions."""
import anthropic
import os

from autopilot.tracker import RunState, Phase, RunStatus, save_run, load_run, load_active_run
from autopilot.context import build_briefing, summarize_for_new_session
from autopilot.observe import trace_run_event
from autopilot.config import get_project_id, get_branch


def _anthropic():
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))


def create_run(goal: str) -> RunState:
    run = RunState(
        goal=goal,
        project=get_project_id(),
        branch=get_branch(),
    )
    save_run(run)
    trace_run_event(run.run_id, run.project, "run_created", {"goal": goal})
    return run


def advance_phase(run: RunState, new_phase: Phase) -> RunState:
    run.phase = new_phase
    run.current_step = 0
    save_run(run)
    trace_run_event(run.run_id, run.project, f"phase:{new_phase.value}")
    return run


def add_artifact(run: RunState, artifact: str) -> RunState:
    if artifact not in run.artifacts:
        run.artifacts.append(artifact)
    save_run(run)
    return run


def add_decision(run: RunState, decision: str) -> RunState:
    run.decisions.append(decision)
    save_run(run)
    return run


def set_plan_steps(run: RunState, steps: list) -> RunState:
    """Replace plan steps (called when ExitPlanMode fires)."""
    run.plan_steps = steps
    save_run(run)
    trace_run_event(run.run_id, run.project, "plan_set", {"step_count": len(steps)})
    return run


def complete_plan_step(run: RunState, step_id: str) -> RunState:
    """Mark a single plan step as done."""
    for step in run.plan_steps:
        if step.get("id") == step_id:
            step["status"] = "done"
            break
    save_run(run)
    return run


def complete_run(run: RunState) -> RunState:
    run.status = RunStatus.complete
    save_run(run)
    trace_run_event(run.run_id, run.project, "run_complete", {"cost_usd": run.cost_usd})
    return run


def refresh_context_summary(run: RunState) -> RunState:
    """Compress run state into a tight context summary using Haiku."""
    run.context_summary = summarize_for_new_session(run, _anthropic())
    save_run(run)
    return run


def get_or_create_run(project: str, goal: str = "") -> RunState:
    run = load_active_run(project)
    if run:
        return run
    if not goal:
        raise ValueError("No active run and no goal provided")
    return create_run(goal)


def get_session_briefing(run: RunState) -> str:
    return build_briefing(run)
