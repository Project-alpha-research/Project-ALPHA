# Report: a plain path to a Qlib model (m111)

Answer: `alpha ml run <spec.toml>` now goes from a plain spec to a stored, costed replay run. It needs no project and no experiment.

## What was built
- `apps/alpha-cli/src/alpha_cli/ml_run.py` (new). The command `run` is in `ml_cmds.py`.
- Spec keys: `assets` (required), `name`, `features` (`alpha158`), `horizon_days` (`1`), `model` (`lightgbm`), `[split]` (`train_days`, `validation_days`, `test_days`; defaults 504 / 120 / 63).
- Example `research/examples/ml-gbm-etfs.toml`; tool card `research/tools/ml-model.md` (26 lines); README row; `cli-ml.md` text.
- Tests: `tests/integration/test_ml_run.py` (7 tests, the repo's real `fake` worker, synthetic bars).

## Worker calls reused (unchanged)
1. `ml_input.export_input` (reads are cut by `reserve.hold_many`).
2. `ml_contract.prepare_exchange` with the worker `uv.lock`.
3. `uv run --project workers/qlib --locked --no-sync alpha-qlib-worker <mode> <exchange> --worker-lock <lock>` and `validate_result_bundle`. I moved the body of `alpha ml train` into `ml_cmds.train_exchange` so both commands share it. `train` behaves as before. `workers/**` is untouched.
4. `_ml_replay.run_ml_replay` (engine replay with costs; stores a v3 run).

## Decisions
- Snapshot: the spec names no snapshot. The command freezes the stored bars into `ml-<hash of bars>` and reuses it when the bars are equal. It copies the pull source from the stored provenance, and refuses assets with no or mixed provenance.
- Label horizon: the worker and the contract accept only 1 day. Any other value fails with a plain message. I did not edit the protected worker.
- Model and features: only `lightgbm` and `alpha158` (version 1, the default) exist; others fail loud.
- Costs: fixed 1 bp fee and 2 bp slippage (no option was named). They are shown in the output and stored in the manifest.
- Seed: fixed 7 (existing default).
- Reserve: `export_input` holds back bars from 2024-01-01; the output carries `reserve_sentence`. The split is stated in `split_sentence`; test days come after train, validation, purge and embargo days.
- Ledger: one row `kind=ml_run`, family `qlib` (`trial_record._spine`), keyed by run id. The same spec on the same data is "counted before". The row does not count toward deflation of rule tests, like screen tries.
- Missing worker: "The Qlib worker is not installed ... Run once from the repository folder: bash scripts/setup.sh".
- Re-run: the work folder is `data_dir/ml_runs/<hash>/`; a finished one is reused and only the (idempotent) replay runs again. A failed run removes its folder.
- Not regenerated, per the brief: `docs/reference/commands.md`, `STATUS.md`, `docs/roadmap/README.md`. `commands.md` is now stale for the new `run` command.

## Review round 1 (Codex findings and CI)
- CI `quick` failed: two tests needed the worker `.venv`, which CI does not have. They now run the repo's fake worker through `PYTHONPATH` (as `test_ml_cli.py` does) and stub `train_exchange` and the install check. I removed the internal `mode` argument.
- Fixed: the snapshot key now hashes bars, corporate actions and provenance (test: a changed actions file gives a new snapshot).
- Fixed: the output now lists every rolling fold and says the model was refit N times, each on days before its own test days.
- Fixed: the finished-run cache key now includes the worker `uv.lock` hash.

## Review round 2
- Fixed: non-repeat `ml_run` rows now count in the `qlib` family total (`counts_for_deflation`); other families are unchanged because deflation filters by family id. Test: `reader_trials == 1` after a run and its repeat.
- Fixed: each run key builds under an exclusive file lock (`ml_runs/<key>.lock`), so a second run waits and then reuses the finished exchange. I did not write a true two-process race test; the test only checks reuse and the lock file.

## Review round 3
- Fixed: the snapshot id is the hash of its own bytes. A snapshot is reused only if its files hash to its id; a new one that does not (the store changed while copying) is removed and the run stops with "run the command again". Test: a tampered snapshot is refused.
- Fixed: `--as-of` now reaches the replay, so the stored manifest keeps `research_cutoff`. Test: `--as-of 2023-06-30` is in the manifest and the last test day is not later.

## Fail-first evidence
I wrote the tests before `ml_run.py`, but I did not run them before the module existed. The first run against the new code failed on a too-short fixture (728 sessions before the held-back day; 756 needed). I lengthened the fixture and all 7 passed. This is weaker than a true red run.

## Old project/experiment path versus this path
The old path (Workstation, `alpha ml export-input --spec`, then `prepare`, `train`, `replay`) stores the experiment spec as a control record, binds a project and experiment id, uses a snapshot the owner made, and lets the owner pick model parameters, feature version 1/2/3, rank-ensemble, costs, seeds, point-in-time membership and several folds by hand. The plain path:
- creates no project, experiment, control-store record, job or capacity slot;
- creates its own snapshot instead of using a named one;
- fixes costs, seed, feature version 1 and membership `current_membership` (with the survivorship warning);
- offers one model, a 1-day horizon and one split;
- runs the worker in the foreground with `--no-sync` and a 2 h limit.

## Known gaps
- `alpha results` lists rule tests only. I did not check that `alpha report` or the figures read an `ml_replay` run; `alpha ml replay` already produced the same kind of run before this change.
- PR #392 was not on main; I merged `origin/chore/m101-no-project-ids` into this branch.
- `gate.py check --base origin/main` passes in full after review round 1.
