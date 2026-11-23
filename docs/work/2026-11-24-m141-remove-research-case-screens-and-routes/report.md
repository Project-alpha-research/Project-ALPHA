# Report: remove the research-case screens and web routes (m141)

## Lines removed (against `origin/main`, generated files excluded)
- Workstation source (`frontend/src`): about 6,700 lines. Python web source (`alpha_web`): about 4,100 lines.
- Python tests: about 2,700 lines. Browser test support (`e2e/support/workstationHarness.ts`): about 1,070 lines.
- Generated files (`openapi.json`, `generated.ts`, the authority matrix, the operation list) were regenerated with their own scripts.
- `STATUS.md`, `docs/roadmap/README.md` and `docs/reference/commands.md` were not regenerated (a later sweep does).

## Step 2: screens and client calls
Deleted: `EvidenceHub`, `ResearchCockpit`, `researchCockpitModel`, `ResearchBacklog`, `researchBacklogModel`, `researchHeadlineModel`,
`researchViews`, `Pipeline`, `StrategyLab`, `V3Workbenches`, `durableJobs`, `OwnerActionButton`, `ResearchGateLockNotice`,
`projectContextModel`, `DeskNotes`, `ResearchDataExplorer`, `researchChipModel`, `useLinkedProjectGate`, `researchGateModel`, their tests,
and `api/research.test.ts`. About 45 old functions left `api/client.ts`, with the PDF helpers only they used.

Proof (both searches are empty apart from the kept names below):
`rg -n "ResearchCockpit|EvidenceHub|ResearchBacklog|V3Workbenches|StrategyLab|Pipeline\b|useLinkedProjectGate|researchGateModel|DeskNotes|ResearchDataExplorer|OwnerActionButton|cryptoSnapshotRegister" apps/alpha-web/frontend/src`
returns only `openStrategyLab` / `showStrategyLab` (a live action that opens the Ideas window; KEPT) and `generated.ts`.
`rg -n "api/research|api/projects|api/evidence|api/development|research-gate-overrides|stage-links" apps/alpha-web/frontend/src --glob '!generated.ts'` is empty.
A reachability walk from `main.tsx` shows no file that was reached before and is not reached now.

Mounted edits: Data Manager lost the research-case dataset lists; Market Desk lost the Notes tab; Kronos no longer looks up a linked
project (it reads the run it was given); the run report no longer shows the research-gate watermark; the Crypto Data Center lost the
register button and its route.

## Step 3: web routes
Deleted: `api/research.py`, `_research.py`, `api/development.py`, `_development.py`, `api/models/{projects,research_cases,research_gates,semantic_reads}.py`,
the `/snapshots/{id}/register` route and its two models, the development clone in `api/v3.py`, the `governed_project` branch of `run_authority.py`
(a `governed_project` run context is now refused with 422), the re-exports in `api/models/__init__.py`, and `docs/reference/invariants/web-research.md`.
Tests deleted: the five integration files and two unit files the brief names, and `test_web_api_job_cancellation.py` (it only called the removed
`/api/development/jobs` route). Tests edited: `test_run_context_authority`, `test_v3_surface_coverage`, `test_web_api_v3`, `test_web_api_jobs`,
`test_web_api_crypto_data`. `test_v3_release_coverage` needed no edit.

Proof: `rg -n "alpha_web\.(_research|_development)|api\.(research|development)|research_cases|research_gates|research_hub|semantic_reads|models\.projects" apps tests`
now returns only the `alpha_cli` store method `list_research_cases` (not a web module) and generated files. `rg -n '"research", "data", "register-crypto"' apps` is empty.
`/api/jobs` still works with the standalone context.

## Kept, and why
- `api/models/research_hub.py`: trimmed to `ResearchRow` and `ResearchReport`. The reserve guard `tests/unit/test_reserve_research_compare.py` validates the CLI output with them. I did not edit the guard.
- `openStrategyLab`: a live navigation action.
- The Crypto Data Center was reached only through the deleted research-data explorer. I mounted it directly in the Data Manager Quality tab so the data window stays. The "Stored symbols" chips were dropped with the explorer.
- `ProjectSummary` in `navigatorModel.ts` is now a small local type. The Navigator still passes no projects; its empty "Strategies" and "Research cases" folders are unchanged (a later change may drop them).

## Decisions
- The brief names `Toolbar.tsx`, `statusModel.ts` and `useSelectedRunWatermark`. `Toolbar` never used the project gate, and the other two files do not exist. Nothing to change there.
- I also removed code that could no longer compile after the schema left `generated.ts`: `researchCaseRevision` (owner auth), the dataset audit helpers in `researchDataModel.ts`, and the development-stage helpers in `v3Models.ts`, each with its test.
- I pruned the research and project fixtures and routes from the browser test harness. The uncalled `cryptoDataCenterJourney` lost its register steps.
- The import-linter list names only `alpha_cli` modules; none was deleted, so it is unchanged. `lint-imports` is green.
- No code-size baseline entry changed.
- Fail-first: this is a deletion; the proof is that the searches above are empty and the suites that referenced removed code were removed or edited, then run green.
