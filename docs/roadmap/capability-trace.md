# Capability trace: the capability map against the checklist

Links each workflow in the [capability map](capabilities.toml) (what [STATUS.md](../../STATUS.md) shows)
to the [checklist](production-scope.md) row it serves, so neither list can drift from the other.
`tests/unit/test_filesystem_contract.py` fails when a capability id is missing here, when a row
named here is not in the checklist word for word, or when a Working checklist row is in neither
table. A capability may serve several rows; a row may be served by several capabilities.

## Capability to row

| Capability | Checklist row |
|---|---|
| `workstation` | The Workstation opens in a browser |
| `price-charts` | Dense multi-panel price charts, full screen, trade markers, two chart styles |
| `stock-data` | Daily stock and ETF bars from a free source, frozen and verified |
| `stock-data` | Results on free data labelled not yet confirmed |
| `intraday-bars` | Any bar size from one minute up; the daily-only refusal removed |
| `crypto-data` | Daily crypto bars: download, resume, freeze into a snapshot, verify |
| `crypto-backfill` | Daily crypto bars: download, resume, freeze into a snapshot, verify |
| `download-bookkeeping` | Download receipts and quota bookkeeping |
| `funding-download` | Crypto context: funding rates, open interest, listings |
| `crypto-derivatives-context` | Crypto context: funding rates, open interest, listings |
| `filing-events` | Event calendar: central-bank meetings, inflation releases, an earnings-date proxy |
| `price-lookalikes` | "Has this happened before?": every earlier stretch shaped like the latest bars, and what followed, on one figure |
| `price-novelty` | "What is unusual right now?": the latest bars scored against every earlier stretch, known on the day |
| `retained-coverage` | Completeness check on downloaded bars |
| `crypto-snapshots` | Reads see only what was known then; snapshots and receipts never change |
| `backtest` | One-asset rule backtest with costs: decide at a close, fill at the next open |
| `backtest` | Rank many assets by a factor and replay the basket with costs |
| `backtest` | Nautilus as the pinned backtest engine |
| `run-reports` | Reopen any stored run with its report |
| `rules-and-scans` | Simple rule language ("close above X and Y"), saved and rerun exactly |
| `strategy-development` | Strategy development workspace (fixed approved steps) |
| `validation-gauntlet` | Walk-forward testing with gaps between train and test |
| `validation-gauntlet` | Luck-adjusted scores: deflated Sharpe, overfitting probability, combinatorial splits |
| `validation-gauntlet` | Random-price and shuffled-bar comparisons |
| `validation-gauntlet` | Bootstrap ranges (block resampling) around results |
| `validation-gauntlet` | Drawdown episodes listed and dated |
| `monte-carlo` | Path-risk simulation in three families (a fourth, Kronos paths, runs on a stand-in) |
| `risk-numbers` | Risk figures that state their basis (value at risk, expected shortfall) |
| `prop-firm-check` | Prop-firm challenge check, as an optional tool and never the goal |
| `price-forecasts` | Kronos forecast ranges as an exploratory view |
| `research-cases` | Staged research cases with an approval at each stage (the old lane) |
| `quick-screening` | Quick recorded first look at many ideas |
| `literature` | Find papers, screen their claims, tie a claim to its test, keep the PDF |
| `paper-to-experiment` | Find papers, screen their claims, tie a claim to its test, keep the PDF |
| `ai-investigations` | Ask an in-product assistant about a recorded run |
| `ai-tools-connection` | Tool server so Claude or Codex can call ALPHA, cut down to the nine verbs |
| `providers-and-jobs` | Provider checks and a job list for long downloads |
| `paper-trading` | Paper trading: local crypto practice account or a broker practice account |
| `ml-lab` | Machine-learning models trained by Qlib and replayed with costs |
| `alpha158-v2` | Qlib's upstream price features (Alpha158) |
| `alpha158-v3` | Qlib's upstream price features (Alpha158) |
| `qlib-refit` | Qlib's full model list, with retraining fold by fold |
| `qlib-in-research-cases` | Staged research cases with an approval at each stage (the old lane) |
| `native-engine-demos` | Chat panels and demo views folded away once their content shows elsewhere |
| `ai-stock-research` | RD-Agent's factor loop with a real model on real bars, judged by ALPHA |
| `ai-stock-research` | Trial ledger for RD-Agent's factors, failures kept |
| `ai-stock-research` | Call and dollar caps on RD-Agent's model use |
| `rdagent-run-viewer` | RD-Agent's own report reader and run viewer used instead of rebuilt |
| `native-job-result` | RD-Agent results readable in the Workstation |
| `daily-rule-study` | Say an idea in plain English to Claude or ChatGPT and the whole pipeline runs it |
| `ai-research-team` | Small autonomous research team around RD-Agent |
| `mac-real-data` | Confirmation on the Mac with a paid, authoritative data source |
| `macro-context` | Macro series as first published: rates, inflation, jobs, credit, volatility index |
| `rule-test` | The same backtest on real free data, shown on a screen |
| `rule-test` | Plain rules tested as written, with no hidden sizing or rebalancing defaults |
| `rule-test` | Integrity as labels on results, not refusals (exploratory, free data, trial count) |
| `result-diagnostics` | Automatic diagnostic pass after every test: facts and flags in plain sentences |
| `result-diagnostics` | Cheap stress re-runs: double costs, enter one bar late |
| `answer-check` | A drafted answer's tagged numbers and run labels checked against the stored records (`alpha results check`; not the reasoning) |
| `answer-check` | Runs compared side by side, differences computed by code (`alpha results compare`) |

## Working rows that are not a workflow

| Checklist row | Why no capability |
|---|---|
| Weekly automatic health check that opens small clean-up pull requests | a scheduled task, not an `alpha` workflow |
| One gate for every change: look-ahead guards, statistical oracles, repeatable runs | the delivery check (`scripts/gate.py`) |
| File system that says what each part is for, updated with every change | documentation, checked by the contract test |
| Generated status page of what works | generated from the capability map itself |
| Never high-frequency trading: nothing built for ticks, order books or speed | a scope rule |
| Every capability traced to a checklist row, every command to a capability | this page and its test |
