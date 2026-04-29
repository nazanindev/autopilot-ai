"""ap serve — local FastAPI dashboard on :7331."""
import os

from rich.console import Console

console = Console()

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Autopilot</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", monospace; background: #0d1117; color: #e6edf3; padding: 2rem; }
  h1 { font-size: 1.25rem; color: #58a6ff; margin-bottom: 1.5rem; letter-spacing: 0.05em; }
  h2 { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.1em; color: #8b949e; margin: 1.5rem 0 0.75rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 1.25rem; }
  .card .label { font-size: 0.7rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.4rem; }
  .card .value { font-size: 1.5rem; font-weight: 600; color: #e6edf3; }
  .card .sub { font-size: 0.75rem; color: #8b949e; margin-top: 0.25rem; }
  .bar-wrap { background: #21262d; border-radius: 4px; height: 6px; margin-top: 0.5rem; overflow: hidden; }
  .bar { height: 100%; border-radius: 4px; background: #238636; transition: width 0.3s; }
  .bar.warn { background: #d29922; }
  .bar.danger { background: #da3633; }
  table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
  th { text-align: left; color: #8b949e; font-weight: 500; padding: 0.5rem 0.75rem; border-bottom: 1px solid #21262d; }
  td { padding: 0.5rem 0.75rem; border-bottom: 1px solid #161b22; color: #c9d1d9; }
  tr:hover td { background: #161b22; }
  .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 12px; font-size: 0.7rem; font-weight: 500; }
  .badge-active { background: #0d4429; color: #3fb950; }
  .badge-complete { background: #0c2d6b; color: #58a6ff; }
  .badge-failed { background: #4b0000; color: #f85149; }
  .badge-blocked { background: #3d2b00; color: #d29922; }
  .phase { font-size: 0.7rem; color: #58a6ff; text-transform: uppercase; }
  #refresh { font-size: 0.7rem; color: #8b949e; float: right; cursor: pointer; background: none; border: none; color: #8b949e; }
  #refresh:hover { color: #58a6ff; }
</style>
</head>
<body>
<h1>⚡ Autopilot <button id="refresh" onclick="load()">↻ refresh</button></h1>
<div id="app"><p style="color:#8b949e">Loading...</p></div>
<script>
async function load() {
  const [status, stats, runs] = await Promise.all([
    fetch('/status').then(r=>r.json()),
    fetch('/stats').then(r=>r.json()),
    fetch('/runs').then(r=>r.json()),
  ]);

  const budget = status.budget_gate_usd || 2.0;
  const todayPct = Math.min((status.cost_today / budget) * 100, 100);
  const barClass = todayPct > 80 ? 'danger' : todayPct > 50 ? 'warn' : '';

  let activeHtml = '';
  if (status.active_run) {
    const r = status.active_run;
    const runPct = r.max_steps > 0 ? Math.min((r.current_step / r.max_steps) * 100, 100) : 0;
    const projected = r.current_step > 0 ? (r.cost_usd / r.current_step * r.max_steps).toFixed(4) : '—';
    activeHtml = `
      <h2>Active run</h2>
      <div class="card" style="grid-column:1/-1">
        <div class="label">${r.run_id} &middot; <span class="phase">${r.phase}</span></div>
        <div class="value" style="font-size:1rem;margin-top:0.25rem">${r.goal.substring(0,100)}</div>
        <div class="sub">Step ${r.current_step}/${r.max_steps} &middot; $${r.cost_usd.toFixed(4)} spent &middot; ~$${projected} projected</div>
        <div class="bar-wrap"><div class="bar ${runPct>80?'warn':''}" style="width:${runPct}%"></div></div>
      </div>`;
  }

  const projectRows = (stats.projects||[]).map(p => `
    <tr>
      <td>${p.project}</td>
      <td>${p.sessions}</td>
      <td>$${p.total_cost.toFixed(4)}</td>
      <td>${(p.total_tokens||0).toLocaleString()}</td>
      <td>${(p.last_active||'').substring(0,10)}</td>
    </tr>`).join('');

  const runRows = (runs||[]).map(r => {
    const badge = `badge-${r.status}`;
    return `<tr>
      <td style="font-family:monospace;font-size:0.75rem">${r.run_id}</td>
      <td>${r.goal.substring(0,50)}</td>
      <td><span class="phase">${r.phase}</span></td>
      <td><span class="badge ${badge}">${r.status}</span></td>
      <td>$${r.cost_usd.toFixed(4)}</td>
      <td>${(r.updated_at||'').substring(0,10)}</td>
    </tr>`;}).join('');

  document.getElementById('app').innerHTML = `
    <div class="grid">
      <div class="card">
        <div class="label">Today (this project)</div>
        <div class="value">$${status.cost_today_project.toFixed(4)}</div>
        <div class="sub">${todayPct.toFixed(0)}% of $${budget} budget</div>
        <div class="bar-wrap"><div class="bar ${barClass}" style="width:${todayPct}%"></div></div>
      </div>
      <div class="card">
        <div class="label">Today (all projects)</div>
        <div class="value">$${status.cost_today.toFixed(4)}</div>
      </div>
      <div class="card">
        <div class="label">Active project</div>
        <div class="value" style="font-size:1rem;margin-top:0.3rem">${status.project}</div>
      </div>
    </div>
    ${activeHtml}
    <h2>By project</h2>
    <table>
      <thead><tr><th>Project</th><th>Sessions</th><th>Total</th><th>Tokens</th><th>Last active</th></tr></thead>
      <tbody>${projectRows || '<tr><td colspan="5" style="color:#8b949e">No data yet</td></tr>'}</tbody>
    </table>
    <h2>Recent runs</h2>
    <table>
      <thead><tr><th>ID</th><th>Goal</th><th>Phase</th><th>Status</th><th>Cost</th><th>Updated</th></tr></thead>
      <tbody>${runRows || '<tr><td colspan="6" style="color:#8b949e">No runs yet</td></tr>'}</tbody>
    </table>`;
}
load();
</script>
</body>
</html>"""


def cmd_serve(port: int = 7331) -> None:
    try:
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse, JSONResponse
        import uvicorn
    except ImportError:
        console.print("[red]fastapi and uvicorn are required: pip install fastapi uvicorn[/red]")
        raise SystemExit(1)

    from autopilot.tracker import (
        init_db, get_cost_today, get_project_stats, get_recent_runs, load_active_run
    )
    from autopilot.config import get_project_id, constraints

    init_db()
    app = FastAPI(title="Autopilot", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        return _HTML

    @app.get("/status")
    async def status():
        project = get_project_id()
        run = load_active_run(project)
        c = constraints()
        budget_gate = float(os.getenv("AP_BUDGET_USD") or c.get("budget_gate_usd", 2.0))

        active = None
        if run:
            projected = None
            if run.current_step > 0:
                projected = round(run.cost_usd / run.current_step * run.max_steps, 6)
            active = {
                "run_id": run.run_id,
                "goal": run.goal,
                "phase": run.phase.value,
                "current_step": run.current_step,
                "max_steps": run.max_steps,
                "cost_usd": run.cost_usd,
                "projected_usd": projected,
                "status": run.status.value,
                "plan_steps": run.plan_steps,
            }

        return JSONResponse({
            "project": project,
            "cost_today": get_cost_today(),
            "cost_today_project": get_cost_today(project),
            "budget_gate_usd": budget_gate,
            "budget_pct": round(get_cost_today(project) / budget_gate * 100, 1),
            "active_run": active,
        })

    @app.get("/stats")
    async def stats():
        return JSONResponse({"projects": get_project_stats()})

    @app.get("/runs")
    async def runs(limit: int = 20, project: str = None):
        return JSONResponse(get_recent_runs(project, limit=limit))

    console.print(f"[bold cyan]Autopilot dashboard[/bold cyan] → http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
