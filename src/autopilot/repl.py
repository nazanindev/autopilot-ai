"""
Autopilot REPL — persistent interactive session.
Manages run lifecycle, phase switching, and Claude Code subprocess launch.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from autopilot.config import get_project_id, get_branch, model_for_phase
from autopilot.router import MODEL_ALIASES, model_for
from autopilot.tracker import (
    Phase, RunStatus, init_db, load_active_run, save_run, get_cost_today
)
from autopilot.run_manager import (
    create_run, advance_phase, refresh_context_summary,
    add_artifact, add_decision, complete_run, get_session_briefing
)

console = Console()
HISTORY_PATH = Path.home() / ".autopilot" / "repl_history"
HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)


class AutopilotREPL:
    def __init__(self):
        self.project = get_project_id()
        self.branch = get_branch()
        self.run = None
        self.model_override = None  # type: Optional[str]
        self.no_agents = False
        self.session = PromptSession(
            history=FileHistory(str(HISTORY_PATH)),
            style=Style.from_dict({"prompt": "bold cyan"}),
        )

    # ── Prompt ────────────────────────────────────────────────────────────────

    def _prompt_str(self) -> str:
        parts = []
        if self.run:
            model = self.model_override or model_for(self.run.phase, self.run.goal)
            model_short = model.split("-")[1] if "-" in model else model
            phase = self.run.phase.value
            step = f"{self.run.current_step}/{self.run.max_steps}"
            cost = f"${self.run.cost_usd:.2f}"
            parts.append(f"{phase}:{model_short}|step:{step}|{cost}")
        else:
            parts.append(f"project:{self.project}")
        flags = []
        if self.no_agents:
            flags.append("no-agents")
        if flags:
            parts.append(",".join(flags))
        inner = " | ".join(parts)
        return f"ap [{inner}] > "

    # ── Slash commands ────────────────────────────────────────────────────────

    def handle_slash(self, cmd: str) -> bool:
        """Returns True if handled."""
        parts = cmd.strip().split(None, 1)
        verb = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if verb == "/plan":
            self._set_phase(Phase.plan)
        elif verb == "/exec":
            self._set_phase(Phase.execute)
        elif verb == "/fast":
            self._set_phase(Phase.execute)
            self.model_override = MODEL_ALIASES["haiku"]
            console.print("[dim]→ Fast mode: haiku[/dim]")
        elif verb == "/model":
            m = MODEL_ALIASES.get(arg.lower(), arg)
            self.model_override = m
            console.print(f"[dim]→ Model override: {m}[/dim]")
        elif verb == "/no-agents":
            self.no_agents = not self.no_agents
            state = "ON" if self.no_agents else "OFF"
            console.print(f"[dim]→ No-agents mode: {state}[/dim]")
            os.environ["AP_NO_SPAWN"] = "1" if self.no_agents else "0"
        elif verb == "/budget":
            os.environ["AP_BUDGET_USD"] = arg or "2.00"
            console.print(f"[dim]→ Budget set to ${os.environ['AP_BUDGET_USD']}[/dim]")
        elif verb == "/new":
            self._new_session()
        elif verb == "/compact":
            self._compact()
        elif verb == "/resume":
            self._resume(arg)
        elif verb == "/skip-plan":
            if self.run:
                advance_phase(self.run, Phase.execute)
                self.run.phase = Phase.execute
                console.print("[dim]→ Skipped planning phase → execute[/dim]")
        elif verb == "/status":
            self._show_status()
        elif verb == "/verify":
            self._run_verify()
        elif verb == "/ship":
            from autopilot.commands.ship import cmd_ship
            cmd_ship()
        elif verb == "/done":
            self._finish_run()
        elif verb in ("/quit", "/exit", "/q"):
            console.print("[dim]Goodbye.[/dim]")
            sys.exit(0)
        elif verb == "/help":
            self._show_help()
        else:
            console.print(f"[red]Unknown command: {verb}[/red]")
        return True

    def _set_phase(self, phase: Phase) -> None:
        if not self.run:
            console.print("[yellow]No active run. Start a task first.[/yellow]")
            return
        self.model_override = None
        advance_phase(self.run, phase)
        self.run.phase = phase
        model = model_for(phase, self.run.goal)
        console.print(f"[dim]→ Phase: {phase.value} | Model: {model}[/dim]")

    def _new_session(self) -> None:
        if not self.run:
            console.print("[yellow]No active run.[/yellow]")
            return
        console.print("[dim]Compressing context...[/dim]")
        refresh_context_summary(self.run)
        console.print("[green]✓ Context compressed. Next session will use RunState briefing.[/green]")

    def _compact(self) -> None:
        self._new_session()

    def _resume(self, run_id: str) -> None:
        from autopilot.tracker import load_run, get_recent_runs, RunStatus
        if run_id:
            r = load_run(run_id)
            if not r:
                console.print(f"[red]Run {run_id} not found.[/red]")
                return
            self.run = r
            console.print(f"[green]✓ Resumed run {run_id}: {r.goal}[/green]")
            return

        # No ID given — show picker of recent incomplete runs
        runs = [r for r in get_recent_runs(limit=10) if r["status"] != RunStatus.complete.value]
        if not runs:
            console.print("[yellow]No incomplete runs found.[/yellow]")
            return

        console.print("\n[bold]Recent incomplete runs:[/bold]")
        for i, r in enumerate(runs, 1):
            console.print(
                f"  [cyan]{i}.[/cyan] [{r['run_id']}] {r['goal'][:60]}  "
                f"[dim]{r['phase']} · ${r['cost_usd']:.4f}[/dim]"
            )

        try:
            choice = self.session.prompt("Pick a run (number or ID): ").strip()
        except (EOFError, KeyboardInterrupt):
            return

        if choice.isdigit() and 1 <= int(choice) <= len(runs):
            run_id = runs[int(choice) - 1]["run_id"]
        else:
            run_id = choice

        r = load_run(run_id)
        if not r:
            console.print(f"[red]Run {run_id} not found.[/red]")
            return
        self.run = r
        console.print(f"[green]✓ Resumed run {run_id}: {r.goal}[/green]")

    def _run_verify(self) -> None:
        from autopilot.commands.verify import run_checks
        passed, output = run_checks()
        if passed:
            console.print("[green]✓ Verification passed[/green]")
        else:
            console.print("[red]✗ Verification failed[/red]")
            console.print(f"[dim]{output[-1500:]}[/dim]")

    def _finish_run(self) -> None:
        if not self.run:
            return
        complete_run(self.run)
        console.print(f"[green]✓ Run {self.run.run_id} marked complete. Cost: ${self.run.cost_usd:.4f}[/green]")
        self.run = None

    def _show_status(self) -> None:
        today = get_cost_today(self.project)
        console.print(f"[bold]Project:[/bold] {self.project} | [bold]Today:[/bold] ${today:.4f}")
        if self.run:
            console.print(
                f"[bold]Run:[/bold] {self.run.run_id} | "
                f"[bold]Goal:[/bold] {self.run.goal[:60]} | "
                f"[bold]Phase:[/bold] {self.run.phase.value} | "
                f"[bold]Cost:[/bold] ${self.run.cost_usd:.4f}"
            )

    def _show_help(self) -> None:
        console.print(Panel(
            "[bold]Phase toggles:[/bold]\n"
            "  /plan          → Opus (planning)\n"
            "  /exec          → Sonnet (execution)\n"
            "  /fast          → Haiku (quick tasks)\n"
            "  /model <name>  → force model (opus/sonnet/haiku or full name)\n\n"
            "[bold]Context:[/bold]\n"
            "  /new           → compress context, start fresh session with RunState\n"
            "  /compact       → same as /new\n\n"
            "[bold]Control:[/bold]\n"
            "  /no-agents     → toggle subagent spawn blocking\n"
            "  /budget $X     → set session budget gate\n"
            "  /skip-plan     → skip planning, go straight to execute\n\n"
            "[bold]Run lifecycle:[/bold]\n"
            "  /resume [id]   → resume an interrupted run (picker if no ID)\n"
            "  /verify        → run tests/lint for current project\n"
            "  /ship          → verify → commit → create PR\n"
            "  /done          → mark current run complete\n"
            "  /status        → show current run + cost\n"
            "  /quit          → exit autopilot",
            title="Autopilot commands",
            border_style="dim",
        ))

    # ── Task launch ───────────────────────────────────────────────────────────

    def _ask_clarifying_questions(self, goal: str) -> str:
        """Use Haiku to generate clarifying questions, return enriched goal."""
        import anthropic as _anthropic
        client = _anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": (
                    f"Given this dev task: '{goal}'\n\n"
                    "Generate 2-3 concise clarifying questions that would prevent ambiguity "
                    "or rework. Be specific. Number them. If the task is already unambiguous, "
                    "respond with just: CLEAR"
                )}],
            )
            questions = resp.content[0].text.strip()
        except Exception:
            return goal

        if questions == "CLEAR" or not questions:
            return goal

        console.print(f"\n[bold yellow]Before starting, a few questions:[/bold yellow]\n{questions}\n")
        try:
            answers = self.session.prompt("Your answers: ")
        except (EOFError, KeyboardInterrupt):
            return goal

        return f"{goal}\n\nClarifications: {answers}"

    def _launch_claude(self, enriched_goal: str) -> None:
        """Launch claude subprocess with correct model and RunState context injected."""
        model = self.model_override or model_for(self.run.phase, self.run.goal)
        briefing = get_session_briefing(self.run)

        # Write briefing to a temp file and prepend to the session
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, prefix="ap_briefing_"
        ) as f:
            f.write(briefing)
            briefing_path = f.name

        env = os.environ.copy()
        if self.no_agents:
            env["AP_NO_SPAWN"] = "1"

        cmd = ["claude", "--model", model]

        console.print(
            f"\n[dim]→ Launching Claude ({model}) | "
            f"phase: {self.run.phase.value} | "
            f"run: {self.run.run_id}[/dim]\n"
        )

        # Pass briefing as initial user message via stdin or print it
        # Claude Code doesn't accept stdin injection, so we print the briefing path
        console.print(f"[dim]Session briefing: {briefing_path}[/dim]")
        console.print("[dim]Paste this at the start if you want full context:[/dim]")
        console.print(f"[dim]  cat {briefing_path} | pbcopy[/dim]\n")

        try:
            subprocess.run(cmd, env=env)
        except FileNotFoundError:
            console.print("[red]Error: 'claude' CLI not found. Install Claude Code first.[/red]")
        finally:
            Path(briefing_path).unlink(missing_ok=True)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        init_db()

        # Restore active run for this project
        self.run = load_active_run(self.project)

        console.print(Panel(
            f"[bold cyan]Autopilot[/bold cyan] — {self.project} ({self.branch})\n"
            f"[dim]Type a task to start, /help for commands, /quit to exit.[/dim]"
            + (f"\n\n[yellow]Active run: {self.run.run_id} — {self.run.goal[:60]}[/yellow]" if self.run else ""),
            border_style="cyan",
        ))

        while True:
            try:
                user_input = self.session.prompt(self._prompt_str()).strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Use /quit to exit.[/dim]")
                continue

            if not user_input:
                continue

            if user_input.startswith("/"):
                self.handle_slash(user_input)
                continue

            # New task or continuation
            if not self.run or self.run.status != RunStatus.active:
                enriched_goal = self._ask_clarifying_questions(user_input)
                self.run = create_run(enriched_goal)
                model = model_for(self.run.phase, self.run.goal)
                console.print(
                    f"\n[bold]New run {self.run.run_id}[/bold] | "
                    f"phase: {self.run.phase.value} | model: {model}"
                )

            self._launch_claude(user_input)

            # Reload run after session ends (hooks may have updated cost)
            from autopilot.tracker import load_run
            updated = load_run(self.run.run_id)
            if updated:
                self.run = updated

            today_cost = get_cost_today(self.project)
            console.print(
                f"\n[dim]Session ended. Run cost: ${self.run.cost_usd:.4f} | "
                f"Today: ${today_cost:.4f}[/dim]"
            )


def start_repl() -> None:
    AutopilotREPL().start()
