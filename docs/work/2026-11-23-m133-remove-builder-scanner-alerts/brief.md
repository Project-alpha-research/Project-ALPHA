# Brief: remove the Strategy Builder, Scanner and Alerts windows (deletion only)

Branch: `chore/m133-remove-builder-scanner-alerts`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read first).
The owner approved this removal (plan phase 1a): the Workstation still lists three windows that the new pipeline replaced. Ideas are
now written in plain words and tested with `alpha test`; Setup Lab studies chart conditions; `alpha follow` watches surviving ideas.
The owner LIKES the Workstation's look: change nothing else about it. This is a DELETION change: net lines must fall a lot.

Remove, with everything only they use:
1. The Strategy Builder window (`builder`), the Scanner window (`scanner`) and the Alerts window/tab (`alerts`, including the
   "Alerts" tab in the bottom dock): entries in `apps/alpha-web/frontend/src/shell/` (documents, workflow model, profiles, menus,
   command palette, saved-workspace defaults, tours), their panel components, hooks, styles, tests and fixtures.
2. The web API routes only those windows call (rule builder, scan, alerts) under `apps/alpha-web/src/alpha_web/`, their tests, and
   their entries in the stored OpenAPI file and `generated.ts` (regenerate both the way `apps/alpha-web/CONTEXT.md` says).
3. `alpha` commands that ONLY those routes call and that no card, skill, nightly config, test of another feature or other command
   uses. Prove "no caller" for each file you delete with a grep, and list the proof in `report.md`. If anything else uses it, keep it.
4. Docs, cards and component pages that describe the removed windows: delete or correct them in the same change. A saved workspace
   that names a removed window must open without an error (drop the unknown window silently, with a test).

Never delete: anything that greps positive for `neurotrader` (case-insensitive); Setup Lab, patterns, lookalike, Kronos/forecast,
Monte Carlo, ML, RD-Agent, follow, toolbox, propfirm, ideas, the price chart, the report, compare, jobs, data windows; the
Governance window (it goes later with the old research-case machinery); the rule language in `packages/alpha-strategies`
(`alpha test` uses it). Do not edit protected paths (`workers/**`, `.claude/`, `.agents/`, `scripts/`, `tests/bias_guards/`,
`.github/`) except lowering or removing entries in `.claude/code-size-baseline.json` for code you deleted (never raise one). Do not
regenerate `STATUS.md`, `docs/roadmap/README.md`, `docs/reference/commands.md`.

Checks before you open the pull request: frontend lint, unit tests and build; `uv run python scripts/gate.py check`; and these
tests, which the light pull-request check does not run: `uv run pytest -q tests/unit/test_code_size.py
tests/unit/test_filesystem_contract.py tests/unit/test_research_playbook.py tests/integration -k "web or api or openapi"` (the
SPA must be built first for the web tests). Put this brief in the task folder on your branch (the folder contract needs it).
Done = pull request ready (not draft) with a green `ci-ok`; then stop and push nothing more.
Report: lines removed (source, tests), windows before and after, each deleted file group with its no-caller proof.
