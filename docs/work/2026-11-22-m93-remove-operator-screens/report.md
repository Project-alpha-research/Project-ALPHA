# M93 report: remove operator screens

## Result
- Providers and Activity panes are gone. Eight unused Workstation files are gone, with their tests.
- Home page (Overview) now shows the Today view (`FollowToday`). `ResearchBacklog` left the home page.
- Lines: 36 added, 1,251 removed (git diff against `origin/main`, without this report).

## Pane counts (before → after)
- Overview: 1 → 1 (`ResearchBacklog` → `FollowToday`).
- Operations: 6 → 4 (Providers & system and Activity removed; Jobs, Data jobs, Alerts, Paper stay).
- Toolbox tabs: 6 → 5 (Log removed).
- The "Jobs & providers" document is now "Jobs".

## Deleted
- `panels/ProviderSystem.tsx`, `panels/ActivityFeed.tsx`.
- `shell/DocumentArea.tsx`, `DockFrame.tsx`, `FunctionBar.tsx`, `useSymbolVenue.ts`; `panels/portfolioModels.ts`, `workspaceModel.ts` and their tests. No file had an importer. No hit for `neurotrader`.
- Orphans from those panes: two helpers in `panels/controlPlane.ts` and their test, `feed-*` and `provider-*` styles, `api.providerCheck`, the "Check system readiness" button, the `showProviders` navigator action, and the cockpit's "Open Provider Readiness" recovery.
- Route `POST /api/providers/{id}/check`, `_catalog.provider_check`, model `ProviderCheckReceipt`, and one test. The CLI command `alpha provider check` stays. No command was removed.
- OpenAPI file, `generated.ts` and the governance classification are regenerated.
- Entries of deleted screens are out of `documents.ts`, `workflowModel.ts` (description only) and `terminalModel.ts`. `profiles.ts` had no entry to remove (the `jobs` window stays).

## Decisions
1. **No Ideas list exists in the Workstation.** The brief says one exists. The web app has no Ideas screen and no route; only `alpha idea list` in the CLI. I added none (brief: no new feature). The home page shows Today only. Today already lists the followed ideas.
2. `ResearchBacklog` stays: the Research document still uses it as a side pane.
3. `/api/providers`, `/api/system` and `/api/activity/stream` stay: Data Manager, Governance, Paper and the toasts use them.
4. `scripts/check_openapi_operations.py` still has a branch for the removed path. It is protected, so I left it dead.
5. Playwright: the harness now mocks `/api/follow/today`. One test now reads overrides on the Governance page. A toast test lost its feed half.
6. Docs: two pages named the activity feed; the Today page rule now names Overview.

## Checks
- `gate.py check --base origin/main`: pass. `lint-imports`: pass. `test_code_size.py`: pass, so no baseline entry to lower.
- Frontend: typecheck, lint, 866 unit tests, build: pass.
- Playwright reference lane: 222 passed. One test (`market-overview`, real backend) failed in the full run and passed when run alone; I treat it as a flake.
- Console error check on the new home page: none.
- Fail-first evidence: this is a deletion build. The new test surface is the e2e mock; the first lane run failed 10 tests with `unmocked API request: GET /api/follow/today`, then passed after the fix.
- Not run: `fs.py verify` (as ordered).

## Screenshots (synthetic data, dark theme)
- `home-today.png`, `home-full.png`.
