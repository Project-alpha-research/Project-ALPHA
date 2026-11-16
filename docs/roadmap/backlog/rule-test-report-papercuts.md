# Rule-test report: wording and basis papercuts

**Status:** Scoped
**Rough size:** S

## Problem / why

Follow-ups from pull requests 186, 188, 195 and 205 that were left only in their descriptions:

- The drawdown flag can read over 100 per cent ("110% of worst drawdown"); check the measure.
- Old runs show a developer message on the macro line (a reason stored before macro data).
- The run library's period (equity curve) differs from the report's (bars loaded), unexplained.
- The summary shows walk-forward Sharpe, the report whole-history Sharpe; the footnote is easy
  to miss.
- Profit concentration uses closed trades only; the audit's trade count differs between
  walk-forward and full-sample sections. Each section should name its basis.
- Tearsheet details still show an unused volatility target and do not say "all in".

## Where it would live

`apps/alpha-cli` rule-test report and `apps/alpha-web` report screen.

## What "done" looks like

Each point fixed or its basis printed on the screen.

## Dependencies

None.

## Sources

- [Checklist stage 10](../production-scope-3.md#10-screens)
