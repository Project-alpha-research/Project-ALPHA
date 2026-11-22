---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/market.py
  - packages/alpha-validation/src/alpha_validation/attribution.py
  - packages/alpha-validation/src/alpha_validation/regimes.py
  - packages/alpha-validation/src/alpha_validation/changepoints.py
verified: 96231f129d35a504
---

# Market attribution, regimes and change points

**Reach for it when** a recorded rule test raises "is it just the market?", "does it only work in some
regimes?" or "when did it stop working?".

```text
alpha tool run-set market-context <run_id> --json
alpha tool run market.attribution <run_id> --param benchmark=SPY --json
alpha tool describe market.vol_regimes
alpha tool describe market.changepoints
```

**How to read it**

- Each tool rebuilds the run's full-sample equity from the stored bars and fails with `RUN_DATA_CHANGED`
  if they no longer reproduce it. History records attempts and outcomes. Reading an identical result reuses its file.
- Attribution: `market.attribution.beta` (1 = one for one), `market.attribution.alpha_annual` with its
  `market.attribution.alpha_p`, and `market.attribution.r_squared`. Buy and hold starts at the first shared open and keeps eligible dividends
  as cash from their payment date, as in the rule test’s full-history comparison. The default is the run’s own asset (label `benchmark-is-same-asset`).
- Regimes: the headline split labels each bar with the market regime known the bar before;
  `market.vol_regimes.turbulent_share_of_return` against `market.vol_regimes.turbulent_share_of_time` says where the return came from.
- The causal split leads; the second is "with hindsight (not knowable at the time)". Opposite signs
  carry `hindsight-disagrees`: use the causal split. Model parameters still use the full sample.
- Change points within five bars of a flat/in-market switch read "position change" and are left out of
  `market.changepoints.count`; with no recorded positions each reads "position state unknown", count null.
**What it cannot tell you**
- Regime model parameters are fitted on the whole sample (`parameters-fit-in-sample`); a split is a
  description, never a tradable signal. Change points are found with hindsight.
- No size or momentum factors: only the market or one chosen asset.
**Next** Test the leading explanation with the [rule test](rule-test.md) on another asset or period.
