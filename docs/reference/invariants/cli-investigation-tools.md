---
owner: command line runs and validation
sources:
  - apps/alpha-cli/src/alpha_cli/tool_cmds.py
  - apps/alpha-cli/src/alpha_cli/_rdagent_checks.py
  - apps/alpha-cli/src/alpha_cli/toolbox/**/*.py
  - apps/alpha-cli/src/alpha_cli/spine/facts.py
  - apps/alpha-cli/src/alpha_cli/spine/ledger.py
  - packages/alpha-validation/src/alpha_validation/attribution.py
  - packages/alpha-validation/src/alpha_validation/regimes.py
  - packages/alpha-validation/src/alpha_validation/changepoints.py
  - tests/smoke/test_rule_tools_smoke.py
---

# Investigation tools invariants

Follow-up questions on a recorded rule test or judged factor replay; part of [command line runs](cli-runs.md).

## Rules

- These three `market-context` entries (`alpha tool run-set market-context <run_id>`) describe one recorded rule test.
  They rebuild its full-sample equity through the diagnostic pass's own path
  (`spine/diagnose.py:full_sample`), fail loud with `RUN_DATA_CHANGED` when the stored bars no
  longer reproduce it, and never re-run a walk-forward. Statistics are thin glue over statsmodels
  and ruptures in `alpha_validation` (`attribution.py`, `regimes.py`, `changepoints.py`).
- The fixed RD-Agent checks use only the shown lead-clock replay's after-cost excess returns. Verify the manifest and replay hashes,
  reproduce the judged annualized return, and refuse inputs that reach the reserve before consulting the cache.
  Attempts belong to the run's checks ledger. They never enter the factor ledger, change a verdict or add a deflation trial.
- Run-level tools use immutable walk-forward sidecars. The cache key includes each required file’s hash. A missing file records an error.
- Seeded interval and path tests publish the effective simulation seed. The deflated Sharpe uses the ledger family frozen at publication.
- New rule tests add `gross_return` and `cost_return` to `equity_curve.parquet` (both zero on the baseline row); older runs lack them.
  Cost per bar comes from the stored fills: the rounded commission, plus on a buy the gap between the fill and the opening bid. The engine
  values a long at the bid, so the whole spread of a round trip lands on its buy bar. Gross is net plus cost; the writer refuses a gap over 1e-12.
- The engine samples equity at each bar's open, so market and benchmark returns are open-to-open
  on shared timestamps; the output reports the bars each side lost to the join. A comparison of
  two assets with different session clocks says that a shared date is not a shared instant.
  Attribution uses the rule test’s full-history buy-and-hold calculation from the first shared open.
  A comparison asset’s recorded dividends enter its cache key.
- Regimes are fitted on the market's returns. The headline split labels each bar with the
  filtered regime of the bar before it (causal); the smoothed split is a separate `hindsight`
  section. Model parameters use the whole sample: label `parameters-fit-in-sample`. Change points
  are labelled `hindsight`; same-asset comparisons `benchmark-is-same-asset`.
- Causal regime shares lead the facts and reading; hindsight is explicitly second. Opposite signs add `hindsight-disagrees` and advise using the causal split.
- Change points within five bars of a portfolio flat/in-market transition are position changes, excluded from `market.changepoints.count`; both counts are
  reported. Without a recorded position series each reads "position state unknown" and the count is null. `near_switch_share` is the share of
  bars within five bars of a switch; above 20% the sentence calls the split rough.
- The [toolbox contract](../project/components/toolbox.md) governs attempts, settings and cache identity.
  Each attempt writes an `attempted` ledger row before computing and an `ok` or `error` row (with `error_code`) after; an identical
  request (inputs, settings, seed, version) returns the stored file with no new row. Rows carry `tool_kind` and `look`. A setting off its
  default, or a re-rolled seed of a seeded entry, adds `non-default-params`; `alpha tool history <run_id>` lists every attempt.
  Outputs live under `diagnostics/<run_id>/<id>@v<version>-<sha8>.json`. Tool rows add no try, but a new `parameters.*` settings re-run adds one.
- `alpha results show` includes stored files and attempt history. Cite a value by its tool id and output key, e.g. `market.attribution.beta`.
  Earlier metric names and stored files remain citable. Use `--tool-output <id>` for multiple outputs or any non-default setting.
  Copy the output-specific tag and settings count into the draft. The checker reads the same fact.
- `reserved-period-seen` means the run used data on or after the reserve date. All bars used by the original run remain in the calculation.
