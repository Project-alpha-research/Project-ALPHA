# Vol-target sizing keeps sending orders a cash account cannot pay for

**Status:** Idea
**Rough size:** S

## Problem / why

Found on 2026-11-15 in the SPY 5-minute system test (run `e7554b11b3ccbb4f`): 431 of 522 orders
were denied, 248 of 596 even with `--max-leverage 0.95`. Every denied order is a buy. The default
vol-target sizing uses the starting capital, not current equity, so after losses a CASH account
cannot pay for the target position and each later buy is refused. The run only fails when every
order is refused; otherwise it reports a count, and the report does not say why the orders were
refused. The idea's result is then a different strategy from the one asked for, quietly.

## What "done" looks like

- A run whose orders are partly denied says so in the report and the run list, with the reason
  (insufficient cash) and the first denied order.
- Either sizing on equity becomes the default for CASH accounts, or the denial count is part of
  the run's headline with a clear hint (`--size-on-equity`).

## Dependencies

None.
