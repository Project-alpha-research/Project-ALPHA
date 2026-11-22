---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/overfit_controls*.py
  - tests/unit/test_toolbox_overfit_controls.py
---

# Overfitting controls on one rule test

**Reach for these checks when** a result looks too good and you want to know how much luck, tries or a short history could explain it.

| Question | Command |
|---|---|
| How likely is the true Sharpe ratio to beat a benchmark? | `alpha tool run overfit_controls.probabilistic_sharpe <run_id>` |
| How long a record does this Sharpe ratio need? | `alpha tool run overfit_controls.min_track_record <run_id>` |
| How much should the Sharpe ratio be cut for the tries? | `alpha tool run overfit_controls.haircut_sharpe <run_id>` |
| How many years of history do this many tries need? | `alpha tool run overfit_controls.min_backtest_length <run_id>` |
| What best Sharpe ratio would pure noise reach? | `alpha tool run overfit_controls.noise_best_sharpe <run_id>` |
| Does the Sharpe ratio beat luck at a stated try count? | `alpha tool run overfit_controls.deflated_at_tries <run_id>` |
| Is the t-statistic above the multiple-testing reference? | `alpha tool run overfit_controls.t_stat_hurdle <run_id>` |
| Is the sample big enough to say anything of the win rate? | `alpha tool run overfit_controls.trade_count <run_id>` |
| How much history detects a Sharpe ratio of a given size? | `alpha tool run overfit_controls.required_history <run_id>` |
| Did the evidence reach a sequential-test limit? | `alpha tool run overfit_controls.sequential_test <run_id>` |
| What is the Sharpe ratio after shrinking toward a sceptical prior? | `alpha tool run overfit_controls.shrunk_sharpe <run_id>` |

**How to read it**

- All use the scored after-cost bar returns of the stored run (trades for `trade_count`) and the run's own bars per year.
- Checks that take `n_trials` use the count recorded with the run when you leave it at 0. With no recorded count they say so.
- Each gives numbers and a sentence, never a pass or a fail. Each needs at least 30 scored bars, and says so when it has fewer.

**What these checks cannot tell you** They assume independent bar returns and independent tries. Correlated tries
need less correction. None shows that an edge exists. For the tries recorded in the ledger, use `overfit.deflated_sharpe`.

**Next** [Deflated Sharpe and trials](deflated-sharpe-and-trials.md). [Cite](results-and-cite.md) the stored output.
