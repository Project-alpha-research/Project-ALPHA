---
owner: validation statistics
sources:
  - packages/alpha-validation/src/alpha_validation/factor_attribution.py
  - packages/alpha-validation/src/alpha_validation/correlation_interval.py
  - tests/unit/test_validation_factor_attribution.py
  - tests/unit/test_validation_correlation_interval.py
---

# Factor attribution and correlation interval

Two statistics for the published-factor check, in `alpha_validation`. They add maths (owner-approved
2026-11-20); they do not wrap statsmodels. Package rules: [validation invariants](validation.md).

## Factor attribution

- `factor_attribution(strategy, factors, *, periods_per_year, factor_names)`: OLS with a constant on K factors.
  Newey-West standard errors use the lag rule, Bartlett kernel and `n / (n - K - 1)` factor of
  `market_attribution`; intervals and p-values are normal. With K = 1 it equals `market_attribution` to 1e-12.
- Errors are `DataError`: non-finite input, unequal lengths, duplicate names, a series that does not vary.
- A standard error of exactly 0 gives `t = None`, `p = None` and `edge = "zero_standard_error"`; no p is made up.
- HAC intervals under-cover in small samples: about 92% at N = 60 with independent errors, 89% with AR(1) errors.
- Minimum sample `max(36, 10 * (K + 1))` (`min_observations`): a convention, not a law, and not a caller knob.
- Collinearity: the condition number of the unit-length-column design above `MAX_CONDITION_NUMBER` (30,
  Belsley-Kuh-Welsch rule of thumb) is an error that names the columns involved.

## Correlation interval

- `correlation_interval(x, y, *, method="pearson")`: Fisher z interval, two-sided normal p, at least 4 pairs.
  `|r| = 1` returns `r = +-1`, interval `[r, r]`, `p = 0`, `edge = "perfect_correlation"`. Spearman uses
  average ranks and the same interval. That is slightly narrow: Fieller, Hartley and Pearson (1957) give
  about `1.06 / (n - 3)`. The interval assumes independent pairs; there is no effective-N adjustment.

## What they must never be used for

- A significant beta or correlation is not evidence of an edge: it measures exposure or association.
- Serial correlation makes the correlation interval too narrow; the HAC lag only partly covers it for betas.

## Tests

- Known answers, not oracles in `tests/oracles` (no file may be added there without the owner): an
  independent lstsq and Newey-West loop, a hand Fisher interval, K = 1 equality and coverage simulations.
