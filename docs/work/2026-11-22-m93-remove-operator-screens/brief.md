# Brief: remove operator screens and unused Workstation files; home page is Today plus Ideas

Branch: `chore/m93-remove-operator-screens`. Rules: `docs/work/_common-rules-2026-11-21.md` (deletion-only build). Extra rules for this build: the owner wants the project SMALLER
and SIMPLER: add no shim, no "moved" notice, no alias, no new option, no new guard. Do not copy other briefs or the common rules into your
branch; add only your own `report.md` in this task folder. NEVER delete anything that comes from neurotrader888: before deleting a file,
run `grep -il neurotrader <file>`; a hit means keep it and say so in the report (his material: `packages/alpha-patterns`,
`alpha_research/pip_miner.py`, `retracements.py`, `rolling_pca.py`, `alpha_validation/mcpt.py`, `bar_permutation.py`,
`trade_dependence.py`, `tests/fixtures/neurotrader/`, `alpha_data/crypto/features.py`). Report lines removed and added, and commands removed.

The owner talks to an AI in a terminal and uses the Workstation only to SEE results. Decided on 2026-11-22:
1. Delete the Providers and Activity screens/panes (frontend panels, their models, tests, Playwright lanes, menu entries, and the web
   routes that only they call). Do not touch the Paper screen (another build removes it).
2. Delete these files, which nothing imports (verify each with a grep of its import path across `apps/alpha-web/frontend/src`):
   `shell/DocumentArea.tsx`, `shell/DockFrame.tsx`, `shell/FunctionBar.tsx`, `panels/portfolioModels.ts`,
   `panels/workspaceModel.ts`, `shell/useSymbolVenue.ts`, and their tests.
3. Home page: the Overview page shows `ResearchBacklog`, a pane of the old research-case lane (`App.tsx`). Make the home page show the
   Today view and the Ideas list that already exist; remove `ResearchBacklog` from the home page (delete it only if nothing else uses it).
4. Three registries list the pages (`shell/documents.ts`, `shell/workflowModel.ts`, `shell/profiles.ts`). Do not redesign them here;
   only remove the entries of deleted screens from all three.
Regenerate the OpenAPI file and `src/api/generated.ts` if routes go. Build the frontend, run its unit tests and the Playwright
reference lane; the app must load with no console error. The screen is dark; charts stay white.

Done: pull request ready, `ci-ok` green except possibly the code-size test, `report.md` with before/after pane counts and two
synthetic screenshots of the new home page.
