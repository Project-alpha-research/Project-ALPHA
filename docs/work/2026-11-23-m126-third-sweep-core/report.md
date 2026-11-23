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

## 6. Progress while `alpha test` runs
- Cause: `alpha test` had no heartbeat.
- Change: it prints the expected time first (240 s per asset, a quarter of that with `--quick`), then the existing `heartbeat` helper prints a line about every 10 seconds naming the stage ("testing SPY (1 of 2)"). `heartbeat` now accepts a label function; `run_idea` takes an optional `stage` callback. Lines go to stderr; stored runs are unchanged.
- Test: `tests/unit/test_m126_counts_bridge.py`.

## 3. Price chart
- Cause: fixed marker sizes (26, then 9 past 60 fills) and always a linear price axis.
- Change (`figures/_price_signal.py`): marker size falls smoothly with the fill count (never under 10). Past 200 fills, every k-th fill is drawn and the caption says "every kth of N fills drawn". A span over five years (and all lows above 0) gets a log price axis, named in the axis label. Look unchanged: white, standard matplotlib.
- Decision: no zoomed second panel. All panels of a figure share one x-axis in `alpha_research.figures` (protected), so a last-two-years panel cannot be drawn. The brief allowed thinning instead.
- Test: `tests/unit/test_figure_pack.py` (three new tests).

## 7. Small wording
- a. Cause: raw metric name and two unrelated counts. Change: `GLOSS` in `results_summary.py` explains "inverted sharpe"; when flags and flagged checks both show, one sentence says they are counted apart. Test: `test_m126_wording.py`.
- b. See item 7b above.
- c. Cause: the money axis never named the account. Change: `trade_pnl` caption says "account size assumed: N" from `metadata.starting_cash`, or "account size not stored in this run" (never a made-up number). In the caption, because a longer answer text left the figure. Test: `test_figure_pack.py`.
- d. Cause: a stored data-health sentence and one toolbox hint said `uv run alpha`. Change: the toolbox hint says `alpha`; `emit` prints `alpha` for any `uv run alpha` in screen text. The stored sentence is not changed (a setup study stores it and its pinned hash must stay). Test: `test_m126_wording.py`.
- e. Follow: the refusal now says `--test` wants the id in the RUN column and where to find it. Tool: `alpha tool run <tool> --run <id>` works; exactly one of the two forms. Test: `test_m126_wording.py`.
- f. `alpha idea new "text"` takes the bare text as the claim (an error when `--claim` is also given). The saved hint names `--idea-card`. Test: `test_m126_wording.py`.
- g. Cause: callout boxes were drawn inside the plot. Change: pattern pictures mark points with letters; the notes sit under the plot. The shared `ps.callout` helper is unchanged (other figures use it). Test: `test_chart_pattern_picture.py`.

## Not done / notes
- `docs/reference/commands.md` is not regenerated (the brief forbids it); `alpha idea new` and `alpha tool run` options changed, so it is stale.
- Item 1: `forecast`, `propfirm` and `data` read bars by symbol and fail loud on a short name; they never print a false "nothing tried", so I left them.
