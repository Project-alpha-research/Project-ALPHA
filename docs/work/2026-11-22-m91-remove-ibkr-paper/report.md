# Report: remove IBKR paper trading

Result: the `alpha paper` group, its web screen and its API are gone. `alpha follow` is untouched.
Lines against `origin/main`: source 56 added, 5,451 removed; tests 14 added, 4,318 removed;
docs and generated files 125 added, 1,624 removed.

## Commands removed (14)

`alpha paper` with: `ibkr-preflight`, `ibkr-run`, `ibkr-what-if-execute`, `ibkr-what-if-plan`, `preflight`, `readiness`,
`reconcile`, `run`, `scheduler-repair`, `scheduler-status`, `scheduler-tick`, `sessions`, `show`, `stop`.
Also removed: the `alpha provider check ibkr` check and the `ibkr` entry in `alpha info providers`.

## No-caller proof per deleted file

Method: `grep -rnE` for the module name, the command words and `python -m`/subprocess use, in `apps packages workers tests scripts docs`.
`grep -il neurotrader` returned no hit for any deleted file.

| Deleted | Reached only by |
|---|---|
| `alpha_cli/paper_cmds.py` | the `paper` row in `main.py` (removed) |
| `alpha_cli/_paper.py`, `_ibkr_paper.py`, `ibkr_what_if.py`, `paper_acceptance.py`, `paper_readiness.py` | `paper_cmds.py`, each other, `daily_scheduler.py`, deleted tests |
| `alpha_cli/paper_store.py` | those modules, `alpha_web/api/paper.py`, and the marker code in `alpha_web/api/candles.py` (removed) |
| `alpha_cli/daily_scheduler.py` | `paper_cmds.py` and `scripts/run_daily_scheduler.sh` |
| `scripts/run_daily_scheduler.sh`, `docs/operations/com.project-alpha.daily.plist.example`, `daily-paper.example.json` | the scheduler only |
| `alpha_web/api/paper.py`, `api/models/paper.py` | `app.py` router line and `models/__init__.py` (removed) |
| `frontend/src/panels/PaperMonitor.tsx`, `paperModel.ts`, `paperModel.test.ts` | `documents.ts`, `Toolbox.tsx`, `Navigator*` (edited) |
| 8 test files (`test_paper*`, `test_ibkr_paper`, `test_daily_scheduler`, `test_web_api_paper`, `test_binance_paper_live`, `test_paper_command_guards`) | test only the deleted code |
| `docs/reference/invariants/cli-paper.md` | links in `invariants/README.md`, `paper-and-live.md` (fixed) |

Also removed: the `paper-trading` capability row (`capabilities.toml`, `capability-trace.md`), the `ibkr` provider and
`paper_execution` field, `supports_live_paper`, `paper_enabled`/`ibkr_paper_enabled` settings and status fields,
the `paper` activity area, the paper candle markers, and the Paper menu, document, navigator group and Toolbox tab.
Regenerated: `commands.md`, `STATUS.md`, `openapi.json`, `generated.ts`, the OpenAPI classification file.

## Decisions

1. **Kept `alpha_strategies/base.py` paper hooks and `ExecutionEventSink`.** The strategy fingerprint hashes `base.py`;
   any edit moves every run id and breaks pinned ids in `test_reading_rule`, `test_reserve_scan_and_archive`.
   About 250 lines of unused paper-risk code remain there. Remove them in a separate build that accepts the id change.
2. **Kept `paper_resources.py`**: it holds links to academic papers, not paper trading.
3. **Kept the project stage `paper`, `strategy-candidate paper-preflight` and the `paper_preflight` suite action name**; the non-hedged suite action no longer builds a `paper preflight` step and returns a blocker (Codex review finding, fixed):
   they are lifecycle and hedged-basis blockers, not a broker path. They need an owner decision.
4. **Kept `Paper only` status chip** (no-live-capital label) and the `Follow` paper text.
5. **Edited `tests/unit/test_research_reads_are_cut.py`**: removed 3 exemptions for the deleted files. No guard was weakened.
6. **Deleted three Playwright checks** that only tested the Paper screen: the paper-marker printf hover test,
   "only the active document mounts", and the paper-journal refetch step (the Log step now uses the `alerts` area).
7. **No-broker test:** `.claude/settings.json` deny rules and `test_claude_harness_settings.py` still name `alpha paper ibkr-run`.
   They are protected, so I left them; the commands no longer exist.
8. Left `ALPHA_PAPER_ENABLED` env lines in 4 test/script fixtures (`scripts/run_playwright_backend.py` is protected; they are inert).
9. Left `tests/_tiers.py` (protected): its `test_paper_`, `test_ibkr_` name prefixes now match nothing.
10. Dated records (ADRs, governance, `docs/work/`) keep their paper text.
11. Browser (Playwright) lanes were not run here.

## Fail-first evidence

A deletion has no new behaviour to fail first. The failing checks came from the removal: `test_generic_command_catalog`,
`test_cli_entry_lazy_groups`, `test_capabilities`, `test_filesystem_contract`, `test_provider_registry`, `test_web_contracts`,
`test_status_page`, `test_web_menu_groups` failed after the first delete and passed after I fixed the owning file.

## MCP tools

`apps/alpha-mcp` (protected): no tool names paper or IBKR (`mcp__alpha__*` list has none). Nothing to list.

## Dependency

`apps/alpha-cli/pyproject.toml` still has `nautilus-trader[ib,docker]==1.228.0`. Nothing imports the IB adapter or `ibapi` now.
Change it to `nautilus-trader==1.228.0` and re-lock (`uv.lock` is protected: not done).

## Code-size test (the one expected red)

`tests/unit/test_code_size.py` asks the orchestrator to edit `.claude/code-size-baseline.json`:

- remove `apps/alpha-cli/src/alpha_cli/_ibkr_paper.py::run_ibkr_paper`
- remove `apps/alpha-cli/src/alpha_cli/ibkr_what_if.py::IBAPITransport.preview`
- lower `apps/alpha-cli/src/alpha_cli/providers.py::provider_definitions` to 275

## Known red from the brief's own rule

`test_task_folders_hold_a_plan_and_only_stage_files` fails on this branch: the task folder holds only `report.md`, and the
brief said not to copy `brief.md` here. It passes once the brief branch is merged (it supplies `brief.md`). A 2026-11-22 CI run
also failed `test_component_pages_state_purpose_reasoning_plan_and_place` (I had dropped the ADR link in `nautilus.md`); fixed.

## Checks run

`gate.py check --base origin/main` passes (ruff, format, docs, import contracts, mypy, mapped pytest).
Full `tests/unit tests/integration`: the only failures not caused by this change are on `main` too
(codex rpc, home backup, two rdagent tests) or need the network (live provider tests), plus `test_code_size`.
Frontend: `tsc -b`, `oxlint`, `vitest` (866 tests) pass.
