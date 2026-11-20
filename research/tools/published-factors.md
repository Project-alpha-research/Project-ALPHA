---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/context.py
  - apps/alpha-cli/src/alpha_cli/toolbox/reference.py
  - packages/alpha-validation/src/alpha_validation/factor_attribution.py
verified: 11024a221ff70253
---

# Published factors

**Reach for it when** a recorded rule test on a US stock or ETF makes you ask "is this just a known published
factor?" or "is the result new?". It is a reading in context, never a pass or fail.

```text
uv run alpha context pull-osap-portfolios --release <RELEASE> --released <DATE>
uv run alpha tool run context.published_factors <run_id> --json
uv run alpha tool describe context.published_factors
```

**How to read it**

- The run's scored returns become calendar-month returns. A month counts only when every trading day of the asset in
  that month is a scored date and the bar after its last day is scored too. The months used are listed.
- Seven fixed factors, chosen in code: momentum, short-term reversal, size, book-to-market, low beta, profitability,
  asset growth (`Mom12m`, `STreversal`, `Size`, `BM`, `Beta`, `OperProf`, `AssetGrowth`). Each shows its published year.
- `context.published_factors.explained_share` is the share of month-to-month variation that moves with them. The part
  they do not explain is shown per month and per year with a 95% range.
- A second part, labelled "search across all signals - exploratory", names the three closest signals with an adjusted
  p-value. Picking three of many is a search, and its range assumes independent months.
- Under 80 months, a non-US-stock asset, or factors too similar: a typed reading, no numbers.
- Every result is labelled `reference-series-known-later`: the factors were published after the test's period.
  The rule: [descriptive reference reads](../../docs/reference/invariants/cli-toolbox.md#descriptive-reference-reads).

**What it cannot tell you**

- A clear exposure is not evidence of an edge. A low explained share does not prove an edge.
- Ranges are too narrow when months are few. The factors are US stock factors; an ETF without stocks does not fit.

**Next** Run [attribution](attribution-regimes-changepoints.md) against a market, or the [rule test](rule-test.md) on another asset.
