# Report: remove the Governance, Saved workspaces, Watchlist and Risk windows

Answer first: the four windows are gone. Net change is +78 / -3423 lines against main.

## Numbers
- Source and docs: about 1,250 lines removed (frontend, backend, docs).
- Tests (unit, integration, browser): +49 / -777.
- Generated files: `openapi.json` -879, `generated.ts` -512 (regenerated the way `apps/alpha-web/README.md` says).
- Windows (panes the shell lists, one profile): 19 before, 15 after. The brief says 29; I could not reproduce that count, so I report the pane count I can measure.

## Decisions
1. Watchlist: only the window entry went. The `MarketWatch` panel stays, because the Market Watch dock inside the Price chart uses it. Two browser tests that opened the window now open the Price chart.
2. Risk: only the window went. `/api/risk/scenario`, `RiskMetricBasis.tsx` and the "Stress test" tab of a run's report stay. The two browser lanes `risk-live` and `risk-metric-basis` now test the report tab only (the Risk window variant is removed, nothing else weakened).
3. Settings page stays (density, explanations, backtest result card), now with no window inside. Reached from View > Settings. Browser tests that used "Settings > Governance" to reach those controls now use a new `openSettings` helper.
4. Old links and saved tabs naming a removed window open without an error (tab restore drops them; a link opens the page's first window). Tests extended in `documentTabs.test.ts` and `workflowModel.test.ts`.
5. The unused `Toolbar` status chip and Governance button, `statusModel`, `useSelectedRunWatermark` and the `shell-modal`, glossary-panel and governance-table styles went with them (only Governance used them). Styles shared with V3 workbenches (`governance-grid/block/title/form`) stay.
6. Owner note: the Governance "Providers" page showed the TradingView Lightweight Charts attribution. That page is gone. The chart still shows its own attribution logo. I corrected the line in `THIRD_PARTY_NOTICES.md`. Private use only, so I judged this fine; the owner may want to know.
7. Commit trailer: I used the trailer given by the session instructions, not the `Fable 5.2` line in the common rules.
8. `scripts/gate_test_durations.json` still lists the deleted test file. It is a protected path; left alone.

## Deleted file groups and no-caller proof
Proof: after deletion I grepped apps, packages, tests, docs, scripts and research for each name. The only hits left are my own stale-link tests.
| Group | Files | Proof |
|---|---|---|
| Governance window | `panels/Governance.tsx`, `governanceModel.ts` (+test), `Glossary.tsx` | no import left; `tsc -b` clean |
| Saved workspaces window | `panels/Workspaces.tsx`; `api/workspaces.py`, `api/models/workspaces.py`, `_workspaces.py`, `test_web_api_workspaces.py`; `workspaces-load-race.spec.ts`; activity area `workspaces` | no caller of `/api/workspaces`; MCP has none |
| Risk window | `panels/RiskMonitor.tsx` | `RiskMetricBasis` and `/api/risk/scenario` still used by the report |
| Status chip | `shell/statusModel.ts` (+test), `useSelectedRunWatermark.ts` | only `Toolbar` and Governance used them |
| Routes `/api/system`, `/api/research-gate-overrides` | `control.py`, `_catalog.system`, `_development.active_research_gate_overrides`, models `SystemStatus`, `KronosCacheStatus`, `ActiveResearchGateOverride` | only Governance called them; `/api/v3/research-gate-overrides` and the `alpha info system` command stay |
| Client | `api.system`, `researchGateOverrides`, workspace methods and types | no remaining caller |

## Checks run
- Frontend: `tsc -b`, `oxlint --deny-warnings`, vitest (836 pass), build: pass.
- Web API tests (`tests/integration -k "web or api or openapi"`): pass.
- The five named unit test files (322): pass.
- `gate.py check --base origin/main`: ruff format failed once (two files); fixed. The other steps (ruff, docs, import contracts, mypy, pytest) passed.
- Fail-first evidence: the new stale-link tests name windows that did not exist in the registries after the change; they pass by dropping them. I wrote them with the code, not before (cleanup change).

## Browser tests
- Default lane (3 projects, 346 tests passed in the first run): one real failure of mine, fixed. `archive-chart` "watchlist picker" assumed the first read of `/api/chart-datasets` came from the picker; the Price chart also reads it. The test now fails every read until the retry and looks inside the dock. Same checks, same order.
- Two failures also occur on untouched `origin/main` in this cloud box, so they are not from this change: `rule-test-summary` hover readout (chromium-minimum) and the `chart-document` screenshot (chromium-wide, 8% pixels differ here, tolerance 2%). I did not regenerate that snapshot: the removed Governance button is far below the 2% tolerance, and a snapshot made in this box would not match CI.
- Removed the four `governance-document-*` screenshots (the window is gone).
- Native-result lane skipped: it needs the RD-Agent source and Python, not provisioned here. CI runs it.
