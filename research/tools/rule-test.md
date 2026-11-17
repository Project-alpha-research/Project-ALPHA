---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/*.py
  - apps/alpha-cli/src/alpha_cli/test_cmds.py
verified: 6cd92121479202cd
---

# Rule test

**Reach for it when** the owner states a price rule or asks "does X work": the one route for a new idea.

**Command**

```text
uv run alpha test <spec.toml> --json
uv run alpha test --rule ma_cross --param fast=50 --param slow=200 --asset SPY --idea "<owner's words>" --json
```

A spec file holds `name`, `idea`, `assets`, a `[rule]` table (`kind` plus its numbers) and an optional `[costs]`
table (`fee_bps`, `slippage_bps`). Rule kinds: `ma_cross` (`fast`, `slow`), `breakout` (`window`), `tsmom`
(`lookback`, `skip`). An asset is a symbol, or symbol@store. A file and rule flags cannot be mixed. `--quick`
runs a small gauntlet and labels the result `quick`.

**How to read it**

- Each asset has `run_id`, `verdict` (grade), `oos_sharpe`, `benchmark_sharpe`, `labels`, `flags`, `error`, `resized_entries`.
  `resized_entries` counts reduced scored entries; `trials_total` counts ledger trials; `test_id` names the test.
- A failed asset keeps its row with `error` set and still counts as a trial. If every asset fails, the output
  is an `error` object: read `known` and `next`, and do what `next` says.
- Bars per year come from the calendar of the bars (`periods_per_year`), so crypto is not treated as stocks.

**What it cannot tell you**

- A rule outside the three kinds, short selling, sized positions or intraday bars: it reads daily bars only.
  Say so and offer the nearest kind, or `alpha backtest run <SYMBOL> --timeframe 1h` (intraday, or a saved rule
  with `--strategy rules`): a plain backtest with no diagnostics, not counted in the ledger. Label it so.
- Whether the result is real. Read [diagnose and audit](diagnose-and-audit.md) first.

**Next** `uv run alpha diagnose <run_id> --json`, then the card that matches the first flag.
