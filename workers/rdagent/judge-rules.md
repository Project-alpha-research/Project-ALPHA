---
owner: rd-agent worker
sources:
  - workers/rdagent/alpha_factor_judge.py
  - workers/rdagent/alpha_factor_data.py
  - apps/alpha-cli/src/alpha_cli/_rdagent_membership.py
  - apps/alpha-cli/src/alpha_cli/rdagent_factor_eval.py
verified: 8d496b5cc1fd5f45
---

# RD-Agent worker: judging rules

The judging rules of the RD-Agent factor loop that were part of the [worker page](README.md): shortlist bookkeeping, futures funding, and thirds and ties (with its do-not-change list). What the loop does and how to launch it stay on the worker page.

## Shortlist bookkeeping

Every new evaluation factor and its trial-ledger row records `shortlist`: true only for
`CANDIDATE` or `DEFLATION_FAIL`, after the declared primary screen, spread and replay passed.
Shortlisted is not a pass, not a candidate, and not evidence of profit. This flag never changes
status, confirmed counts, screen cutoffs, deflation N or family counts. Old missing flags mean
"not recorded", never false. It is bookkeeping for a later owner-approved confirmation stage;
this addition reads no reserved data and grants no confirmation authority.

For shortlisted factors, `lineage_r2` uses the twin check's hash-bound factor-value Parquet files
on the same panel. `pooled-xs-rank-ols-v1` ranks finite values within each date, uses average tied
ranks scaled to [-0.5, 0.5] (a singleton has rank zero), then selects at most 20 earlier judged
factors by absolute pooled rank correlation, with ties in ledger order. Repeats, imports and
failed, unstable or look-ahead code store no values and supply no regressor. All finite target rows enter one pooled OLS fit
without an intercept; missing regressor cells contribute zero. The adjusted R² is
`max(0, 1 - (SSE / (n - rank(X))) / (sum(y²) / n))`; `lineage_regressors` records the column count.
`composite_suspect` is true at R² ≥ 0.5: "looks like a blend of earlier tries", diagnostic only.
Fewer than 1,000 target rows, no earlier factor, a constant target, or unavailable earlier value
archives give null with `lineage_reason`; no proxy or incomplete top-20 selection is invented.
If the calculation itself fails, the row records null and the error as `lineage_reason`; the verdict stands.
Retain each earlier factor's dated instrument values and their hash to make that comparison possible.
`test_rdagent_shortlist.py` checks blends, independent noise, missing values and unchanged decisions.

## Futures funding

`factor_loop_launch.py run --funding-dir <data_dir>` (also the evaluator's `freeze` option)
reads existing `context/binance/um/funding/<SYMBOL>.parquet` tables; no downloads.
`alpha_data.context.daily_funding_with_sources` verifies each sidecar SHA-256 and returns daily
sums, last rates and settlement counts plus source hashes. The settlement's `known_from` instant
chooses its UTC day: `[d 00:00, (d+1) 00:00)`. A settlement at the next midnight plus 8 ms belongs
to the next day. Actual rates are summed regardless of 8h/4h/2h or unknown intervals. Empty days
have no row. A table containing any 2024-or-later row is refused even outside the requested range.

Freeze keeps `PANEL_COLUMNS` and `panel.parquet` unchanged. `_panel_funding` joins the raw ticker
and date before identity relabelling; successors bring their own perp's rates. Reused tickers
lose funding on and after their declared break. `FUNDING_EXCLUSIONS` omits COCOSUSDT because
"perp identity across the 2023 rename is unresolved"; 1000-prefixed perps are not mapped.
Only panel keys survive. `panel/funding.parquet` and the receipt's optional `funding` block bind
the side table hash, source hashes, funded names and annual panel instrument-day coverage.
The launcher records the supplied directory in its arguments and receipt.

`alpha_factor_data.prepare` adds float64 `$funding_sum`, `$funding_last`, `$funding_count` to full,
debug and every cut, and records `funding_sha256`. Missing stays NaN: no perpetual or no settlement
that day (roughly four in ten coin-days, and most later-delisted coins never had a perpetual).
Never fill with zero or carry forward. The generated README explains the columns and midnight
boundary; the scenario mentions them only when they exist in the prepared data. Without the
option, freeze and prepare retain their original outputs, including receipts (HDF5 files embed
write times, so their bytes differ between any two runs, even of unchanged code; frames are equal).

The open `futures funding` family recognises funding, carry, basis and perp and is matched first,
so `funding_momentum_7d` is a funding idea, not a closed price family; no existing counts change. Eligibility uses the archived, hash-checked source: literal `$funding_` selectors in
Python subscripts or `.get`, `.filter`, `.__getitem__` calls intersect the normal mask with that
day's funding rows. Comments and standalone strings do not count. This is syntax, not data-flow
analysis: dynamic column names can be missed, and an unused selector or a selector on a different
object can count. Output values never choose the mask. Funding-enabled successful factors require
archived source. Trial rows (also in evaluation records) include `eligibility: "perp-funding"`,
`mean_eligible_names` over exploration days and funding hash. `input_columns` lists only literal
`$` selectors read by the source, including price columns, with `input_columns_method: source-selectors`.
If source is missing, the factor failed, or no literal selector is detected, no columns are listed
(as before) and `input_columns_method` says `fallback` and why. This does not change eligibility.

The unchanged coverage threshold is 80%; half of funded names is still DEGENERATE. At least five
finite names are needed on a decision day (the existing gap policy skips thin days).

Synthetic checks: `test_context_daily_funding.py` (poison, prefixes, intervals, absent days,
reserved rows, checksum); `test_rdagent_funding_columns.py` (identity join, partitions, source
selectors, coverage, price-only parity, pre-change freeze bytes and prepare frames).

## Thirds and ties

The rule lives in `alpha_cli._rdagent_membership.third_weights`
(`apps/alpha-cli/src/alpha_cli/_rdagent_membership.py`), not in the worker: `alpha_factor_judge.py` runs inside
RD-Agent's environment, imports no ALPHA package and calls the evaluator `alpha_cli.rdagent_factor_eval` as a
subprocess. Tests: `tests/unit/test_rdagent_ties_and_thirds.py`.

Thirds use `k = max(1, round(n/3))` among finite ranks. A tie group crossing a third's boundary receives
`s/g` membership per name (s remaining slots, g tied names); portfolio weights are `(s/g)/k`.
The spread, both replay paths and bucket reports share `_rdagent_membership.third_weights`.
Spread returns use these membership units divided by k; replacement turnover sums positive changes
in membership units divided by the new k, and estimated costs use that turnover. Replay targets
use the same weights for actual fills, fees, slippage and turnover. Without ties, membership is
exactly 0 or 1 and the old arithmetic is preserved. The legacy alternate-tie spread field equals
`mean_spread`; displayed figures and the sign check use this same spread.
`tie_share` is the daily mean fraction of finite names sharing a value. `boundary_tie_share` counts
names in a tie crossing either third boundary, once per name; empty days contribute zero.
`all_tied_day_share` retains the old fully tied-day fraction and its unchanged 5% screen guard. About
85 funded names can be screened and give 28 names per third if all have values; breadth alone
never grants a pass. Outcomes remain panel spot returns; clocks, cost rates, pass thresholds, deflation,
counting and twin rules are unchanged. Price-only evaluations retain the original eligibility.

Do not change without the owner:

- clocks, cost rates, pass thresholds, deflation, trial counting and twin rules (all unchanged by the thirds rule);
- the 80% coverage threshold, the five-name minimum (`MIN_NAMES`) and the 5% all-tied-day guard;
- a nonpositive spread stays `SPREAD_FAIL`: a stricter gate, never a pass;
- the loop never sees data on or after 2024-01-01 ([reserved period](../../docs/reference/project/reserved-period.md));
- keep the tie diagnostics `tie_share`, `boundary_tie_share` and `all_tied_day_share`, and the legacy field `alternate_tie_order_mean_spread`, which equals `mean_spread`;
- the instrument order never chooses a member of a tie, and the worker keeps importing no ALPHA package;
- never weaken a bias guard or oracle to get green; run `uv run python scripts/gate.py check`.
