"""ap status and ap stats commands."""
import os

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from autopilot.tracker import init_db, get_cost_today, get_project_stats, get_recent_runs, load_active_run
from autopilot.config import get_project_id, constraints

console = Console()


def _budget_bar(used: float, total: float, width: int = 20) -> str:
    pct = min(used / total, 1.0) if total > 0 else 0
    filled = int(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    color = "red" if pct >= 0.9 else "yellow" if pct >= 0.6 else "green"
    return f"[{color}]{bar}[/{color}] {pct*100:.0f}%"


def cmd_status() -> None:
    init_db()
    project = get_project_id()
    today = get_cost_today()
    project_today = get_cost_today(project)
    run = load_active_run(project)
    c = constraints()
    budget_gate = float(os.getenv("AP_BUDGET_USD") or c.get("budget_gate_usd", 2.0))

    lines = [
        f"[bold]Project:[/bold] {project}",
        f"[bold]Today (this project):[/bold] ${project_today:.4f}  {_budget_bar(project_today, budget_gate)}  of ${budget_gate:.2f} budget",
        f"[bold]Today (all projects):[/bold] ${today:.4f}",
    ]
    if run:
        projected = None
        if run.current_step > 0:
            projected = run.cost_usd / run.current_step * run.max_steps

        lines += [
            "",
            f"[bold yellow]Active run:[/bold yellow] {run.run_id}",
            f"[bold]Goal:[/bold] {run.goal[:80]}",
            f"[bold]Phase:[/bold] {run.phase.value} | step {run.current_step}/{run.max_steps}",
            f"[bold]Run cost:[/bold] ${run.cost_usd:.4f}"
            + (f"  →  ~${projected:.4f} projected" if projected else ""),
        ]

        if run.plan_steps:
            done = sum(1 for s in run.plan_steps if s.get("status") == "done")
            total_steps = len(run.plan_steps)
            lines.append(f"[bold]Plan:[/bold] {done}/{total_steps} steps done")
            for s in run.plan_steps:
                marker = "[green]✓[/green]" if s.get("status") == "done" else "○"
                lines.append(f"  {marker} {s['description']}")
    else:
        lines.append("\n[dim]No active run.[/dim]")

    console.print(Panel("\n".join(lines), title="Autopilot Status", border_style="cyan"))


def cmd_stats(project_filter=None) -> None:
    init_db()

    # Per-project breakdown
    project_stats = get_project_stats()
    if not project_stats:
        console.print("[dim]No sessions recorded yet.[/dim]")
        return

    t = Table(title="Cost by project", show_lines=True)
    t.add_column("Project", style="cyan")
    t.add_column("Sessions", justify="right")
    t.add_column("Total cost", justify="right")
    t.add_column("Tokens", justify="right")
    t.add_column("Last active")

    for row in project_stats:
        if project_filter and project_filter.lower() not in row["project"].lower():
            continue
        t.add_row(
            row["project"],
            str(row["sessions"]),
            f"${row['total_cost']:.4f}",
            f"{int(row['total_tokens']):,}",
            row["last_active"][:10] if row["last_active"] else "—",
        )
    console.print(t)

    # Recent runs
    runs = get_recent_runs(project_filter, limit=10)
    if runs:
        r = Table(title="Recent runs", show_lines=True)
        r.add_column("Run ID", style="dim")
        r.add_column("Goal")
        r.add_column("Phase")
        r.add_column("Status")
        r.add_column("Cost", justify="right")
        r.add_column("Updated")

        status_colors = {"active": "green", "complete": "blue", "failed": "red", "blocked": "yellow"}
        for row in runs:
            color = status_colors.get(row["status"], "white")
            r.add_row(
                row["run_id"],
                row["goal"][:50],
                row["phase"],
                f"[{color}]{row['status']}[/{color}]",
                f"${row['cost_usd']:.4f}",
                row["updated_at"][:10] if row["updated_at"] else "—",
            )
        console.print(r)
