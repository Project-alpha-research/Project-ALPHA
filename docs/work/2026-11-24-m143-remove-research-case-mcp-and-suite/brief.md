# Brief: remove the research-case MCP tools and `alpha suite` (plan steps 4 and 5)

Branch: `chore/m143-remove-research-case-mcp-and-suite`. Do step 4 first, commit and push; then step 5. Another builder is
deleting research-case screens and web routes under `apps/alpha-web`: stay out of `apps/alpha-web`.
Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first). The owner (one retail swing trader, not a
coder) approved on 2026-11-23 the removal of the old research-case machinery, which the new pipeline replaced (`alpha test`,
ideas, Setup Lab, follow, nightly, `alpha confirm`). This is a DELETION change taken from the ordered removal plan; the plan text
for your steps is copied below. Delete exactly what it lists; prove "no caller" with the searches it gives (they must return only
files you delete) and put the proofs in `report.md`. If a listed file turns out to have another caller, KEEP it and say so.

Never delete: anything that greps positive for `neurotrader` (case-insensitive) on main; any named feature (Kronos/forecast, the
Monte Carlos, lookalike, patterns, Setup Lab, RD-Agent, Qlib/ML and its lab window, follow, toolbox, propfirm, ideas, nightly,
backup, `alpha confirm`, the trial ledger, data commands and windows, jobs, the price chart, Market, report, compare, run
library). The owner LIKES the Workstation look: change nothing about it beyond the removals. Do not edit protected paths
(`workers/**`, `.claude/`, `.agents/`, `scripts/`, `tests/bias_guards/`, `tests/holdout/`, `.github/`,
`packages/alpha-research/src`, `packages/alpha-validation/src`) except lowering or removing entries in
`.claude/code-size-baseline.json` for code you deleted (never raise or add one). The import-linter contract "kept features stand
off the old research-case machinery" in `pyproject.toml` names modules: remove from its forbidden list the names you delete, and
keep `uv run lint-imports` green. In `docs/roadmap/capabilities.toml` make the card edits the plan names; do NOT regenerate
`STATUS.md`, `docs/roadmap/README.md` or `docs/reference/commands.md` (a later sweep does), but if `tests/unit/test_status_page.py`
or `test_commands_reference.py` then fail only because those generated pages are out of step, regenerate just that page with its
own script and say so. In the task folder on your branch write a SHORT `brief.md` (at most 15 lines of at most 150 characters: what the steps remove and where the full brief is, `work/m102-briefs`); do not copy this long brief there. Write no figure from a real run anywhere.

Checks before the pull request (the pull-request check is light; these have broken main before): the tests the plan lists; `uv run
pytest -q tests/unit/test_code_size.py tests/unit/test_filesystem_contract.py tests/unit/test_research_playbook.py
tests/unit/test_capabilities.py tests/unit/test_status_page.py tests/unit/test_reserved_date_one_home.py tests/smoke`; for web
changes the frontend lint, unit tests, build and the browser tests exactly as CI runs them (`uv run python scripts/gate.py
component frontend`: fix every journey that still expects a removed screen; delete journeys that only served one; never weaken a
kept feature`s journey); `uv run lint-imports`; `uv run python scripts/gate.py check`. A function over its size ceiling is split,
never the ceiling raised. Done = pull request ready (not draft) with a green `ci-ok`; then stop and push nothing more.
Report: lines removed (source, tests), each deleted group with its no-caller proof, anything you kept and why.

## Plan text: the units
### 3.1 CLI groups and modules (`apps/alpha-cli/src/alpha_cli/`)

| Unit | Lines | Decision | Step | Caller or proof |
|---|---:|---|---|---|
| `reserved_slots.py` use of `ControlStore` and `_control_schema._SCHEMA_RESERVED_CONFIRMATION` | 169 | MOVE-FIRST: own small SQLite open, own DDL | 1 | `confirm_cmds`, `spine/reserve`, `spine/confirm`, `spine/confirm_run`, `next_cmds` |
| Job methods of `ControlStore` (`create_job` ... `reconcile_interrupted_jobs`, `control_store.py:12112-12825`, about 600 lines) | ~600 | MOVE-FIRST to `job_store.py`; `ControlStore` delegates until step 11 | 1 | `project job-*` called by web `_ml.py`, `_invoke.py`, MCP `_invoke.py` |
| `_run_literature_worker` (`research_cmds.py`, about 75 lines), `_read_owner_pdf`, `_validated_extraction` (`local_pdf_cmds.py:78-140`), `_MAX_OWNER_PDF_BYTES` (`control_store.py`) | ~150 | MOVE-FIRST to `literature_call.py` | 1 | `library_papers_cmds.py:13-14` (`alpha library search`, `import-pdf`) |
| `suite_cmds` 160, `_suite` 1,141, `_suite_actions` 930, `_suite_types` 491, `suite_catalog` 20 | 2,742 | DELETE | 5 | only web `_development.py:513,532`, MCP `_control.py:797-839` (gone in steps 3-4) |
| `project_cmds.py` lines 1-702 (create, version, experiment, link-run, attempt, stage-*, seal/reveal-holdout, decide, workspace, agent-brief, override-research-gate, review-monte-carlo) | ~700 | DELETE | 6 | no caller after steps 2-5 |
| `project_cmds.py` lines 703-886 (`job-*`) | ~185 | KEEP, renamed file `jobs_cmds.py`, still mounted as `alpha project` | 6 | web `_ml.py`, `_invoke.py`; MCP `_invoke.py` |
| `project_workspace.py` | 878 | DELETE | 6 | only `project_cmds` |
| `evidence_cmds.py` | 176 | DELETE | 6 | only `main.py` |
| Native lane: `native_supervisor` 954, `_native_fixture_store` 759, `_native_daily_rule_artifacts` 729, `_native_daily_rule_container` 395, `_native_daily_rule_projection` 348, `_native_daily_rule_restore` 187, `_native_daily_rule_history` 171, `_native_loop_admission` 357, `_native_rule_artifacts` 259, `_native_rule_completion` 257, `_native_rule_projection` 279, `_native_rule_environment` 176, `_native_rule_authority` 43, `_native_stock_launch` 217, `native_stock_fixture` 243, `native_stock_inspect` 376, `native_stock_profile` 196, `native_stock_cmds` 118, `daily_native_cmds` 282, `daily_rule_report` 263 | 6,609 | DELETE after Q1 | 7 | entry only through `research run` and `research diagnostic native-result` |
| `_native_rule_protocol` 385, `_native_daily_rule_protocol` 331, `_native_daily_rule_study` 372, `_native_rule_study` 131, `_native_rule_economics` 193, `_native_daily_rule_identity` 14 | 1,426 | DELETE after Q1, after the edit below | 7 | only kept caller: `research_analysis_plan.py:192-199` (two schema branches for case contracts) |
| `research_analysis_plan.py` | 365 | KEEP; drop the two native branches (lines 191-200) | 7 | `info_cmds.py:177` (`analysis_family_catalog`), `ml_refit.py:19` |
| `report_cmds.py` daily-rule branch (lines 93, 155-175) | ~30 | DELETE the branch | 7 | `--daily-rule-evidence` only from web `api/runs.py:80-94` |
| `owner_auth.py` 525, `owner_auth_cmds.py` 56 | 581 | DELETE | 8 | `owner_auth_cmds`, web `api/owner_auth.py`; hidden since 2026-11-22 (`main.py:52-53`) |
| `research_cmds` 3,537, `_research_cmd_parts` 1,107, `research_intake` 815, `research_execution` 454, `research_execution_digest` 236, `research_diagnostic_cmds` 224, `research_dossier` 236, `research_suggestions` 237, `research_study_status` 170, `research_workflow_contract` 101, `research_compare` 26, `local_pdf_cmds` 363 | 7,506 | DELETE | 9 | only `main.py:69-85` and each other |
| `research_d1` 1,411, `research_d2` 829, `research_runtime` 967, `research_crypto_runtime` 828, `research_crypto_d2` 438, `research_crypto_binding` 123, `research_readiness` 123, `research_data_audit` 363, `research_gate_packet` 1,568, `study_semantic` 120, `_research_artifact_io` 55, `paper_resources` 394 | 7,219 | DELETE | 10 | only `research_cmds`, `_research_cmd_parts`, lazy imports inside `control_store` methods |
| `control_store` 14,025 (about 13,400 after step 1), `_control_schema` 964, `_control_json` 62, `_ml_observation_store` 559, `ml_native_plan` 563, `_structural_digest` 297 | 16,470 | DELETE after Q1 | 11 | no kept importer after steps 1-10 (graph proof) |
| `research_crypto_data` 311, `research_crypto_strategy` 248 | 559 | KEEP | – | `crypto_data_cmds`, `strategy_candidate_cmds` (reserved-date cut of crypto rows) |
| `research_protocols` 94 and `.agents/skills/alpha-research-protocols/` | 646 | KEEP | – | `info_cmds.py:178` (`alpha info` catalogue) |
| `durable_lease` 474, `job_capacity` 50 | 524 | KEEP | – | web `_ml.py`, `_invoke.py`; MCP `_invoke.py` |
| `_native_tearsheet` | – | KEEP (Nautilus tear sheet, not the native lane) | – | `_artifacts.py` |
| `moved_notice` 31, `library_papers_cmds` 227 | – | KEEP | – | `main.py` (`alpha library`) |


### 3.4 MCP (`apps/alpha-mcp/src/alpha_mcp/`)

| Unit | Lines | Decision | Step |
|---|---:|---|---|
| `server.py` research tools 519-736 (15), project tools 781-1060 (14), `plan/launch_development_suite` 1108-1154, `plan/launch_ml_experiment` 1180-1195, evidence tools 1198-1337 (5) | ~700 | DELETE | 4 |
| `_control.py` research 63-315, projects 370-719, suite 786-874, evidence 918-1051 | ~826 | DELETE | 4 |
| `_types.py`: 36 research/project/evidence/suite classes | ~342 | DELETE | 4 |
| `server.py` data tools 739-778, job tools 1063-1105 and 1157-1177; `_control.py` 318-367, 722-783, 877-915 | – | KEEP (`cancel_development_suite` cancels any job) | – |


## Plan text: the steps
### Step 4: MCP tools

- **Branch:** `chore/m143-remove-research-case-mcp-tools`
- **Files:** §3.4; delete `tests/integration/test_research_mcp.py` (423); edit
  `tests/integration/test_mcp_server.py`, `tests/unit/test_mcp_invoke.py`; docs
  `docs/reference/invariants/mcp.md`.
- **Lines removed:** about 2,300.
- **Proof:** `rg -n
  "research_capture|research_get|create_strategy_project|search_evidence|plan_development_suite|launch_ml_experiment"
  apps/alpha-mcp`
  is empty.
- **Tests:** `tests/integration/test_mcp_server.py`, `tests/integration/test_mcp_front_door.py`,
  `tests/unit/test_mcp_*.py`.
- **Baseline:** none. **Cards:** `ai-tools-connection`: drop the proof
  `test_research_mcp.py::test_research_mcp_capture_propose_status_and_report_round_trip`.
- **Protected:** none. **Risk:** low.

### Step 5: `alpha suite`

- **Branch:** `chore/m144-remove-suite`
- **Files:** `suite_cmds.py`, `_suite.py`, `_suite_actions.py`, `_suite_types.py`, `suite_catalog.py`;
  `main.py:40`; `catalog.py:43`; `ControlStore.create_suite_job` stays dead until step 11; tests
  `tests/unit/{test_suite_planner,test_suite_executor,test_suite_plan_golden,test_suite_plan_builders,test_suite_catalog}.py`,
  `tests/integration/test_suite_cli.py`; edit `tests/unit/test_cli_entry_lazy_groups.py`; docs
  `cli-runs.md` suite part.
- **Lines removed:** about 5,600 (2,742 source, 2,876 tests).
- **Proof:** `rg -n "_suite|suite_cmds|suite_catalog|\"suite\"" apps scripts workers --glob '!*.md'`
  returns only deleted files.
- **Tests:** `tests/unit/test_cli_entry_lazy_groups.py`, `tests/integration/test_control_cli.py`,
  `scripts/gate.py check`.
- **Baseline:** none listed. **Cards:** delete `strategy-development` (lines 349-371).
- **Protected:** none. **Risk:** low.

