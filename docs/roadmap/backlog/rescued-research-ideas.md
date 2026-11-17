# Research-method ideas recovered from earlier material

**Status:** Idea
**Rough size:** M

## Problem / why

Plans and ideas from the owner's earlier private plans and research that no capability row or note
carried. Restated in plain words; the originals stay outside git.

- Walk-forward efficiency (out-of-sample result over in-sample result) as a reported number, shown
  as a rule of thumb and never as a derived threshold.
- An inverted-signal control: the opposite trade must lose; if it also wins the edge is a data
  artefact.
- A verified source library: papers, books and tools grouped by topic, each checked to exist. Known
  corrections to keep: a commonly quoted minimum trade count is only a sample-size formula, and the
  half-efficiency rule is a practitioner guideline; one indicator library is poorly maintained.
- An earlier pattern study exists privately. It is a candidate to import as history and to reuse
  as a chart-setup test case on the first golden paths.
- On-chain and sentiment inputs for swing work: network value ratios, exchange net flows,
  profit-and-loss measures, stablecoin ratios, active addresses, dominance, a fear index. Data
  adapters exist; no research uses them yet.
- Position sizing breadth: fractional Kelly, risk parity, sleeves and correlation analysis, with
  drawdown limits.
- Multiple-testing hurdles: a higher t-statistic bar for many tested ideas, haircut Sharpe
  (Bonferroni, Holm, a false-discovery variant) and the model confidence set.
- Regime resilience: calibration with support counts, telling input drift from signal decay from
  dependence shocks, an abstention contract, and frozen champion and challenger shadow tracking.
- Research-acceptance additions: search effort added up across studies, sensitivity to how often
  useful ideas occur, a shortlist of feasible ideas, reuse of negative results without leaking
  sealed ones, a next-test-or-stop trace, a frozen-incumbent comparison, and an original versus
  adaptation versus destination comparison for paper ideas.
- Open questions: overfitting at the level of a whole portfolio of strategies, strategy capacity
  against size, correlation in crises, and a feedback loop from live execution quality to the model.

## Where it would live

[Checklist stages 1, 2, 5 and 7](../production-scope.md); `research/` and the idea folder.

## What "done" looks like

Each item is a checklist row, a line in the playbook, an ADR, or dropped by the owner.

## Dependencies

[Practitioner ideas](practitioner-research-ideas.md); [risk shocks](risk-shock-placement.md).

## Sources

- [Checklist stage 5](../production-scope-2.md#5-overfit-tests), [stage 7](../production-scope-2.md#7-records-and-memory)

## More recovered from the second pass

- Idea check against publication date: compare a published edge before and after it became public.
- Noise robustness: re-run a rule on prices with added noise; a cliff means a fitted rule.
- A plausibility label for results far above a retail swing book's usual net range; a label, not a threshold.
- Automated-loop score: out-of-sample result, complexity (parameter count) and a trade-count floor.
- Scan many context features against trade loss, run-up and profit; count every feature scanned.
- Before-entry profile of winners and losers beside a random-date control.
- Feature building: say what you care about, find the raw data, choose the type, then transform
  (percent not price units, ratio of short to long range, rarity score) and plot examples.
- Event sampling: show event count against the threshold, since too many events is noise and too few
  leaves no sample; scale thresholds by volatility.
- Regime stack: require a hidden-state model, a switching model and change detection to agree before
  declaring a regime; then switch strategy, adjust settings or scale risk by regime.
- Published chart-pattern statistics kept as base-rate priors for the first pattern studies.
