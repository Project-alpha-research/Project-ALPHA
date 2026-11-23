# Report: remove the Strategy Builder, Scanner and Alerts windows

## Result

The three windows are gone. Net change: 204 lines added, 4,275 removed (60 files).
By group, net: source −1,419; tests (unit, integration, Playwright) −576; generated and docs −2,076.

## Windows before and after

| Part | Before | After |
|---|---|---|
| Windows | chart, report, compare, builder, scanner, rdagent, ideas, setup-lab, governance, forecast, jobs (11) | the same without builder and scanner (9) |
| Workflow pages | 7 (with "Strategies & Tests") | 6 ("Strategies & Tests" held only these two windows, so it is gone) |
| Toolbox tabs | Jobs, Backtests, Data pulls, Alerts | Jobs, Backtests, Data pulls |
| Chart results tabs | Scan results, Trades, Results, Run library | Trades, Results, Run library |
| Chart Conditions buttons | Refresh, Edit / test rules, Scan markets | Refresh |

## Decisions

1. The "Strategies & Tests" page is removed. It would be empty. An old link to it opens Overview (test in `workflowModel.test.ts`).
2. A saved tab, link or desk that names a removed window drops it silently (tests in `documentTabs.test.ts` and `workflowModel.test.ts`). Saved workspace files hold linked context only, no window names.
3. The default chart results tab is now Trades (it was Scan results). A stored "Scan results" choice falls back to the default.
4. `showStrategyLab` pointed at a page that no longer exists. It now opens Research › Ideas.
5. The chart's Conditions tab stays. It still needs `GET /api/rules` and `POST /api/rules/evaluate`, so those two routes stay.
6. The activity area `alerts` is removed from the backend and the SPA. Only the Alerts tab used it.
7. Two Playwright specs are deleted: `edge-real.spec.ts` and `deferred-editing.spec.ts`. Both could only start from a rule saved or edited through the removed routes. The scripts folder is protected, so the test server cannot be pre-seeded with a rule. Condition evaluation stays covered by `tests/integration/test_rules_explain.py`.
8. Commit trailers follow the common build rules (`Co-Authored-By: Claude Fable 5.2`).
9. `docs/governance/2026-09-12-neurotrader888-provenance.md` greps positive for the guard word. I did not delete it. I changed one phrase (it named the Strategy Builder dialog) and nothing else.

## Fail-first

`tests/integration/test_web_api_rules.py::test_rules_are_listed_and_the_builder_routes_are_gone` failed before the change (`/api/rules` still had `post`). It passes after. The frontend tests for stale links and tabs were added with the change.

## Deleted file groups and no-caller proof

| Group | Proof |
|---|---|
| `panels/StrategyBuilder.tsx`, `ruleBuilderModel(.test).ts` | `grep -rn "StrategyBuilder\|ruleBuilderModel"` found imports only in `documents.ts` (removed) and each other. `tsc`, lint, vitest and build pass. |
| `panels/Scanner.tsx`, `scannerModel(.test).ts` | Importers were `documents.ts`, `DeskResults.tsx`, `Alerts.tsx` (all edited or deleted). |
| `panels/Alerts.tsx` | Importers were `Toolbox.tsx` and `workflowModel.ts` (edited). |
| `state/ruleDraft.ts` | Importers were `actions.ts` (the `openRuleBuilder` helper) and `StrategyBuilder.tsx`. |
| `actions.ts`: `openRuleBuilder`, `openScanner`, `openScannedMarket` | Callers were `ConditionChecklist`, `Scanner`, `Alerts` only. `scanChartContext` had one caller (`openScannedMarket`) and is removed. |
| `api/client.ts`: `rule`, `ruleSave`, `ruleValidate`, `ruleDelete`, `scans`…`scanDelete`, `alerts` | `grep "api\.(rule|ruleSave|ruleValidate|ruleDelete|scan*|alerts)\b"` found callers only in the removed panels. `api.rules` stays (ConditionChecklist). |
| `alpha_web/_scans.py`, `api/scans.py` | `_scans` was imported only by `api/scans.py`; the router only by `app.py` (edited). |
| `api/rules.py` save, validate, delete, show; `_rules.py` same; models `RuleRecord`, `RuleSaveRequest`, `RuleValidateRequest`, `RuleValidation`, `RuleDeleted`, `Scan*` | Callers were the removed client functions. `grep "/api/rules"` in tests, e2e and docs found no other user. OpenAPI file, `generated.ts` and the classification files are regenerated. |
| `tests/integration/test_web_api_scans.py` | Tested only the removed routes. |

## `alpha` commands: none deleted

Every CLI command the removed routes called has another user, so all stay:

- `alpha scan list|show|save|delete|run|check|alerts`: used by `tests/unit/test_scan_bias_guard.py` (bias guard), `tests/unit/test_reserve_holdback_commands.py`, `tests/integration/test_rules_explain.py`, `tests/integration/test_cli_scan.py`, `tests/unit/test_scan_engine.py`. The same `scan_cmds.py` module also holds `scan hypotheses` and `scan replay` (quick-screen card).
- `alpha rules list|show|save|validate|delete|explain`: `rules_cmds.resolve_rules_spec` is used by `backtest_cmds.py` and `validate_cmds.py` (`alpha test` path); `tests/integration/test_cli_rules.py` covers the commands.

## Docs fixed

`docs/reference/invariants/web-research.md` (sources, builder and scan sections), `docs/roadmap/capabilities.toml` (entry points and the deleted spec), `docs/ARCHITECTURE.md`, `docs/reference/invariants/strategies.md`, the provenance line above, `apps/alpha-web/frontend/README.md`. Not regenerated, as briefed: `STATUS.md`, `docs/roadmap/README.md`, `docs/reference/commands.md` (no command changed).

## Checks run

- Frontend: `tsc` (app and e2e configs), `npm run lint -- --deny-warnings`, `vitest` (97 files, 850 tests), `npm run build`.
- `uv run lint-imports`: 13 kept, 0 broken.
- `uv run python scripts/gate.py check`: passed.
- `uv run pytest -q tests/unit/test_code_size.py tests/unit/test_filesystem_contract.py tests/unit/test_research_playbook.py tests/integration -k "web or api or openapi"`: passed. `.claude/code-size-baseline.json` named none of the deleted files, so no entry changed.
- Not run: the Playwright browser specs (no browser lane here). CI runs them.
