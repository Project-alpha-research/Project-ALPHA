---
owner: command line runs and validation
sources:
  - apps/alpha-cli/src/alpha_cli/tool_cmds.py
  - apps/alpha-cli/src/alpha_cli/toolbox/**/*.py
  - apps/alpha-cli/src/alpha_cli/spine/facts.py
  - apps/alpha-cli/src/alpha_cli/spine/ledger.py
  - packages/alpha-validation/src/alpha_validation/attribution.py
  - packages/alpha-validation/src/alpha_validation/regimes.py
  - packages/alpha-validation/src/alpha_validation/changepoints.py
  - tests/smoke/test_rule_tools_smoke.py
verified: c999d5c46621d8f4
---

# Investigation tools invariants

Follow-up questions on one recorded rule test; part of [command line runs](cli-runs.md).

## Rules

- The three entries in `alpha tool run-set market-context <run_id>` describe one recorded rule test.
  They rebuild its full-sample equity through the diagnostic pass's own path
  (`spine/diagnose.py:full_sample`), fail loud with `RUN_DATA_CHANGED` when the stored bars no
  longer reproduce it, and never re-run a walk-forward. Statistics are thin glue over statsmodels
  and ruptures in `alpha_validation` (`attribution.py`, `regimes.py`, `changepoints.py`).
- Run-level descriptions use immutable walk-forward sidecars. The cache key includes the hash of each required sidecar, and a missing file records an error.
- The engine samples equity at each bar's open, so market and benchmark returns are open-to-open
  on shared timestamps; the output reports the bars each side lost to the join. A comparison of
  two assets with different session clocks says that a shared date is not a shared instant.
- Regimes are fitted on the market's returns. The headline split labels each bar with the
  filtered regime of the bar before it (causal); the smoothed split is a separate `hindsight`
  section. Model parameters use the whole sample: label `parameters-fit-in-sample`. Change points
  are labelled `hindsight`; same-asset comparisons `benchmark-is-same-asset`.
- Causal regime shares lead the facts and reading; hindsight is explicitly second. Opposite signs add `hindsight-disagrees` and advise using the causal split.
- Change points within five bars of a portfolio flat/in-market transition are position changes, excluded from `market.changepoints.count`; both counts are
  reported. Without a recorded position series each reads "position state unknown" and the count is null. `near_switch_share` is the share of
  bars within five bars of a switch; above 20% the sentence calls the split rough.
- The [toolbox contract](../project/toolbox-registry.md) governs attempts, settings and cache identity.
  Each attempt writes an `attempted` ledger row before computing and an `ok` or `error` row (with `error_code`) after; an identical
  request (inputs, settings, seed, version) returns the stored file with no new row. Rows carry `tool_kind` and `look`. A setting off its
  default, or a re-rolled seed of a seeded entry, adds `non-default-params`; `alpha tool history <run_id>` lists every attempt.
  Outputs live under `diagnostics/<run_id>/<id>@v<version>-<sha8>.json`. Tool rows have a null verdict and contribute zero deflation trials.
- `alpha results show` includes stored files and attempt history. Cite a value by its tool id and output key, e.g. `market.attribution.beta`.
  Earlier metric names and stored files remain citable. Use `--tool-output <id>` for multiple outputs or any non-default setting.
  Copy the output-specific tag and settings count into the draft. The checker reads the same fact.
- `reserved-period-seen` means the run used data on or after the reserve date. All bars used by the original run remain in the calculation.
