# Report: m126 third sweep, core path

Decision: the commit trailer names the model that did the work (Sonnet 5.5), not the line the common rules quote.

## 1. Symbol names
- Cause: `ledger tries` compared the typed name (BTC) with the stored name (BTC/USDT) as plain text.
- Change: `typed_symbol` (in `spine/stores.py`) calls `resolve_asset`, the resolver `alpha test` uses. `ledger tries`, `ledger list --asset` and `ledger query` use it and say "BTC is stored as BTC/USDT." A name that is not stored stays as typed.
- Test: `tests/unit/test_m126_symbol_names.py` (failed first: "0 ideas on BTC").

## 2. Labels (and 7b, compare table)
- Cause: only `alpha test` called `label_lines`; the other views printed the bare names.
- Change: `label_block` and `legend_line` (in `spine/label_meaning.py`) now serve `report`, `results show`, `results compare` (block) and `results` list (one legend line under the table).
- Test: `tests/unit/test_m126_labels_compare.py`.

## 7b. Compare table
- Cause: every run had value, diff and ratio columns, each headed with the run id.
- Change: each id prints once; the first run keeps only its value column (no 0.00 / 1.00x). Later runs add "change from first" and "ratio to first". Two old tests changed to match.

## 4. Tries paragraph
- Cause: the paragraph gave three counts with no reason.
- Change: `reading_count_sentence` (the one helper every view calls) now says what each count is and why the all-assets count can be larger. Numbers unchanged.
- Test: `tests/unit/test_m126_counts_bridge.py`; the older count tests still pass.
- Not fixed: `tests/unit/test_code_size.py::test_baseline_entries_are_ceilings` already fails on `origin/main` (three functions are longer than their baseline). I did not touch them or the baseline in `.claude/`, which is protected. Numbers: `forecast_cmds.run` 172 vs 163, `monte_carlo_cmds.kronos` 372 vs 315, `report_cmds.report` 225 vs 219.

## 5. Bridge sentence
- Cause: the reading word came from checks the luck-adjusted number does not show.
- Change: `deciding_sentence` (in `spine/reading.py`) builds "What decided it: ..." from the stored reading's `evidence.because` and `measures`. `reading_text` (test, results show) and `alpha report` print it under the reading. No statistic or stored field changes. Not changed: the toolbox's own "probabilistic Sharpe" screen (no reading is stored there).
- Test: `tests/unit/test_m126_counts_bridge.py`, `test_m126_labels_compare.py`.
