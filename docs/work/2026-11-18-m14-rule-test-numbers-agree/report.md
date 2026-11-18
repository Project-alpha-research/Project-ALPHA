# Build report: a rule test's numbers agree with each other

Answer first: a new rule test stores each headline number with the period it covers, and both
lines of every comparison chart use the same prices and the same dividend rule. Tiles and the
charts beneath them come from the same samples. Old runs stay readable and show "not recorded"
where a number was never stored.

## What changed, item by item

| Item | What was wrong | What is true now | Test |
|---|---|---|---|
| 1. Two periods on one page | Tiles read full-history diagnostics; charts read the scored walk-forward equity. | `spine.periods` stores `full_history`, `tradable` and `scored`, each with dates, price basis, strategy and buy-and-hold total return, return per year, worst drop, Sharpe, trades and the ahead/behind figure. The Summary shows a tradable row and a separate "Scored test periods only" row, each with its own dates, tiles, Sharpe and two charts. | `test_rule_periods_match_rendered_equity`, `test_tradable_numbers_match_a_hand_calculation` |
| 2. Chart contradicted itself | The caption's figure was final strategy growth ÷ passive growth − 1. The panel compounded the bar-by-bar difference of the two returns, on the 5,000 plotted points rather than all sessions. | One definition everywhere: strategy growth ÷ buy-and-hold growth − 1, named on the axis ("Ahead of / behind buy and hold"). Every label (caption, end labels, worst drop) is computed on the full series; only plotted points are sampled, and the worst-drop session is always plotted. One builder now serves old and new runs. | `test_excess_series_matches_caption`, `test_runs_without_period_records_use_the_same_ratio`, `test_rule_drawdown_preserves_full_resolution_extreme` |
| 3. Dividends | The engine credits recorded cash dividends to shares held before the ex-date open, on the first session on or after the pay date (ex-date if none); cash is kept, not reinvested. The old passive line was a price-only open index and the diagnostics used a second, close-price buy-and-hold. A dividend fund's strategy got dividends; its benchmark did not. | `spine/diagnostics.py: buy_and_hold` buys one share at the period's first open (engine price precision) and keeps dividend cash under the engine's exact rule. Both lines say "with dividends" when dividends are recorded; with none, both say "price only, no dividends" and the run carries `benchmark-price-only`. The close-price calculation was deleted. | `test_buy_and_hold_dividend_cash_matches_invested_engine` (engine to 1e-9), `test_rule_without_diagnostics_cites_stored_dividend_benchmark` |
| 4. Headline dates | The headline used the loaded data range. | It says "could trade from … to …" (first open after indicator warm-up); the data range is shown smaller as "data from … to …". | `test_rule_periods_match_rendered_equity`, `RuleTestSummary.test.tsx` |
| 5. Dark stored figures | Stored figures used the dark theme. | New rule tests store all four Summary figures light. `alpha figures render/path/export --dark` makes a separate dark copy with its own cache key. | `test_new_rule_figure_light_and_dark_keys`, `test_run_publishes_four_light_summary_figures` |

## Review fixes after the first build

- The old chart builders (old rule runs, plain validation runs) still drew the compounded panel
  and took the worst drop from sampled points. They now call the period builder. Deleted: the
  old `equity_underwater` and `equity_vs_passive` bodies in `figures/_builders.py`.
- The break-even cost tool (from main) accepted only the price-only line, so it would have failed
  on every dividend run. Both stored-benchmark tools now read one list, `toolbox/inputs.py:
  HOLD_KINDS`. Its gross return and the benchmark both follow the engine's dividend rule.
- The market-exposure tool compares strategy returns with price-only opens; its basis text now
  says so.
- Chart subtitles name the period in plain words ("could trade", "scored test periods only").

## Fields added to stored runs

`manifest.json: spine.periods.{full_history,tradable,scored}`, `tradable_comparison.parquet`,
`benchmark_kind = passive_open_to_open_with_dividends` for dividend runs, the run label
`benchmark-price-only`, and period facts (`tradable_*`, `scored_*`); cited facts carry
`period`, `first_ts`, `last_ts` and `price_basis`.

## Old runs

Run folders are never rewritten. A run without `spine.periods` shows "not recorded" in both
rows and keeps its full-history numbers under "Recorded full history". Its charts use the same
builder, with the buy-and-hold line labelled from its stored kind ("price only").

## Checks

Independent proofs, on synthetic runs made through the real `alpha test` command in a temporary home:

- Always-invested, zero-cost rule on a synthetic fund with 20 cash dividends (one paid five sessions
  after its ex-date, one paid after the data ends). Strategy equity equals `1 + f × (buy-and-hold − 1)`
  to 3e-13 at every one of 1,198 sessions, where `f` is the share of capital invested. So both lines
  receive exactly the same dividends on the same days. The only gap is uninvested cash from
  whole-share sizing (42.80 on 1,000,000), which leaves the strategy 0.004% behind.
- Every tile in both rows (total return, return per year, worst drop, buy-and-hold, ahead/behind)
  recomputed by hand from the stored opens, dividends and equity: largest difference 0.
- Long moving-average run, 8,300 sessions: the tradable row starts after the 200-session warm-up.
  Tiles 171.0% and 160.9% match the chart ends 2.71x and 2.61x, and the 3.8% end label equals
  2.71 ÷ 2.61 − 1. Worst drop −36.1% in the tile and on the chart, with 5,000 of 8,100 sessions plotted.

| Check | Result |
|---|---|
| Unit selection (spine, facts, rule, benchmark, figure, artifacts, toolbox, code size, filesystem, links) | 1,505 passed; 1 failed: the code-size ratchet asks for a lower `figures/_builders.py` allowance (see Unverified) |
| `tests/bias_guards` | 207 passed, 4 skipped |
| `tests/smoke -k rule` | 5 passed |
| Frontend lint, type check, unit tests | passed; 701 tests |
| Browser lanes, including screenshot baselines | 162 passed; no baseline changed |
| `gate.py semgrep`, `fs.py stale` | passed; 0 stale |

## Unverified

- `.claude/code-size-baseline.json` must lower the `figures/_builders.py` entry from 2657 to 2530
  because this change deleted 127 lines there. This build may not edit `.claude/`, so that one-line
  change is left to the owner.
- The engine's whole-share sizing leaves a small cash residual, so an always-invested rule never
  equals buy and hold exactly through the command line. The 1e-9 equality is proven in the unit
  test with a fractional-share fixture.
- Two dividends with the same ex-date, one with no pay date, make `_runner.source_fingerprint` fail
  (it sorts `None` against a date). This was found while building fixtures; it predates this change and is not fixed here.
- No real-data run was made.
