---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/resampling_more*.py
  - tests/unit/test_toolbox_resampling_more.py
---

# More resampling and Monte Carlo checks

**Reach for these checks when** one history is all you have and you ask how much its range, drop or order was luck.
Run any of them with `alpha tool run <id> <run_id>`. Each gives numbers and a plain sentence, never a verdict.

| Check | Question |
|---|---|
| `resampling.moving_block_paths` | What range of final return and worst drop do fixed blocks of bars give? |
| `resampling.circular_block_paths` | The same, with blocks wrapped around the history. |
| `resampling.wild_bootstrap` | What range of average bar return holds when bars of different size are weighted? |
| `resampling.risk_of_ruin` | How often does a redrawn history fall past a ruinous drop? |
| `resampling.return_shuffle` | Does the order of the bar returns carry anything beyond the returns themselves? |
| `resampling.phase_surrogates` | Does the drop need more than the return spectrum, which random-phase copies keep? |
| `resampling.calendar_year_shuffle` | Is the worst drop tied to the order of the calendar years? |
| `resampling.interleaved_halves` | Do two random halves of the bars tell the same story? |
| `resampling.trade_order_drawdown` | How much does the worst drop depend on the order of the trades? |
| `resampling.trade_jackknife` | Does any single trade drive the average profit per trade? |
| `resampling.year_jackknife` | Does any single calendar year drive the total return? |
| `resampling.stress_shocks` | What if the swings were larger, or one sudden loss hit at the high? |

**How to read it**

- All use the scored after-cost returns or closed trades of the stored run, cut at the held-back date.
- Seeded checks name their seed in the stored result. A new seed or changed setting counts as another setting tried.
- Too few bars, trades or years gives "too little to read" with the count, never a number.

**What these checks cannot tell you** Every redraw assumes the future looks like this history. None shows that an edge exists.

**Next** See [uncertainty in one rule test](resampling-checks.md) for intervals, and [trade streaks](run-level-checks.md).
