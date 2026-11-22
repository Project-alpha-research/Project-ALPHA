---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/context.py
  - apps/alpha-cli/src/alpha_cli/toolbox/reference.py
  - packages/alpha-validation/src/alpha_validation/factor_attribution.py
verified: e1fd9aceca0d9f21
---

# Published factors

**Reach for it when** a recorded rule test on a US stock or ETF makes you ask "is this just a known published
factor?" or "is the result new?". It is a reading in context, never a pass or fail.

```text
alpha context pull-osap-portfolios --release <RELEASE> --released <DATE>
alpha tool run context.published_factors <run_id> --json
alpha tool describe context.published_factors
```

**How to read it**

- The run's scored returns become calendar-month returns, complete months only. The months used are listed.
- Seven fixed factors, chosen in code: momentum, short-term reversal, size, book-to-market, low beta, profitability,
  asset growth (`Mom12m`, `STreversal`, `Size`, `BM`, `Beta`, `OperProf`, `AssetGrowth`). Each shows its published year.
- `context.published_factors.explained_share` is the share of month-to-month variation that moves with them. The rest has a 95% range.
- A second part, labelled "search across all N - exploratory", names the three closest of the N signals compared, with
  a p-value adjusted over all N. Picking three of many is a search; its range assumes independent months.
- Under 80 months, or an asset that is not a US stock or fund: a typed reading, no numbers. Factors too similar:
  one factor at a time; these exposures overlap and must not be added up.
- Older stores: a stock source with only US-session bar dates is read as a US stock or fund, labelled `asset-kind-inferred-from-calendar`.
- Every result is labelled `reference-series-known-later`: the factors were published after the test's period.
  Rule: [descriptive reference reads](../../docs/reference/invariants/cli-toolbox.md#descriptive-reference-reads).

**What it cannot tell you**

- An exposure is not an edge; a low explained share does not prove one. Factor returns are paper portfolios before costs.
- Ranges are too narrow when months are few. For a bond or commodity fund these stock factors mean little.

**Next** Run [attribution](attribution-regimes-changepoints.md) against a market, or the [rule test](rule-test.md) on another asset.
