---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/resampling.py
  - tests/unit/test_toolbox_resampling_checks.py
---

# Uncertainty in one rule test

**Reach for these checks when** the owner asks how much a Sharpe ratio, yearly return or drop depends on the one history the test saw.

| Question | Command |
|---|---|
| What range of yearly Sharpe ratio does the history support? | `alpha tool run resampling.sharpe_interval <run_id>` |
| What range of compound yearly return does the history support? | `alpha tool run resampling.return_interval <run_id>` |
| Was the worst drop unusual next to histories redrawn bar by bar? | `alpha tool run resampling.drawdown_distribution <run_id>` |
| What final returns and drops do histories redrawn in blocks give? | `alpha tool run resampling.block_bootstrap_paths <run_id>` |

**How to read it**

- RD-Agent’s [journey](rdagent-journey.md) also reports the Sharpe interval and block paths on a judged factor’s after-cost return above the basket.
- On a rule test, all four use the scored after-cost bar returns from the stored walk-forward equity, and the run's own bars per year.
- The two intervals are block-bootstrap (BCa) intervals: 2,000 redraws, blocks of five bars on average, 95% confidence.
  At these defaults they give the same numbers as the Sharpe and CAGR intervals the rule test stored (`alpha report <run_id>`).
  An interval that includes zero means this history cannot rule out no edge. They need at least three varying returns.
- The drop check redraws single bars at random, 10,000 times, and gives the typical and the one-in-20 worst drop.
  At these defaults it gives the same numbers as the independent-return family of `alpha monte-carlo classical --from-run <run_id>`.
- The block check redraws runs of bars together, 2,000 times, and gives the 5th, 50th and 95th percentile final return and the one-in-20 worst drop.
  Keeping runs of bars together keeps losing streaks that the single-bar check breaks up, so its drops are the more cautious of the two.
- Each stored result names its seed. A new seed or any changed setting is labelled and counted as another setting tried.

**What these checks cannot tell you** Every redraw assumes the future looks like this history. Single-bar redraws also assume each bar is
independent of the one before; check `trades.dependence` for bunched wins and losses. None of these shows that an edge exists.

**Many tries?** `alpha tool run overfit.deflated_sharpe <run_id>` gives the same probability as `alpha results cite <run_id> trial_dsr`.
It uses the count of tries frozen when the run was recorded and says that count; later tries are not counted.

**Next** Check [trade clustering](run-level-checks.md) or [family deflation](deflated-sharpe-and-trials.md). [Cite](results-and-cite.md) the stored output.
