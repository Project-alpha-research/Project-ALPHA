---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/*.py
  - apps/alpha-cli/src/alpha_cli/test_cmds.py
  - apps/alpha-cli/src/alpha_cli/_context_plan.py
verified: d240366b057727b7
---

# Rule test

**Reach for it when** the owner states a price rule or asks "does X work": the one route for a new idea.
**Command**
```text
uv run alpha test <spec.toml> --json
uv run alpha test --rule ma_cross --param fast=50 --param slow=200 --asset SPY --idea "<owner's words>" --json
uv run alpha test <spec.toml> --recheck --json   # system check, not a trial; exit 4 if the result differs
```
A spec file holds `name`, `idea`, `assets`, a `[rule]` table (`kind` plus its numbers) and an optional `[costs]` table
(`fee_bps`, `slippage_bps`, or `costs = "class-default"`). Kinds: `ma_cross` (`fast`, `slow`), `breakout` (`window`), `tsmom` (`lookback`, `skip`), and `owner`
(a `[rule.spec]` table: [language](../../docs/reference/owner-rule-language.md); `examples/owner-rsi-dip.toml`, `examples/owner-breakout-rsi-cross.toml`).
Asset: symbol or symbol@store. No file with flags. `--quick`: small gauntlet. `idea_card`: [card](idea-card.md). `[context]`, `when`: `--plan` only.
**How to read it**
- Each asset carries its own [data health verdict](data-health.md). Use `--check-data` to check missing or changed inputs before testing.
- The headline starts at the first open after warm-up; tiles, Sharpe and charts share each row’s dates (walk-forward only).
  Both lines use split-adjusted opens and one dividend basis. Missing period facts read “not recorded”.
- Each asset has `run_id`, `reading` (costs line), `oos_sharpe`, `benchmark_sharpe`, `labels`, `flags`, `error`, `resized_entries`, `executed`.
  `trials_total` counts ledger trials; `test_id` names the test. An owner rule's `reading` adds `count_sentence` and `variant_table`.
- Quote the `reading`, never a grade: `clear of chance`, `some evidence`, `not clear of chance` or `too little to read`,
  and above, below or within the uncertainty of buy-and-hold. `Fault:` means no reading. `verdict` is the old letter.
- A failed asset keeps its row with `error` set and counts as a trial. If all fail, read `known` and `next` in `error`.
- Bars per year follow each market's calendar. Bars from 2024-01-01 on are held back (`reserved-period-held-back`).
- `--recheck`: the test computed again and compared with the stored result; no ledger row, no file
  ([rule](../../docs/reference/invariants/cli-rule-readings.md#recheck)). `executed` is `true` if the engine ran; `repeat` is not that.
**What it cannot tell you**
- Today's limits, planned to be lifted ([checklist](../../docs/roadmap/production-scope.md#4-backtest)): daily bars, long only,
  all-in sizing; no exits, shorts or volume in an owner rule. Say so, or use `alpha backtest run <SYMBOL> --timeframe 1h`
  (intraday): a plain backtest, no diagnostics, not in the ledger. Label it so.
- Whether the result is real. Read [diagnose and audit](diagnose-and-audit.md) first.
**Next** `uv run alpha diagnose <run_id> --json`, then the card that matches the first flag.
