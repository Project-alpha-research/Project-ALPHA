# Build report: m23-reserve-holdback

## Changed files

Rule tests and setups read only bars dated before 2024-01-01. This is build 1 of the brief (Rules 1 to 8). Rule 9 (the owner's confirmation) is not built.

- `apps/alpha-cli/src/alpha_cli/spine/reserve.py` (new, 82 lines): cut-off, timestamp-only count, record, sentence, `seen`, the Rule 6 refusal, and the carry to study and trade.
- `spine/run.py`: counts held-back bars, passes `as_of` to both loaders, sets `research_cutoff` and `as_of` only when bars were held back, records `spine.reserve`, adds the label, prints the sentence.
- `spine/setup_find.py`: `as_of` on find and reload; refusal at the top of `study_inputs` and `checked_study_inputs`.
- `setup_cmds.py`: find manifest `reserve` block, label, sentence in text output.
- `spine/setup_study.py`, `spine/setup_trade.py`, `spine/setup_trade_figure.py`: carry the find's label and sentence only.
- `toolbox/inputs.py`: `load_run` loads bars and dividends with the run's `research_cutoff`.
- `results_cmds.py`: derives `reserved-period-seen` and a plain sentence when a run is read.
- `spine/check.py`: both labels added to `LABEL_PHRASES`.
- `apps/alpha-web/src/alpha_web/_setup_runs.py`: the two label texts.
- Tests: `tests/unit/test_reserve_holdback.py` (new), one test in `tests/unit/test_web_setup_runs.py`.
- Docs: `reserved-period.md`, `cli-runs.md`, `cli-setups.md`, four tool cards, `capabilities.toml` and generated pages, stamps.

## Cautious readings

- Loaders always get `as_of` = 2023-12-31 23:59:59 UTC, even when no bar is held back. A split or dividend known after that date is then never applied. With no such action the bytes are the same.
- `research_cutoff` in the run identity is set only when bars were held back, so ids for stores that end before 2024 are unchanged.
- The brief says the held-back run id equals the id of a store cut at 2023-12-31. It cannot: the cut-off and the label are part of the identity (Rule 4). The test compares results and the source fingerprint instead.
- The find's `reserve` block is written only when bars were held back, so an old find and a new find with no held-back bars read the same.
- Data health still reads the stored series as before; it is outside this brief.

## Not done

- Rule 9, the confirmation path (second build). No change to `owner_auth.py`, `control_store.py` or `_control_schema.py`.
- All follow-up commands in the brief (optimise, validate, backtest and others).

## Byte proof

`tests/unit/test_spine_honesty_3.py` and `tests/unit/test_setup_trade.py` ran unedited and passed. The legacy run id `3d7c42078dd76b34`, the find id `32d1f3b953038de2` and the trades SHA `b865b7dc…` are unchanged. The N = 0 test shows no `reserve` block, no label and `research_cutoff` None.

## Guard tests

`test_rule_test_and_tool_read_no_held_back_bar[SPY|BTC/USD]`, `test_setups_read_no_held_back_bar[SPY|BTC/USD]`, `test_old_find_that_saw_the_period_is_refused_before_any_bar_loads[study|trade]`, `test_find_with_no_held_back_bars_is_byte_identical`. They failed before the source change (collection error, then behaviour failures with the source reverted). The latest bar each path returned was 2023-12-31 for run, tool load, find, study and trade, on both fixtures. N is 139 for both (1,600 bars from 2020-01-01; 1,461 are dated before 2024).

## Checks

- New tests, the two pinned files, `test_web_setup_runs.py`, `test_spine_report_edges.py` and `test_entry_gap_sizing.py`: 104 passed.
- 30 related test files ran one by one and passed after three fixes the first run showed (lazy import in `setup_cmds.py`, a mock-safe `as_of` call, line length of the tool cards). `test_toolbox_contract.py` drafts now include the phrase "reserved period seen", because `LABEL_PHRASES` requires it.
- `tests/bias_guards`: 207 passed, 4 skipped. `lint-imports`: 13 kept. `fs.py stale`: 0 stale. `ruff`, `mypy`: pass.
- Not run: the full broad `-k` selection finished only in part; it stalled on tests outside this change.
