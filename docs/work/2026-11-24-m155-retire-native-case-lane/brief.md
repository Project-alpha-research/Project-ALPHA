# Brief: retire the native research-case lane (plan step 7)

Branch: `chore/m155-retire-native-case-lane`. Start from `origin/main` (if the branch exists on origin, continue from it).
Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first), and the first three paragraphs of
`docs/work/2026-11-24-m143-remove-research-case-mcp-and-suite/brief.md` on branch `work/m102-briefs` (what never to delete, the
protected paths, the import-linter forbidden list, the checks before the pull request, the short task `brief.md`, the report).
They apply here unchanged. This is a DELETION change from the owner-approved removal plan (owner decision 2026-11-23, logged in
`docs/reference/project/owner-decisions-6.md`); the earlier steps are already on main. The plan text for this step is copied
below; line numbers in it are from an older main, so find each item by name. Delete exactly what it lists; prove "no caller"
with the searches it gives and put the proofs in `report.md`. If a listed file has another caller, KEEP it and say so.

The gate in the plan (questions Q1 and Q2) is passed: the owner said yes to retiring the three cards and to dropping the paper
link. Protected files in this step: `workers/rdagent/qualify_daily_container.py`, `scripts/inspect_daily_rule_history.py` and the
`qualify_daily_container` line of `scripts/setup_rdagent.sh`. The owner approved these three, but you do NOT edit them: the
orchestrator adds that commit at review. Do not touch any other file under `workers/`. RD-Agent's prompts, memory, judge and the
`alpha rdagent` commands are kept features: change nothing in them. This step is large: commit and push after each group of
files (CLI, web, frontend, tests, docs) so the work survives a restart.

Find a module fast: `uv run python scripts/fs.py map apps/alpha-cli --find WORDS`. At the end of your report add one line:
"What the file system got wrong:" with any routing row or page that misled you (or "nothing").

Lesson from the step before this one: a test can call a removed command by its words, not by an import, so the import search
misses it and main breaks after the merge. Also search `tests/` for every command word you remove, for example
`rg -n '"(project|evidence|native-result|suite)"' tests`, and for every deleted module name in strings. Fix or delete each
test you find (a test of a removed command goes with it; a test of a kept feature must keep passing), and remove deleted
tests from every proof list in `docs/roadmap/capabilities.toml`.

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

### 3.2 Web backend (`apps/alpha-web/src/alpha_web/`)

| Unit | Lines | Decision | Step | Proof |
|---|---:|---|---|---|
| `api/research.py` 515 (24 routes), `_research.py` 425 | 940 | DELETE | 3 | frontend callers go in step 2 |
| `api/development.py` 555 (projects, suite, evidence, `/development/jobs`), `_development.py` 793 | 1,348 | DELETE | 3 | `/development/jobs*` is called only by `V3Workbenches.tsx` (unmounted); the job monitor uses `/api/jobs` |
| `api/models/{projects 562, research_cases 558, research_gates 227, research_hub 177, semantic_reads 111}` | 1,635 | DELETE; drop their re-exports in `api/models/__init__.py` | 3 | only each other and `api/models/__init__` |
| `run_authority.py` 63 | 63 | KEEP the `standalone_sandbox` branch; delete the `governed_project` branch (lines 34-63) | 3 | `api/jobs.py:21,57` |
| `api/crypto_data.py:280-297` register route and its two models | ~40 | DELETE (it calls `research data register-crypto`) | 3 | frontend `cryptoSnapshotRegister` (`CryptoDataCenter.tsx:420`) goes in step 2 |
| `api/v3.py` clone of development routes | ~20 | DELETE the development part | 3 | `api/v3.py` imports `api.development` |
| `api/owner_auth.py` 320 | 320 | DELETE | 8 | Governance window (other builder) |
| `api/workspaces.py`, `_workspaces.py`, `api/models/workspaces.py` | 209 | other builder (Saved workspaces) | – | not in this plan |
| `_native_results.py` 267, `api/native_results.py` 38, `api/native_result_models.py` 149, `api/runs.py:80-100` daily-rule-evidence route | ~475 | DELETE after Q1 | 7 | card 8 reader; card 9 report |

### 3.3 Workstation frontend (`apps/alpha-web/frontend/src/`)

Already unmounted (not reached from `main.tsx`): `EvidenceHub` 693, `ResearchCockpit` 1,249,
`researchCockpitModel` 503, `ResearchBacklog` 121, `researchBacklogModel` 33,
`researchHeadlineModel` 54, `researchViews` 100, `Pipeline` 225, `StrategyLab` 297,
`V3Workbenches` 1,008 (holds the unmounted MlResearch and AssetMemory panes; the live ML window is
`MachineLearning.tsx`), `durableJobs` 58, `components/OwnerActionButton` 98,
`components/ResearchGateLockNotice` 32, `shell/projectContextModel` 31. DELETE in step 2.

Mounted, need an edit in step 2: `DataManager.tsx` (drop the research-data tab; then delete
`ResearchDataExplorer` 171 and `researchChipModel` 43), `shell/MarketDesk.tsx` (drop
`DeskNotes` 45, research notes), `KronosStudio.tsx:38` (drop the linked-project lookup; Kronos
stays), `shell/Toolbar.tsx:12,105` (drop the project gate; then delete `useLinkedProjectGate` 51),
`rundetail/index.tsx`, `shell/statusModel.ts`, `useSelectedRunWatermark` 29 (drop the research-gate
watermark; then delete `researchGateModel` 37), `CryptoDataCenter.tsx:420` (drop the register
button), `api/client.ts:545-735` (about 45 old functions).

After Q1 (step 7): `DailyRuleReport.tsx` and its test, `NativeJobResult.tsx` 65,
`nativeJobResult.css` 7, `api/nativeResults.ts` 60, `rundetail/index.tsx` (drop the daily report
tab), `e2e/daily-rule-report.spec.ts`, `e2e/native-result-real.spec.ts` (673 lines in all).

### 3.8 Tests, docs, skills, cards

Listed per step in §5. Kept test families: `test_reserved_slots`, `test_durable_job_lease`,
`test_web_ml`, `test_web_api_jobs`, `test_mcp_server` (job and data parts), `test_native_tearsheet*`,
worker tests `test_native_loop_conformance`, `test_native_stock_worker_contract`,
`test_daily_rule_costed_worker` (their worker files stay).

Worker files `workers/rdagent/{native_fixture,fixture_entry,fixture_owner,stock_fixture,stock_fixture_entry,daily_container_entry,install_rule_profile,install_stock_profile,admitted_probe,costed_probe,rule_probe,conformance}.py`
become unreached from ALPHA after step 7. This plan does **not** delete them: they are RD-Agent
worker files under `workers/**`. They need their own owner decision.

## Plan text: the step
### Step 7: the native RD-Agent lane (cards 8, 9, A)

- **Branch:** `chore/m146-retire-native-case-lane`
- **Files:** §3.1 native rows; `research_analysis_plan.py:191-200`; `report_cmds.py` daily branch;
  web §3.2 native rows; frontend §3.3 step-7 list; `main.py:80-84` (`native-result` mount);
  `workers/rdagent/qualify_daily_container.py` (233); `scripts/inspect_daily_rule_history.py` (32);
  the `qualify_daily_container` line in `scripts/setup_rdagent.sh`; tests
  `tests/unit/test_native_*.py` and `tests/unit/test_daily_*.py` except `test_native_tearsheet*`,
  `test_native_loop_conformance`, `test_native_stock_worker_contract`,
  `test_daily_rule_costed_worker`; plus `tests/unit/{test_qualify_daily_container,_native_phase_capture}.py`,
  `tests/integration/test_daily_rule_report.py`, `tests/smoke/test_rdagent_smoke.py`; docs
  `docs/reference/invariants/cli-native.md` (136), `docs/roadmap/rd-agent-in-alpha.md`,
  `docs/operations/storage-settings.md` (daily study parts), ADR-0048 status note.
- **Lines removed:** about 27,000 (about 8,035 CLI, 475 web, 673 frontend, 265 worker and script,
  about 17,800 tests).
- **Proof:** `rg -n "_native_(fixture|rule|daily|stock|loop)|native_supervisor|native_stock|daily_native|daily_rule_report|qualify_daily_container|native-result|daily-rule-evidence" apps scripts workers --glob '!*.md'`
  returns only deleted files and the kept worker files of §3.8.
- **Tests:** `scripts/gate.py check`; `tests/smoke/test_rdagent_model_gateway_smoke.py`;
  `alpha rdagent run --dry-run` and `alpha info` on a copy of real data.
- **Baseline:** remove `_native_fixture_store.py::_events`, `_native_rule_completion.py::complete_rule_trial`,
  `daily_native_cmds.py::run_daily_deep`, `daily_rule_report.py::daily_rule_evidence`.
- **Cards:** delete `native-job-result`, `daily-rule-study`, `qlib-in-research-cases`; add a
  `[[decision]]` row for the retirement; `ai-stock-research`: drop the `native-result` and
  `native_supervisor` entry points and the two native smoke proofs. Update decision C's comment.
- **Protected:** `workers/rdagent/qualify_daily_container.py`, `scripts/inspect_daily_rule_history.py`,
  `scripts/setup_rdagent.sh`: **owner yes**. `scripts/gate_test_durations.json` loses entries (generated).
- **Risk:** medium. A named RD-Agent card goes: only with Q1. RD-Agent prompts, memory, judge and
  `alpha rdagent` are not touched.

