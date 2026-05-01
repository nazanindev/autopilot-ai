# Cursor Plan

Updated: 2026-04-30

## Completed Harness Updates

- Tier 1 foundations shipped:
  - `flow` namespace migration and CLI packaging cleanup
  - `AGENTS.md` + `CLAUDE.md` routing docs
  - stronger `flow verify` failure guidance
  - clean-state checks in stop hook for verify/ship phases
- Tier 2 core primitives shipped:
  - `features.yaml` state model + `flow features` commands
  - active feature wiring into run state + injected context
  - soft WIP=1 guidance in pretool hook
  - `flow init --repo` scaffolding support
- Plan progression controls shipped:
  - plan parsing fallback in REPL and pretool hook
  - `/approve` and `/reject` plan controls
  - session gates: `/gate plan on|off`, `/gate pr on|off`, `/gate autoship on|off`
  - `/execute` alias, lifecycle nudges, and clearer phase UX
  - execute-step completion via `STEP_DONE: <id>` auto-marking
- Shipping flow upgrades shipped:
  - resilient `/ship` behavior when PR already exists
  - branch/title controls (`/ship-branch`, `/ship-title`)
  - global style-driven ship defaults (`ship.*` in style config)
- Repo hygiene shipped:
  - git `post-merge` hook installer in `flow init`
  - auto-close active run when linked PR is merged (on local post-merge event)

## Remaining Work (To Finish Harness Engineering)

1. Worker/Checker separation (`flow check`)
   - Add independent reviewer command that evaluates local diff with a rubric.
   - Output machine-readable findings (JSON) and concise human summary.
2. Verify-phase gate integration
   - Optional prompt/auto-run of `flow check` before shipping.
   - Require explicit acknowledgement for blocker-level findings.
3. Sprint contract injection
   - Extend briefing with a compact sprint contract derived from active feature.
   - Include acceptance criteria + verification command + out-of-scope.
4. Stronger evidence model for step completion
   - Keep `STEP_DONE` token, but add optional evidence check (file/test output hint).
   - Reduce false positives where model claims done without enough proof.
5. End-to-end regression coverage
   - Add e2e checks for lifecycle transitions:
     - plan capture -> approve -> execute
     - execute step completion -> verify auto-advance
     - verify -> ship gating and autoship behavior
     - existing PR handling + post-merge auto-close

## Suggested Next Slice

- Build `flow check` first (smallest high-leverage checker primitive).
- Then wire verify-phase prompting for `flow check`.
- Then add sprint contract section to context briefing.
