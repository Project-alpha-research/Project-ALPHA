# Brief: remove the Governance, Saved workspaces, Watchlist and Risk windows (deletion only)

Branch: `chore/m138-remove-four-windows`. Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read first). The
owner said on 2026-11-23 that they do not use these four Workstation windows and want them removed. The owner LIKES the
Workstation's look: change nothing else about it. This is a DELETION change: net lines must fall. The model is the earlier removal
of the Builder, Scanner and Alerts windows (merged pull request #437: read its diff for the places to touch).

Remove, with everything only they use:
1. The windows `Governance` (also the "Governance" button at the top right of the shell), `Saved workspaces`, `Watchlist` and
   `Risk` (also any "Risk" tab that only opens that window): their entries under `apps/alpha-web/frontend/src/shell/` (documents,
   workflow model, profiles, menus, command palette, defaults, tours), panel components, hooks, styles, unit tests, fixtures and
   the browser journeys under `apps/alpha-web/frontend/e2e/` (a journey whose only purpose was a removed window is deleted with
   its helpers; one that merely passed through is repointed at the right remaining window; never weaken a journey of a kept feature).
2. The web API routes only those windows call, under `apps/alpha-web/src/alpha_web/`, with their tests and their entries in the
   stored OpenAPI file and `generated.ts` (regenerate both the way `apps/alpha-web/CONTEXT.md` says). A route another window or
   the MCP server still calls stays.
3. Do NOT delete any `alpha` command in this change (the old approval and research-case commands go later in their own ordered
   changes). Do not delete the layout engine itself: windows must still open, dock and tab as now; only the screen that saves and
   reloads named layouts goes. A layout or link stored earlier that names a removed window must open without an error (drop the
   unknown window silently; extend the existing test for that).
4. Docs, cards and component pages that describe the removed windows: delete or correct them in the same change. In
   `docs/roadmap/capabilities.toml` correct any "Workstation: View > ..." text that names a removed window (keep the capability
   and its command). Do not regenerate `STATUS.md`, `docs/roadmap/README.md` or `docs/reference/commands.md`.

Never delete: anything that greps positive for `neurotrader` (case-insensitive) on main; Setup Lab, patterns, lookalike,
Kronos/forecast, Monte Carlo, ML, RD-Agent, follow (the Today window), toolbox, propfirm, ideas, the price chart, the Market
window, the report, compare, the run library, jobs, data windows. Do not edit protected paths (`workers/**`, `.claude/`,
`.agents/`, `scripts/`, `tests/bias_guards/`, `.github/`) except lowering or removing entries in
`.claude/code-size-baseline.json` for code you deleted (never raise or add one).

Checks before the pull request: for EVERY deleted file grep the remaining tree for its module, component and route name: no
reference may remain (code, docs, tests, e2e, defaults). Frontend lint, unit tests, build, and the browser tests
(`cd apps/alpha-web/frontend && npm run test:e2e:built`: the pull-request check runs them and they failed on #437's first try).
Then `uv run python scripts/gate.py check` and `uv run pytest -q tests/unit/test_code_size.py tests/unit/test_filesystem_contract.py
tests/unit/test_research_playbook.py tests/unit/test_capabilities.py tests/unit/test_overlay_tables_drift.py` and the web API
tests (`tests/integration -k "web or api or openapi"`, SPA built first). Put this brief in the task folder on your branch.
Done = pull request ready (not draft) with a green `ci-ok`; then stop and push nothing more.
Report: lines removed (source, tests), windows before (29) and after, each deleted file group with its no-caller proof.
