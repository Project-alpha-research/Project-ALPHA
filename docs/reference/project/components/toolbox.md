---
owner: project layer
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/**/*.py
  - apps/alpha-cli/src/alpha_cli/tool_cmds.py
  - tests/unit/test_toolbox_*.py
verified: 0abbdb63f354f27e
---

# Toolbox

The toolbox is one catalogue of tests and analyses that can be run on a stored result. Each has a plain
question, declared inputs and settings, a plain reading and caveats, and every attempt to run one is
recorded. The owner's AI assistant uses it today; RD-Agent is meant to choose from it later.

## Why it exists

The owner wants "all possible test and system availability like permutation, parameter sensitivity, etc.":
hundreds of tests, if not thousands, not a small fixed set
([owner, 2026-11-18](../owner-decisions-5.md#2026-11-18-the-toolbox-is-an-open-catalogue-meant-to-grow-to-hundreds-of-tests)).
One uniform way to describe, find and run a test means adding one costs a small module and one entry, not a
new command, card and screen. Running many tests and quoting the favourable ones is itself overfitting, so
the record of what was run is part of the design.

## Its job in the research loop

Step 6, judging, and the "look before testing" step: after a rule test the assistant asks which tests
suit the result and runs them. Later, RD-Agent proposes ideas and may pick tests from the same catalogue;
it would not write them (a recommendation the owner has not yet confirmed,
[log](../owner-decisions-5.md#2026-11-18-rd-agent-may-choose-tests-but-not-write-them-recommendation-not-yet-confirmed)).
Kronos, the four [Monte Carlo](monte-carlo.md) methods, lookalike search and the pattern tools are
meant to become entries too, and are never slimming targets
([log](../owner-decisions-5.md#2026-11-18-kronos-the-four-monte-carlos-lookalike-and-pattern-tools-are-rd-agents-toolbox)).

## Intended design

- One explicit list of entries in `toolbox/registry.py`; no automatic discovery, so the list is readable.
- Each entry declares an id (`family.name`), a version, a question, a kind (diagnostic, test, control or
  gate), required input, settings with defaults, labelled outputs with units, a reading template filled only
  from those outputs, caveats, a cost class, whether it uses a seed, whether it is safe about time order,
  and the reference test that checks its numbers. An entry holds no statistics: it calls a function in
  `alpha_validation` or an installed library.
- The runner owns everything honest: it writes a ledger row before computing and another with the outcome,
  including errors, so a failed or unflattering attempt cannot hide. A result is stored by a key of input
  hashes, settings, seed and version, so asking again reads the stored answer and is not a new look.
- A "look" class separates describing a result (adds no trial), testing it (counted per result) and
  searching variants (would add the number of variants to the many-tries correction).
- Gates come from a frozen list that is empty today; a tool never changes a grade or a promotion.
- A tool row has a null verdict and adds zero deflation trials (the many-tries count is not changed by a tool run;
  [rule](../../invariants/cli-investigation-tools.md)).
- A single run is labelled `ad-hoc`, a non-default setting `non-default-params`, and a result whose run
  already used 2024 onward `reserved-period-seen`.
- Growth rule: moving an old tool in deletes its old command and card in the same pull request, and a test
  without a known answer (a reference value or a planted effect) does not go in.
- The accepted design (kept outside the repository so far, a known gap) expects 22 first entries, then 10 to 30
  per pull request by input kind (return statistics, trade statistics, sweeps, multi-strategy overfitting, market
  descriptions, forecast evaluation, the AFML worker).

## What is real today

Fourteen entries are registered. Three describe one recorded rule test. `market.attribution` measures exposure against full-history buy and hold,
including eligible cash dividends. `market.vol_regimes` compares calm and turbulent markets. `market.changepoints` identifies when behaviour shifted.
The named set `market-context` runs all three. Five more read the run's stored walk-forward files
instead of replaying it: `performance.downside_ratios` (Sortino, Calmar, Omega, tail ratio beside the stored
Sharpe), `robustness.start_end_dates` (25 windows with moved first and last dates, against buy and hold),
`trades.side_contribution` (long versus short), `trades.concentration` (profit without the best trades) and
`costs.break_even` (cost multiples at zero return and at buy and hold). Their [card](../../../../research/tools/run-level-checks.md) gives the definitions.
Six tests use the same stored history. The [resampling card](../../../../research/tools/resampling-checks.md) covers
Sharpe and compound yearly return intervals, independent-return drawdowns, and block-bootstrap final returns and drops.
`trades.dependence` tests the order of closed-trade outcomes. `overfit.deflated_sharpe` reuses the verdict's
family correction on the ledger count and prior comparable Sharpes frozen in the run, and states that count. See the
[family counting card](../../../../research/tools/deflated-sharpe-and-trials.md).

Each stored file's hash is part of the result's key, and a value that cannot be measured is "unavailable" with a reason. Commands: `alpha tool list` (filter by
`--for <run>`, `--search`, `--family`, `--kind`), `describe`, `run`, `run-set` and `history`. The only
target is a run id. The toolbox uses the [shared reserved date](../reserved-period.md).
Results are stored under the data directory's `diagnostics/<run>/`. See the capability on
[STATUS.md](../../../../STATUS.md).

**Not built from this batch:**
- `trades.win_rate_interval`: Wilson bounds accept win and trade counts. No public validation function
  computes the comparison rate from average realized gains and losses. The barrier break-even rate uses
  a fixed target and stop. It answers a different question.
- `resampling.bar_permutation`: the run stores the observed and null scores, but the public permutation
  test needs OHLC bars and a callable that re-scores the strategy on each new permutation. There is no
  public validation function to rank the stored scores alone.

No command or card was replaced or deleted. Later one-in-one-out candidates are the interval lines in
`alpha report`, the IID drawdown summary in `alpha monte-carlo classical`, the runs z-score shown by
`alpha figures render` and the family DSR reported by `alpha results cite`. Each command also serves other uses.

**Other work outstanding:** targets other than a run; a cut-off that hides the reserved period from tool inputs (today
it only labels, and a run made on all data has already seen it); listing in the Workstation, MCP and a
generated catalogue; counting sweep variants in the deflation; RD-Agent access (an evidence file, a fixed
set after judging, a budget, exporting causal tools as factor inputs); remaining first-batch entries
(minimum track record length waits for a function in `alpha_validation`); and
the growth plan. The 480-entry catalogue (ALPHA has 149, has part of 103, lacks 228) is the backlog but is
not yet in the repository; random-exit control remains among its highest-value gaps.

### Adding an entry

1. Write a `ToolSpec` (`toolbox/contract.py`) in a module under `toolbox/families/`
   (`costs`, `market`, `overfit`, `performance`, `resampling`, `robustness`, `trades`).
2. Add it to the explicit tuple `SPECS` in `toolbox/registry.py`. Nothing is found automatically. The fourteen registered ids:
   `market.attribution`, `market.vol_regimes`, `market.changepoints`, `performance.downside_ratios`, `robustness.start_end_dates`, `trades.side_contribution`,
   `trades.concentration`, `costs.break_even`, `resampling.sharpe_interval`, `resampling.return_interval`,
   `resampling.drawdown_distribution`, `trades.dependence`, `overfit.deflated_sharpe`, `resampling.block_bootstrap_paths`.
   Named sets are in `toolbox/sets.py` (one: `market-context`, the three market ids).
3. The entry declares its id, version, question, kind, required inputs (`needs`), settings, outputs (key, label, unit, gloss), reading, caveats,
   cost class, seeded or not, time safety, look class, a poison test when time order matters, and `reference`: the test that checks its numbers.
4. The contract refuses: an id that is not lower-case `family.name`; a reading that names something that is not an output; a `search` look without an
   evaluation count; an ordered input without a poison test; repeated output or setting names; a gate that is not in the frozen list (empty).
5. Add the reference test under `tests/unit/test_toolbox_*.py` with a known answer. Call `alpha_validation` or a library for the statistics.
6. If the entry replaces an old command and card, delete them in the same pull request.

## Where it lives

- **Workspaces:** none (inside the command-line workspace `apps/alpha-cli`, owned by [command line](command-line.md)).
- **Capabilities:** `investigation-tools`
- Code: `apps/alpha-cli/src/alpha_cli/toolbox/` (contract, inputs, runner, store, registry, sets, gates,
  reserve and family modules) and `apps/alpha-cli/src/alpha_cli/tool_cmds.py`.
- Tests: `tests/unit/test_toolbox_contract.py`, `tests/unit/test_toolbox_runner.py`,
  `tests/unit/test_toolbox_run_level_checks.py`, `tests/unit/test_toolbox_resampling_checks.py`, `tests/smoke/test_rule_tools_smoke.py`.
- How to change it: [apps/alpha-cli/CONTEXT.md](../../../../apps/alpha-cli/CONTEXT.md); rules in
  [investigation tools](../../invariants/cli-investigation-tools.md). Tool cards: `research/tools/`.
- **Plan:** the toolbox rows of the [AI partner stage](../../../roadmap/production-scope-2.md#8-ai-partner) of the checklist.
- Example card: [market family](../../../../research/tools/attribution-regimes-changepoints.md).

## Decisions and open questions

- Decided 2026-11-18: open catalogue, hundreds of tests (linked above; [decisions log](../owner-decisions.md), volume 5).
- Recommended, not confirmed: RD-Agent chooses tests but does not write them.
- Open, for the owner: the reserve policy (one date for everything, a tail per idea, or labels only; who
  may reveal it) in [ideas and things considered](../ideas-and-considered.md#open-questions); when sweep
  variants enter the deflation count; which stored gauntlet results join the frozen gate list; RD-Agent's
  budget; whether a declared plan is needed before citing evidence toward promotion; who reviews new statistics.

## Never

- Never let a tool change a grade, verdict or promotion; only the owner decides.
- Never let RD-Agent set test settings, write to the gate list or read the reserved period.
- Never hide an attempt, an error or an unfavourable result from the history.
- Never add statistics inside the toolbox; call `alpha_validation` or a library.
- The rules: [investigation tools](../../invariants/cli-investigation-tools.md).
