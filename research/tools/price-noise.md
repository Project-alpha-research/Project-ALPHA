---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/price_noise.py
  - apps/alpha-cli/src/alpha_cli/spine/diagnose.py
  - apps/alpha-cli/src/alpha_cli/spine/facts.py
verified: 5b14ac172b6eee8e
---

# Price-noise robustness

**Reach for it when**: would a slightly different data feed change the answer?

**Commands**
```text
uv run alpha diagnose <run_id>
uv run alpha results cite <run_id> price_noise_p05_sharpe
```

**How to read it**
- The test stores 50 full-sample net engine re-runs with independent lognormal nudges to each OHLC
  price, log standard deviation 0.001 (10 basis points). High and low are repaired; volume stays fixed.
- Seeds come from the run id. The spec, costs and next-open fills stay the same. These are controls:
  no ledger trial, sensitivity variant or family count is added. Diagnose only reads stored results.
- `price_noise` gives median Sharpe, the 5th–95th percentile range, sign-flip share and median trades.
  `fragile-to-price-noise`: the original Sharpe was positive and the 5th percentile was at most zero,
  or some copy had no defined Sharpe at all (it went flat).

**What it cannot tell you**
- This is feed sensitivity, not a confidence interval or proof of an edge. Gaussian nudges are unbounded;
  0.1% is their scale, not a maximum. Corporate actions and volume are unchanged.
- The nudges add a little day-to-day wobble, so copies sit slightly below the original Sharpe even
  for a robust rule (SPY 50/200: original 0.75, copies 0.74–0.75). Read the spread and sign flips.
- Any undefined copy makes the aggregate Sharpe and sign-flip figures null with a reason and is counted in
  `undefined_copies`; it is never dropped.
- Old runs have no stored price-noise pass. Test the saved spec again to compute it; old runs stay immutable.

**Next** Compare another data feed or more history with the [rule test](rule-test.md).
