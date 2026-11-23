# Brief: remove the research-case screens and web routes (plan steps 2 and 3)

Branch: `chore/m141-remove-research-case-screens-and-routes`. Do step 2 first, commit and push; then step 3.
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


## Plan text: the steps
### Step 2: Workstation screens and client calls (leaves)

- **Branch:** `chore/m141-remove-research-case-screens`. Start after the other builder's
  Governance/Workspaces/Watchlist/Risk PR merges (same `client.ts`, `generated.ts`).
- **Files:** §3.3 unmounted list; the mounted edits in §3.3; tests
  `panels/{researchCockpitModel,ResearchCockpitRender,researchBacklogModel,researchHeadlineModel,researchGateModel,durableJobs}.test.ts`.
- **Lines removed:** about 5,800 (4,878 screens, 766 tests, about 190 in `client.ts`).
- **Proof:** `rg -n
  "ResearchCockpit|EvidenceHub|ResearchBacklog|V3Workbenches|StrategyLab|Pipeline\b|useLinkedProjectGate|researchGateModel|DeskNotes|ResearchDataExplorer|OwnerActionButton|cryptoSnapshotRegister"
  apps/alpha-web/frontend/src`
  is empty; `rg -n "api/research|api/projects|api/evidence|api/development|research-gate-overrides|stage-links"
  apps/alpha-web/frontend/src --glob '!generated.ts'`
  is empty; `python3 tsgraph.py src` reports no new unreached file.
- **Tests:** `npm run lint -- --deny-warnings`, `npm run build`, `npm run test:coverage`,
  `npm run test:e2e:built`; open Kronos, Data Manager, Market Desk, a run report in the browser.
- **Baseline:** none. **Cards:** edit `entry_points` of `research-cases`, `literature`,
  `paper-to-experiment`, `strategy-development` (drop the panel lines).
- **Protected:** none. **Risk:** low. Kronos, Data Manager and run report lose only research-case
  overlays.

### Step 3: web routes

- **Branch:** `chore/m142-remove-research-case-routes`
- **Files:** §3.2 rows for step 3; `app.py:39,51,145` and the router lines; `api/models/__init__.py`;
  `frontend/openapi.json`, `src/api/generated.ts`, `docs/governance/capability-authority-matrix.md`
  (regenerated); tests
  `tests/integration/{test_web_api_research,test_web_api_development,test_web_api_suite,test_web_project_workspace,test_web_retained_project_fixture}.py`,
  `tests/unit/{test_web_research_projection,test_web_project_lineage}.py`; edit
  `tests/unit/{test_run_context_authority,test_v3_release_coverage,test_v3_surface_coverage}.py`;
  docs: delete `docs/reference/invariants/web-research.md` (74), edit `web-workstation.md`.
- **Lines removed:** about 6,300 (about 3,950 source, 2,328 tests), plus generated files.
- **Proof:** `rg -n
  "alpha_web\.(_research|_development)|api\.(research|development)|research_cases|research_gates|research_hub|semantic_reads|models\.projects"
  apps tests`
  returns only deleted files; `rg -n '"research", "data", "register-crypto"' apps` is empty.
- **Tests:** `tests/integration/test_openapi_safe_routes.py`, `tests/integration/test_web_api_*.py`,
  `tests/unit/test_web_*.py`, `scripts/gate.py component frontend`.
- **Baseline:** none. **Cards:** drop `api:` lines of `research-cases`, `literature`,
  `paper-to-experiment`, `strategy-development`. **Protected:** none.
- **Risk:** low. `/api/jobs` keeps working (standalone context only).

