---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/*.py
  - apps/alpha-cli/src/alpha_cli/results_cmds.py
  - apps/alpha-cli/src/alpha_cli/test_cmds.py
  - apps/alpha-cli/src/alpha_cli/context_cmds.py
  - apps/alpha-cli/src/alpha_cli/context_sources_cmds.py
verified: 661aaca963b74726
---

# Research tools, by symptom

Commands are written as `alpha ...`. From a checkout, type `uv run alpha ...` instead.
Start from the symptom. Each card gives a tool's command, how to read it, its limits and what to try next ([playbook](../PLAYBOOK.md)).

| What you see or need | Open |
|---|---|
| Stored symbols, history, a new symbol; gaps or bad timestamps; a copy of the data | [data](data.md), [data health](data-health.md), [backup](home-backup.md) |
| "Has the chart looked like this before?"; a Kronos range of paths | [lookalike and unusual](lookalike.md), [forecast](forecast.md) |
| "Which check fits my situation?" | [toolbox by situation](toolbox-by-situation.md) |
| "A better model for RD-Agent?" | [model bench](rdagent-model-bench.md), [RD-Agent setup](rdagent-setup.md) |
| "Can a model find it?" (Qlib gradient boosting) | [ML model](ml-model.md) |
| An idea to test ([idea card](idea-card.md), [library](library.md)) | [rule test](rule-test.md), [follow](follow.md), [final](reserved-confirmation.md) |
| "Does the pipeline still work?", "did last night fail?", "is the disk filling up?" | [nightly run](nightly-run.md), [failure marker, disk](nightly-alert.md) |
| Chart setup, pattern: "every time it happened" | [patterns](chart-patterns.md), [find](setup-find.md), [spec](setup-spec.md), [context](setup-context.md) |
| What followed each setup occurrence; a setup traded with stops, targets and a time limit | [setup study](setup-study.md), [setup trade](setup-trade.md) |
| "Did we test this?", "what was the number?", "do two runs move together?" | [results and cite](results-and-cite.md), [portfolio book](portfolio-book.md) |
| The result looks too good | [diagnose and audit](diagnose-and-audit.md), then [random-price null](random-price-null.md) |
| Too good after many tries; a first look at many signals | [deflated Sharpe, trials](deflated-sharpe-and-trials.md), [quick screen](quick-screen.md) |
| Big drawdown in a short period | [benchmark and drawdowns](benchmark-and-drawdowns.md), then the macro row below |
| Works in some years only | [benchmark and drawdowns](benchmark-and-drawdowns.md) (`by_year`), [walk-forward](walk-forward.md) |
| Few trades; profit from a handful of trades | [diagnose and audit](diagnose-and-audit.md) (`enough-trades`), [trade streaks](run-level-checks.md) |
| Would a slightly different data feed change the answer? | [price-noise robustness](price-noise.md), [re-runs](toolbox-parameter-robustness.md) |
| Fragile to costs, delay or nearby settings | [sensitivity](sensitivity.md), [break-even](run-level-checks.md), [cost realism](toolbox-cost-realism.md) |
| "Does it hold up out of sample?" | [walk-forward efficiency](walk-forward.md) |
| "Is this just the market going up?", "a known factor?" | [inverted control](inverted-signal-control.md), [published factors](published-factors.md) |
| Market beta, calm or turbulent regimes, "when did it change?" | [beta, regimes, changes](attribution-regimes-changepoints.md), [more](toolbox-regimes.md) |
| Ranges, drops, prop-firm odds | [resampling](resampling-checks.md), [fat tails](montecarlo-checks.md), [path risk](path-risk.md), [prop firm](propfirm.md) |
| Why a judged RD-Agent idea stopped; a picture for the owner | [one idea’s journey](rdagent-journey.md), [charts](charts.md) (`trade_pnl`: profit by trade) |
| Overfitting; resampling; time series | [overfit](toolbox-overfit-controls.md), [resampling](toolbox-resampling-more.md), [series](toolbox-timeseries.md) |
| Performance statistics; risk and sizing | [performance](toolbox-performance-stats.md), [risk](toolbox-risk-sizing.md) |
| Need the macro picture or option prices | [macro](macro-context.md), [positioning](positioning-short-volume-context.md), [options](options-derived.md) |
| Crypto funding or open interest as known | `alpha context show-bybit --kind funding --symbol BTCUSDT --as-of 2024-03-12` |

## Not available yet

Say "not available yet" and name the gap; never invent the output. Planned, not built:

- regime detection with models refitted only on the past (today's regime parameters are fitted in sample),
  and change-point detection known on the day (today's change points are hindsight);
- factor attribution beyond the fixed published set; capacity and size-aware costs (flat basis points today);
- an event calendar (scheduled releases and earnings dates); a lessons search and counted variants;
- short selling, position sizing and intraday bars in the rule test (long or flat, all-in, daily bars);
- planned plain verbs (get, idea, vary, learn, promote) that would wrap these tools: none is a command yet, so never type one; use the cards above.

## How to change it

A card is at most 40 lines and names only commands that exist: `tests/unit/test_research_playbook.py` checks every command, option,
metric, flag and audit name against the program. Add a card when a tool starts to work; move a line out of "Not available yet" in the same change.
