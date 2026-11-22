---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/timeseries.py
  - apps/alpha-cli/src/alpha_cli/toolbox/families/timeseries_a.py
  - apps/alpha-cli/src/alpha_cli/toolbox/families/timeseries_b.py
  - apps/alpha-cli/src/alpha_cli/toolbox/families/timeseries_c.py
  - tests/unit/test_toolbox_timeseries.py
verified: 0000000000000000
---

# Time-series checks

**Reach for these checks when** the owner asks how the run's daily returns behave over time: linked, trending, clustered or irregular.

Run each as `alpha tool run <id> <run_id>`. Each gives a reading, never a verdict. All read the stored after-cost returns.

| Check | Question |
|---|---|
| `timeseries.ljung_box` | Are returns on nearby bars linked to each other? |
| `timeseries.autocorrelation` | At which lags are returns correlated with their own past? |
| `timeseries.variance_ratio` | Do returns trend or reverse over several days? |
| `timeseries.hurst` | Do returns trend, wander or reverse over long spans? |
| `timeseries.up_down_runs` | Do up bars and down bars come in random order? |
| `timeseries.arch_lm` | Do large moves cluster in time? |
| `timeseries.normality` | Do returns look like a bell curve? |
| `timeseries.dfa` | Do returns remember their own past over long spans, even through trends? |
| `timeseries.long_memory` | Is there fractional long memory in returns? |
| `timeseries.sample_entropy` | How irregular is the return series? |
| `timeseries.compressibility` | How compressible are the up and down days? |
| `timeseries.permutation_entropy` | How ordered is the sequence of returns? |

**How to read them**

- A p-value is a chance under a stated no-pattern case. A small one is a reason to look, not proof of an edge.
- With too few returns, a check says "too little to read" and gives the count.
- `timeseries.hurst` uses the run's seed for its white-noise comparison.
- `timeseries.sample_entropy` reads up to 10,000 bars; a longer run gets an unavailable result with the count.

**What these checks cannot tell you** They describe the past returns of one run. They do not say why, or whether it will continue.
