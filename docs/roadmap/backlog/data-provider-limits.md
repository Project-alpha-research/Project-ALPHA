# Data provider limits not yet written down

**Status:** Scoped
**Rough size:** S

## Problem / why

Facts found in pull requests 190, 196 and 202 that live only in their descriptions:

- The credit-spread series is only available from late 2023; the financial-conditions series
  stores about 937,000 rows; a windowed retry can leave adjacent rows with the same value.
- A rolling three-year replacement for the restricted macro series is unresolved.
- SPY runs are labelled market "unknown" because their manifest records no source.
- Free positioning data (futures positioning, short interest) and filing-dated company data are
  judged in the [register](../../reference/project/outside-projects.md#judged-in-the-november-follow-up-studies).

Also unwritten: what happens when a free provider is down (failover and redundancy for the owner's
sources) and crypto data quality (inflated exchange volume, outages that leave gaps, a venue that
disappears).

## Where it would live

The [data layer page](../../reference/project/components/data-layer.md) and the data invariants.

## What "done" looks like

Each limit stated in its one home, or fixed.

## Dependencies

None.

## Sources

- [Checklist stage 2](../production-scope.md#2-data-and-context)
