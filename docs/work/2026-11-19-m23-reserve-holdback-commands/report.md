# Report: More commands hold back the reserved period

## Covered

`alpha optim grid` and `optim mcpt`, `alpha validate`, `alpha backtest oos`, `run`, `portfolio` and `cross-sectional`, `alpha scan run`, `alpha rules explain`, `alpha lookalike`, `alpha unusual`, and `alpha labels barrier`.

The helper is `Hold` and `hold` / `hold_many` in `apps/alpha-cli/src/alpha_cli/spine/reserve.py`. It adds no second copy of the date, cut-off or sentence. It stayed under `spine/` because `lint-imports` still passes (13 kept).

## Left, with the reason

- Hypothesis scan: the spec and its hashes are frozen, and the crypto lane has its own loader. It needs its own change.
- ML input (`ml_input.py`): tied to a project's frozen export.
- Forecast: a forecast run is forward use; the evaluation sites need their own design.
- Research diagnostics: tied to research cases and their sealed holdout.
- `alpha backtest run --manifest-id` (bulk archive): not held back; the archive count is not built.
- `alpha backtest holdout`: it is the revealed holdout itself.
- `alpha propfirm`, research case runs: not in this task's order or exempt.

## Cautious readings

- `alpha scan check` is the alert watcher. It is forward use, so it still reads the latest bars. `scan run` and `rules explain` hold back.
- The earlier of the user's `--as-of` and the cut-off wins. A user cut-off before the reserved day holds nothing back and keeps its own record.
- Loaders always get the cut-off, so a split or dividend known from the date on is not applied, even when no bar is held back.
- Sentence goes to stdout in text output; for `lookalike`, `unusual` it goes to stderr so `--json` stays clean.
- Old stored results of these commands carry no `reserved-period-seen` label: they have no label mechanism.

## Tests

`tests/unit/test_reserve_holdback_commands.py`. Fail first: the first run, with the source change stashed, failed at the optim case with `assert (... and False)` on the latest bar read, 2024-05-18.
