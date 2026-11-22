# Report: toolbox family G, parameter and specification robustness

Result: 11 checks are built. Each one re-runs the engine with one thing changed. Every re-run is a try in the one trial ledger.
The target was 9. No check from the brief is left out.

## The checks

Each check gives a reading: numbers and a sentence. None gives a pass, a fail or a "best" setting.
The try counts are for a classic rule with two settings (for example `ma_cross` fast 5, slow 20) at the default settings.

| Check id | What it re-runs | Tries it adds |
|---|---|---|
| `parameters.one_at_a_time` | Each setting alone at 0.5, 0.8, 1.2 and 1.5 times (whole bars; refused values left out) | up to 8 (owner rule: up to 16) |
| `parameters.plateau` | The first two settings on a grid: `quick` 3 x 3 at 0.8 to 1.2 times, `full` 5 x 5 at 0.6 to 1.4 times | 8 (`full`: 24) |
| `parameters.neighbour_stability` | Each setting at 0.8 and 1.2 times (the stored diagnostics' neighbours) | up to 4 (owner rule: up to 8) |
| `parameters.worst_neighbour` | The same nearest settings | as above; 0 if `neighbour_stability` ran first |
| `parameters.entry_delay` | Entries 1, 2 and 3 bars later; exits as the rule says | 3 |
| `parameters.exit_delay` | Exits 1, 2 and 3 bars later; entries as the rule says | 3 |
| `parameters.skip_entries` | 10%, 20% and 30% of entries skipped, seeded, `copies` each (default 10) | 30 |
| `parameters.cost_ladder` | Fees and slippage at 2, 3 and 5 times, re-filled by the engine | 3 |
| `parameters.start_date` | The test started 3, 6 and 12 months later | up to 3 |
| `parameters.inversion` | The opposite rule (`controls.run_inverted_backtest`) | 1 |
| `parameters.price_noise` | 50 copies of the bars with seeded noise (`price_noise.noisy_bars`) | 50 |

A re-run already in the ledger adds no try, from the same check or from another one. Through `alpha tool run`, the same check on
the same run is the stored reading and adds nothing.

## What was built

1. Loader. A check may declare the input `run_rerun`. `inputs.load_rerun` reads the bars and dividends at `reserve.CUTOFF`, as
   `alpha test` does, up to the run's last bar. It checks them against the stored data fingerprint. On a mismatch it refuses
   with `RUN_DATA_CHANGED` in plain words. It gives the idea spec, the run spec and the full-sample result too. The cache key
   of such a check holds `data_fingerprint`. The read is proven cut by `tests/unit/test_research_reads_are_cut.py`, so the
   guard needed no new entry. `load_run` keeps its own read and its existing entry.
2. One re-run path (`parameter_robustness_common.py`). Variants come from `diagnose.variant_specs` (new `factors` argument) and
   `owner_variants` (new `factors` argument and `owner_grid`). They run through `price_noise.engine_runs` and
   `_runner.run_full_backtest`. A spawn pool is used only when the runs would take more than 20 seconds one at a time.
3. Delays and skips. `run_full_backtest` takes an optional `signal_filter`. It wraps the built strategy's own `_signal`, so
   the rule still decides on each close and the engine fills at the next open. The filter reads no later signal (a test
   flips every later signal and checks the earlier output).
4. Tries. Before any engine run, each re-run is appended through `append_trial`, as a `screen_trial` row (the existing kind
   for a try with no Sharpe ratio). The same-asset try count reads these rows, so later deflated Sharpe ratios count them.
5. Progress. Each check prints, before it starts, how many engine runs it makes and about how long they take. It prints a line
   every 10 seconds while they run. The lines go to standard error, so `--json` output stays clean.

## Decisions

- Try rows use the existing `screen_trial` kind, with the extra fields `tool` and `of_run`. A new kind would need changes to the
  ledger reader and to the deflation count. The spec hash is the idea spec, the run spec and the signal change. So the same
  re-run from two checks counts once.
- A repeat is not appended at all. The brief says it "adds nothing". The screen path appends a row labelled `repeat` instead.
- Diagnostics price-noise copies are labelled "controls, not trials". The brief says every re-run is a try, so the price-noise
  check counts its 50 copies.
- Too little to read: fewer than 10 closed trades in the full-sample run. Nothing is run and no try is added.
- `plateau` leaves the chosen point out of the share. "Within 20%" means a Sharpe ratio within a fifth of the rule's own.
- Delays and skips are causal changes to the rule's signal, not a second strategy. Exits from a delayed entry stay on time. A
  trade shorter than the delay is never entered.
- `parameters.price_noise` answers the situation "Would a slightly different data feed change the answer". Until now that
  situation had no check and pointed to `alpha data health`. I moved that case of
  `test_situations_without_a_check_point_to_the_command_that_answers` into the owner-words test, which now expects the check.
- `cost_ladder` does not carry the `real-fills` tag itself: `situations.QUESTIONS` sets that tag, and a test requires it.
- Two new situations: "Does the result depend on the exact settings" and "Does the result need perfect entry or exit timing".
  New find words: parameter, setting, sensitive, robust, plateau, neighbour, tweak, delay, timing, late.
- Readings write numbers such as 0.5, 20% and 12 months as words. The citation check refuses an untagged number.
- Commits end with the session's own `Co-Authored-By` line, not the one in the common rules. That line names another model.

## Tests and fail-first evidence

`tests/unit/test_toolbox_parameter_robustness.py` has 43 tests. Each check has a known-answer test, a too-little-data case and a
repeat-is-identical case. There is one tries-are-counted-once test through the runner. Known answers:

- A stand-in engine that gives the rule's own equity for every setting gives a flat sensitivity, a whole plateau and full
  neighbour agreement.
- Engine runs: each delayed entry is an original trade one bar later with the same exit. Skipping no entry reproduces the
  equity exactly. Costs at 2 times equal the stored diagnostics' `costs_x2` variant on a real `alpha test` run. A later start
  equals a full-sample run on the later bars. The opposite rule equals `run_inverted_backtest`.

The tests were written next to the code, not before it. Evidence that they catch faults:

- Repeat rows: the first version appended a `repeat` row for each repeat. The repeat test failed (`assert 16 == 8`). I then made a
  repeat append nothing.
- Breaking `EntryDelay` (one bar short): 2 tests failed.
- Dropping the cut at the run's last bar in `load_rerun`: the poison test failed.

`tests/unit/test_toolbox_contract.py` now gives re-run checks a synthetic re-run input. All 11 pass the shared contract test.

## Checks before push

- `uv run lint-imports`: 13 kept, 0 broken.
- `uv run python scripts/gate.py check --base origin/main`: run before the push.
- These tests also fail on `origin/main` without this change. They are not from this change:
  `test_filesystem_contract.py` (`web-frontend.md` is 204 lines; `components/toolbox.md` is over its size; older task folders
  have no brief), `test_ci_backend_bootstrap.py`, `test_assistant_cleanup.py` and `test_native_daily_rule_lifecycle.py`.

## Not done

- `docs/reference/project/components/toolbox.md` is already over its size limit on main. I did not add to it. The new section
  is in `docs/reference/invariants/cli-toolbox.md`.
- I did not run `fs.py verify`, as the common rules say.
