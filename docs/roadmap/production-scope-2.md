---
owner: status page and roadmap
sources:
  - docs/reference/project/owner-decisions-3.md
verified: 3fd2dac8724c4b7e
---

# Production-ready scope, part 2: overfit tests to engines

Continues [the checklist](production-scope.md), where reading a row is explained; it ends in
[part 3](production-scope-3.md).

## 5. Overfit tests

Telling a real edge from luck after many tries.

| Capability | State | Where | By | Source |
|---|---|---|---|---|
| Walk-forward testing with gaps between train and test | Working | `alpha-validation` | Now | [status] |
| Luck-adjusted scores: deflated Sharpe, overfitting probability, combinatorial splits | Working | `alpha-validation` | Now | [status] |
| Random-price and shuffled-bar comparisons | Working | `alpha-validation` | Now | [status] |
| Bootstrap ranges (block resampling) around results | Working | `alpha-validation` | Now | [status] |
| Permutation test of a parameter sweep; best-of-many reality checks | Unproven | `alpha-validation` | Path 1 | [grade] |
| Corrections for testing many ideas at once | Unproven | `alpha-research` | Path 3 | [grade] |
| Trial ledger for RD-Agent's factors, failures kept | Working | `workers/rdagent` | Now | [status] |
| Every test, tool and variant counted in one ledger; the count printed on each result | Unproven | `alpha ledger`: one read model over the spine and RD-Agent ledgers | Path 1 | [partner] |
| Locked final period, sealed by date; touching it marks the result for good | Unproven | `alpha-cli` judge | Path 1 | [precise] |
| Log of every look at the locked period | Unproven | pull request 178 | Path 3 | [precise] |
| Variants of one idea counted as one family, with the effective number of tests shown | Missing | `alpha ledger families`; the rule test's deflated Sharpe and verdict count the family; effective number not yet | Path 1 | private |
| Path-risk simulation in three families (a fourth, Kronos paths, runs on a stand-in) | Working | `alpha-validation` | Now | [kronos] |
| Sensitivity to nearby parameter values | Unproven | `alpha-cli` optim | Path 1 | [grade] |
| Sample-size check: is there enough data to say anything | Unproven | `alpha-research` | Path 2 | private |
| Quick-screen score corrected for overlapping windows (the weights exist; nothing uses them yet) | Missing | `workers/afml` | Later | [status] |
| Prop-firm challenge check, as an optional tool and never the goal | Unproven | `alpha-validation` | Later | [status] |
| Labels with a target, a stop and a time limit | Working | `alpha labels barrier`; the splits for multi-day labels are in stage 9 | Now | private |
| Second-opinion overfitting numbers and the minimum track record a result needs | Unproven | `workers/afml` stats; tested in-process, no end-to-end check ([toolkit](backlog/afml-toolkit-worker.md)) | Path 1 | private |
| Combined signals never count the same input twice as evidence | Missing | ledger; [practice](backlog/practitioner-research-ideas.md) | Later | private |
| Walk-forward efficiency (out-of-sample over in-sample result), labelled as a rule of thumb | Working | [efficiency](../../research/tools/walk-forward.md) in `alpha diagnose` | Now | private |
| Inverted-signal control: the opposite trade must lose, or the edge is a data artefact | Working | [control](../../research/tools/inverted-signal-control.md) in `alpha diagnose`; a check, not proof | Now | private |
| Robustness to noise added to the price series, re-running the rule on perturbed prices | Working | [price noise](../../research/tools/price-noise.md) in `alpha diagnose`; feed sensitivity, not proof | Now | private |

## 6. Diagnostics

Explaining a result: where the profit and the losses came from.

| Capability | State | Where | By | Source |
|---|---|---|---|---|
| Automatic diagnostic pass after every test: facts and flags in plain sentences | Working | `alpha diagnose` | Path 1 | [partner] |
| Drawdown episodes listed and dated | Working | `alpha-validation` | Now | [status] |
| Drawdown against market and sector: beta, share of loss on down-market days | Unproven | `alpha diagnose`: same-asset benchmark only | Path 1 | [partner] |
| Macro picture for the dates of a loss: rates, releases, volatility | Missing | needs macro data | Later | [partner] |
| Results by market state (volatility, trend, correlation) known on the day | Unproven | `alpha-research` | Path 1 | [partner] |
| Regime detection and change points on a run: causal regime labels, in-sample model labelled, change points labelled hindsight | Working | `alpha tool run market.vol_regimes`, `alpha tool run market.changepoints` | Path 1 | [partner] |
| Regime models refitted only on the past (no in-sample parameters) | Missing | `alpha-validation` | Later | [partner] |
| "What is unusual right now?": the latest bars scored against every earlier stretch, known on the day | Working | `alpha unusual` (STUMPY); no screen yet | Now | private |
| "Was it knowable that day?" check for macro and regime labels | Missing | `alpha-research` | Later | private |
| Results by calendar: year, month, weekday, session | Unproven | `alpha-cli` figures | Path 1 | [partner] |
| Profit concentration: how much comes from a few trades, days or assets | Unproven | `alpha diagnose`: trades only | Path 1 | [partner] |
| Cheap stress re-runs: double costs, enter one bar late | Working | `alpha diagnose` | Path 1 | [partner] |
| Exposure to the market or one chosen asset, such as SPY or Bitcoin: beta, leftover return, up and down beta | Working | `alpha tool run market.attribution` | Path 1 | [partner] |
| Exposure to size and momentum factors | Missing | statsmodels | Later | [partner] |
| Signal, sizing, exposure and cost effects told apart | Missing | `alpha-validation` | Later | private |
| Trade streaks, clustering, lead-lag and stability splits | Unproven | `alpha-research` | Path 2 | [partner] |
| Risk figures that state their basis (value at risk, expected shortfall) | Working | `alpha-validation` | Now | [status] |
| Each risk quantity shown apart: planned loss, size, leverage, volatility, stress loss | Missing | `alpha-validation` | Later | private |
| Stress scenarios that can move the drawdown | Missing | backlog | Later | [status] |
| Kronos forecast ranges as an exploratory view | Unproven | `alpha-forecast` | Later | [kronos] |
| Process, market exposure and chance told apart; capital tied up and for how long | Missing | `alpha diagnose` | Later | private |
| Named crisis replays (2008, March 2020, the 2022 crypto bear, flash crashes) with settings unchanged | Missing | `alpha-validation`; [note](backlog/risk-shock-placement.md) | Later | private |
| Synthetic crisis stress: correlations pushed toward one, liquidity that dries up, partial fills | Missing | `alpha-validation`; [note](backlog/risk-shock-placement.md) | Later | private |
| A "too good to be true" label for results far above what a retail swing book plausibly earns after costs | Working | `alpha diagnose`: `implausibly-good`; a prompt to check data, never a verdict | Path 1 | private |
| Automatic scan of many candidate context features against each trade's loss, run-up and profit, with the number scanned counted | Missing | `alpha-research`; [note](backlog/rescued-research-ideas.md) | Later | private |

## 7. Records and memory

What is kept, how it is labelled, and what the system remembers.

| Capability | State | Where | By | Source |
|---|---|---|---|---|
| Reopen any stored run with its report | Working | `alpha-cli` reports | Now | [status] |
| Runs compared side by side, differences computed by code (`alpha results compare`) | Working | `alpha-cli` results | Now | [status] |
| Figures exported for a run | Unproven | `alpha-cli` reports | Path 1 | [status] |
| One folder per idea linking the question, the spec and every run | Missing | data folder | Path 1 | [partner] |
| Investigation trail per idea: seen, considered, tested, learned, next | Missing | data folder | Path 1 | [partner] |
| Lessons written down, searched before each proposal, pruned weekly | Unproven | `research/lessons`: format only, none yet | Path 1 | [partner] |
| Integrity as labels on results, not refusals (exploratory, free data, trial count) | Working | run records and ledger | Path 1 | [any-bar] |
| Honest status words on findings: read, run, reproduced, validated | Missing | run records | Path 1 | private |
| Failed and rejected variants stay visible | Unproven | trial ledger | Path 3 | private |
| RD-Agent's own memory kept between runs | Missing | `workers/rdagent` | Path 3 | [rd-all] |
| Ledger summary and lessons given to RD-Agent before it proposes | Unproven | `workers/rdagent` | Path 3 | [rd-all] |
| Evidence of every judged trial kept: daily results, code by hash, reasons per round | Unproven | pull request 183 | Path 3 | [ui] |
| Earlier studies and trials imported as history | Unproven | pull request 178 | Path 3 | private |
| Per-asset page gathering everything learned about one market | Missing | `alpha-web` | Later | private |
| "How this was computed": data, steps and code version behind each finding | Missing | `alpha-web` | Path 1 | private |
| Staged research cases with an approval at each stage (the old lane) | Dropped | `alpha-research` | Path 1 | [thin] |
| Conclusions flagged for review when their data or source is revised or withdrawn | Missing | idea folder; [practice](backlog/practitioner-research-ideas.md) | Later | private |
| Each claim labelled descriptive, predictive or causal | Missing | run records; [practice](backlog/practitioner-research-ideas.md) | Later | private |
| An earlier private pattern study kept as history and as a chart-setup test case | Missing | idea folder; [note](backlog/rescued-research-ideas.md) | Path 2 | private |

## 8. AI partner

The AI as a research partner that drives the toolbox from a prompt.

| Capability | State | Where | By | Source |
|---|---|---|---|---|
| About nine plain verbs in front of today's long command list | Missing | `alpha-cli` | Path 1 | [partner] |
| One-page research playbook that teaches a method, not a script | Unproven | `research/PLAYBOOK.md` | Path 1 | [partner] |
| Tool cards indexed by symptom, so the AI finds a tool it was never told about | Unproven | `research/tools` | Path 1 | [partner] |
| The AI proposes next steps with reason, value and cost; says when evidence disagrees | Unproven | playbook and skills: text only | Path 1 | [partner] |
| A drafted answer's tagged numbers and run labels checked against the stored records and flags (`alpha results check`; not the reasoning) | Working | `alpha-cli` results | Now | [precise] |
| The AI must run that check on every draft before sending it | Unproven | playbook and the report skills say so; no test shows an AI follows it | Path 1 | [precise] |
| Tool server so Claude or Codex can call ALPHA, cut down to the nine verbs | Unproven | `apps/alpha-mcp` | Path 1 | [grade] |
| Connection for the Claude and ChatGPT apps, not only the terminal | Missing | `apps/alpha-mcp` | Later | [grade] |
| A review step that audits a result for defects | Unproven | `alpha diagnose` audit; `review-result` skill | Path 1 | [grade] |
| Ask an in-product assistant about a recorded run | Unproven | `alpha-cli`; `alpha-web` | Later | [status] |
| Planted honest and dishonest answers prove the checker catches invented numbers (`alpha partner selftest`) | Working | `alpha-cli` partner | Now | [precise] |
| Platform journey check: seeded scenarios with a known cause, scored weekly | Rebuild | `alpha partner selftest` covers the answer-honesty part only: 25 planted answers, no model calls; not scheduled weekly | Path 1 | [slim] |
| Small autonomous research team around RD-Agent | Missing | backlog | Later | [team] |
| Text from papers and the web can never run tools or unlock anything | Unproven | `workers/literature` | Later | private |
| Sources an answer actually used recorded, apart from sources only retrieved | Missing | `alpha-cli` results; [note](backlog/rescued-partner-ideas.md) | Later | private |
| Call and dollar caps on RD-Agent's model use | Working | `workers/rdagent` gateway | Now | [status] |
| An advisor that reads whole books and papers from the owner's library into context, with claim-level checks on what it says | Missing | `workers/literature`; [note](backlog/rescued-partner-ideas.md) | Later | private |

## 9. RD-Agent and Qlib engines

The pinned upstream engines and how much of each ALPHA uses.

| Capability | State | Where | By | Source |
|---|---|---|---|---|
| RD-Agent's factor loop with a real model on real bars, judged by ALPHA | Working | `workers/rdagent` | Now | [status] |
| That loop started by `alpha` as a watched job that survives a crash | Missing | backlog | Path 3 | [status] |
| Loop settings chosen per prompt: horizon, rebalance pace, universe, lock date | Missing | `alpha-cli` judge | Path 3 | [any-bar] |
| RD-Agent's model loop and its combined factor-and-model loop | Missing | `workers/rdagent` | Path 3 | [rd-all] |
| RD-Agent's own report reader and run viewer used instead of rebuilt | Unproven | `workers/rdagent` | Path 3 | [rd-all] |
| A candidate from the loop handed to the owner's one gate | Missing | backlog | Path 3 | [status] |
| Qlib's upstream price features (Alpha158) | Working | `workers/qlib` | Now | [status] |
| Qlib's full model list, with retraining fold by fold | Missing | backlog (shelved start) | Later | [engines] |
| Qlib's rolling updates, portfolio strategies and nested execution | Missing | `workers/qlib` | Later | private |
| RD-Agent driving the Qlib worker | Unproven | `alpha-cli` (shelved) | Path 3 | [triage] |
| ALPHA's copies of upstream maths retired after a side-by-side check | Missing | several packages | Path 3 | [thin] |
| Nautilus as the pinned backtest engine | Working | `alpha-backtest` | Now | [engines] |
| Kronos with real model files, not a stand-in | Unproven | `alpha-forecast` | Later | [kronos] |
| Automatic checks covering the RD-Agent worker, with a scripted-model smoke run | Missing | backlog | Path 3 | [status] |
| Textbook labels and overlap weights from two pinned libraries that must agree | Working | `alpha labels`, `workers/afml` | Now | [status] |
| Factor importance on purged folds (MDI, MDA, SFI), a report for RD-Agent's factors | Working | `alpha labels importance` | Now | [status] |
| Purged splits by label end time, with embargo, backtest paths and a leak checker | Unproven | `workers/afml` | Path 3 | [status] |
| Fractional differencing with d chosen on training data only | Unproven | `workers/afml` | Path 3 | [status] |
| Second opinions on PSR, DSR, PBO; minimum track record; strategy risk | Unproven | `workers/afml` | Path 1 | [status] |
| One-shot confirmation of shortlisted factors on the reserved data (approved by the owner 2026-11-18, not started; queued behind the screens) | Missing | `workers/rdagent`, `alpha-cli` judge | Path 3 | private |
| Every automatic refusal shown with its reason and open to the owner's override (orchestrator's plan, 2026-11-18) | Missing | `workers/rdagent`, `alpha-cli` judge, `alpha-web` | Path 3 | private |
| A "propose and discuss" mode: the agent shows its ideas and reasoning before any spending (orchestrator's plan) | Missing | `workers/rdagent`, `alpha-cli` | Path 3 | private |
| RD-Agent's reasoning shown on screen, with honesty checks as labels on results (orchestrator's plan) | Missing | `alpha-web` | Path 3 | private |
| A map of everything Qlib and RD-Agent offer, each item with a state | Missing | [coverage maps](backlog/engine-coverage-maps.md) | Path 3 | [rd-all] |
| Feature attribution (SHAP-style) for tree models, tracked over time as an early drift warning | Missing | `workers/qlib`; [note](backlog/engine-coverage-maps.md) | Later | private |
| Automated loops scored on out-of-sample result, complexity and trade count, not return alone | Missing | `workers/rdagent`; [note](backlog/rescued-research-ideas.md) | Path 3 | private |
| An overnight batch of experiments ending in a short morning list of top candidates for the owner | Missing | `workers/rdagent`; [note](backlog/rdagent-autonomous-research.md) | Path 3 | private |

[any-bar]: ../reference/project/owner-decisions-3.md#2026-11-15-no-daily-only-rule-fewer-strict-rules
[engines]: ../reference/project/owner-decisions.md#2026-11-14-the-architecture-in-one-line
[grade]: ../reference/project/owner-decisions-3.md#2026-11-15-what-production-grade-means
[kronos]: ../reference/project/owner-decisions.md#2026-11-14-what-kronos-is-for
[partner]: ../reference/project/owner-decisions-3.md#2026-11-15-the-ai-must-be-a-research-partner-not-an-instruction-follower
[precise]: ../reference/project/owner-decisions.md#2026-11-14-precision-and-live-capital
[rd-all]: ../reference/project/owner-decisions-3.md#2026-11-15-adopt-everything-rd-agent-has-memory-first
[slim]: ../reference/project/owner-decisions-3.md#2026-11-15-always-slimmer
[status]: ../../STATUS.md
[team]: ../reference/project/owner-decisions.md#2026-11-14-the-autonomous-research-team
[thin]: ../reference/project/owner-decisions-2.md#2026-11-14-thin-alpha-dramatically-rd-agent-and-qlib-are-the-proven-core
[triage]: triage-2026-11.md
[ui]: ../reference/project/owner-decisions-2.md#2026-11-14-keep-the-user-interface
