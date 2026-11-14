# Owner rule backtests: full allocation without rejected orders or daily churn

**Status:** Scoped
**Rough size:** M

## Problem / why

A plain "hold SPY while the 60-day trend is up" test through `alpha backtest run --strategy
rules` (2026-11-15, Yahoo snapshot, data to 2023-12-31) showed:

- **Silent rejections.** With full allocation (`--target-vol 100`, max leverage 1, CASH), 5,148
  of 5,151 orders were rejected: the target plus fees is never affordable. The run still
  reported success, with a final equity. That breaks the fail-loud rule.
- **Daily churn.** With `--max-leverage 0.95`, the volatility-target base strategy re-sized every
  day: 5,252 orders for a rule that changed state about 185 times. There is no trade band, so
  costs are inflated.
- **No long-or-flat option.** The command line has no way to ask for the fixed-quantity
  long-or-flat mode (`fixed_quantity`, `fixed_entry_once`), although the strategy supports it.
  The rule-family path (pull request #191) uses that mode directly.
- **The canonical bytes are hidden.** `--rules-file` needs canonical bytes, but
  `alpha rules validate` neither prints nor writes them.
- **A misleading figure.** `equity_vs_passive` compares a fixed-capital (non-compounding)
  strategy with a compounding price index without dividends. On SPY it showed "-88.6%", which is
  mostly a sizing artefact. The figures are also dark-themed only, while the owner asked for a
  light quant style.

## What "done" looks like

- A run with more than a small share of rejected orders fails, or carries a loud warning in its
  report and in the Workstation.
- A `--sizing fixed-long-flat` option, a no-trade band for the volatility target, and
  `alpha rules validate --write-canonical <path>`.
- `equity_vs_passive` compares like with like (both compounding or both fixed, dividends
  stated), with a light theme.

## Dependencies

None.

## Sources

- Runs `e33868ceeab49afb` and `6569429395665854` in the data folder; the figure export of the
  latter.
