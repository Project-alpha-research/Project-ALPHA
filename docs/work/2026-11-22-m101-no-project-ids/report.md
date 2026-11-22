# Report: ML, forecast and crypto-data commands no longer need a project or a case

Branch `chore/m101-no-project-ids`. Lines (excluding generated files): 339 added, 1397 removed.
Generated files (OpenAPI, `generated.ts`, `commands.md`): 94 added, 251 removed.

## Commands

| Command | What it needed | How it works now |
|---|---|---|
| `alpha ml export-input` | `PROJECT_ID EXPERIMENT_ID`, read through `ControlStore.get_project` | `alpha ml export-input OUTPUT --spec FILE [--as-of]`. The file is one JSON object (snapshot_id, universe, split_policy, costs, seeds, stage_config), at most 1 MB. The summary no longer has `project_id` or `experiment_id`. Reads stay cut through `reserve.hold_many`. |
| `alpha forecast eval` | `--project-id` and `--experiment-id` (governed calibration from a project experiment) | Both options removed. It writes its run like any other stored run. |
| `alpha crypto-data acquire` and the in-process backfill call | `--case-id`, `--expected-case-revision`, `--reason`, and a case lookup for derivative trades and books | The three options and the lookup are removed. Derivative trades and books work on the data home alone. |
| Web ML lab (`/api/ml/experiments/preflight`, `/api/ml/experiments`, `/api/ml/inputs/generate`) | `project show` for the experiment and the research gate | The routes take a `spec` object. The server stores it as `control/ml/specs/<sha256>.json` and passes `--spec`. The screen has a spec box and a "Check spec" button. The preflight is now `POST`. The "experiment" and "research_gate" checks are gone. The screen no longer calls `project show`. |
| Web Crypto Data Center | case id, case revision and reason fields | Fields removed from the request, the route and the screen. |
| Suite planner (`qlib` action) | passed project and experiment id to `ml export-input` | Writes the experiment as `control/ml/specs/<id>.json` and passes `--spec`. |

## Decisions

1. `forecast eval --experiment-id` needs a project experiment, so it went with `--project-id`. That removes the "governed calibration" branch of `forecast eval`: about 310 lines in `forecast_cmds.py` (`_experiment`, `_governed_contracts`, `_calibrated_artifacts`, `_write_json_artifact`, the sample columns of `origins.parquet` and the `governed_*` manifest keys), plus two tests. The plain run is unchanged. `alpha_research` and `alpha_validation` stay untouched (protected); their calibration contracts are now unused by the CLI.
2. `CryptoAcquisitionScopeV1` is deleted (contracts, storage, ingestion, CLI). Nothing else needed it. Old manifests that carry an `acquisition_scope` key still verify, because the key is only data. The rule "unscoped derivative data cannot enter a governed snapshot" is gone with it.
3. `--expected-case-revision` and `--reason` on `crypto-data acquire` only fed the case scope, so they were removed as well.
4. The ML spec is the experiment dict as before; no new option was added.

## Golden pins

`tests/fixtures/suite_plan_golden.json`: the `qlib` digest changes because the export step now has `--spec` and the managed-spec marker. `paper_preflight` was already stale on `origin/main` (the test failed there before this change); regenerating the file also refreshed it.

## Fail-first evidence

The tests were changed with the code in the same commits; I did not run a separate red step for each. The old tests failed on the new signatures before I edited them (for example `export_project_input` missing, `--spec` unknown, 422 "spec required" on the web routes).

## Still tied to projects or cases

- Web ML jobs still go through `alpha project job-create` and `job-status` (the durable job journal). They are created with no project id. Other ML actions (train, import, replay) still take an optional project id for job scope.
- `launch_ml_experiment` / `plan_ml_experiment` in `apps/alpha-mcp` (protected) pass a project and experiment id to the suite planner. They keep working through the suite change above. That is the one place a project id still reaches `ml export-input`'s input, and it is not blocked.
- No worker (`workers/**`) and no MCP tool passes a project or case id to `forecast eval` or `crypto-data acquire`: nothing is "blocked by a protected file".
- The suite planner now writes one small file at plan time (`control/ml/specs/<id>.json`) when the plan has no blockers.
- `docs/reference/invariants/cli-crypto-data.md` still mentions the Binance one-minute research selection bound to a case revision; that command was not in scope.
- The capability labels `case_bound_*` in `alpha_data/crypto/capabilities.py` are unchanged (they are stored strings).

## Checks

- `uv run python scripts/gate.py check --base origin/main`: passed.
- `uv run lint-imports`: 13 kept, 0 broken.
- Frontend: `tsc -b`, `vitest` (873 passed), Playwright specs for ML, crypto data and project context (chromium-wide) passed.
- `tests/unit/test_code_size.py`, `test_research_reads_are_cut.py`, `test_follow_separation.py` pass; no baseline entry needed lowering.
- Not run: `fs.py verify` (as ordered); `STATUS.md` was not regenerated (no change).
