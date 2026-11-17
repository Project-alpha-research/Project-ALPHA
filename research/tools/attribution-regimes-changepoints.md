---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/tools.py
  - packages/alpha-validation/src/alpha_validation/attribution.py
  - packages/alpha-validation/src/alpha_validation/regimes.py
  - packages/alpha-validation/src/alpha_validation/changepoints.py
verified: 24c4e5422c1b2dfb
---

# Market attribution, regimes and change points

**Reach for it when** a recorded rule test raises "is it just the market?", "does it only work in some
regimes?" or "when did it stop working?".

**Commands**
```text
uv run alpha tool attribution <run_id> --benchmark SPY --json
uv run alpha tool regimes <run_id> --k 2 --json
uv run alpha tool changepoints <run_id> --on returns --json
```

**How to read it**

- Each tool rebuilds the run's full-sample equity from the stored bars and fails with `RUN_DATA_CHANGED`
  if they no longer reproduce it. Each output is stored beside the run and adds one ledger row.
- Attribution: `market_beta` (1 = moves one for one), `market_alpha_annual` with its `market_alpha_p`,
  and `market_r_squared`. Returns are open-to-open; the default benchmark is the run's own asset
  (label `benchmark-is-same-asset`).
- Regimes: the headline split labels each bar with the market regime known the bar before;
  `regime_turbulent_share_of_return` against `regime_turbulent_share_of_time` says where the return came from.
- Change points: `changepoint_count` and the dates, labelled `hindsight`.

**What it cannot tell you**

- Regime model parameters are fitted on the whole sample (`parameters-fit-in-sample`); a split is a
  description, never a tradable signal. Change points are found with hindsight.
- No size or momentum factors: only the market or one chosen asset.

**Next** Test the leading explanation with the [rule test](rule-test.md) on another asset or period.
