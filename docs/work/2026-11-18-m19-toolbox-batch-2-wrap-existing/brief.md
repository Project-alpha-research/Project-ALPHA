# Brief: Toolbox batch 2 — reach the validated statistics that no command reaches

**Build class:** hard

## Task

`packages/alpha-validation` holds proven statistics (bootstrap, Monte Carlo families, trade
dependence, proportion tests, permutation tests, deflated Sharpe, overfitting probability) that
a rule-test run cannot reach through the toolbox. The owner wants hundreds of tests reachable
(permutation, Monte Carlo, parameter sensitivity and more). The cheapest honest growth is to
wrap what already exists and is already tested. Add up to eight registry entries that call
existing `alpha_validation` functions on what a rule-test run stores. Write no statistic.

## Read first

| Read | Section | When |
|---|---|---|
| `apps/alpha-cli/CONTEXT.md`, `docs/reference/project/components/toolbox.md`, `docs/reference/project/components/monte-carlo.md` | whole | always |
| `apps/alpha-cli/src/alpha_cli/toolbox/` | every file; `families/performance.py`, `robustness.py`, `costs.py` are the pattern | always |
| `packages/alpha-validation/src/alpha_validation/` (read only): `bootstrap.py`, `montecarlo.py`, `path_montecarlo.py`, `bar_permutation.py`, `mcpt.py`, `trade_dependence.py`, `proportion.py`, `dsr.py`, `overfitting.py`, `metrics.py` | public functions, their inputs, seeds, defaults, cited sources | always |
| `tests/unit/test_toolbox_run_level_checks.py`, `tests/fixtures/toolbox_run_level_checks.json` | test pattern | always |
| `research/tools/` cards for Monte Carlo, bootstrap and deflated Sharpe | what existing commands already expose, to avoid a second door to the same thing | always |

## Decision already made

1. **Pick up to eight** entries from this list, in this order, building each one only if an
   existing public `alpha_validation` function computes it from inputs a rule-test run stores
   (scored-period bar returns, trades, equity, the two per-bar cost columns):
   a. `resampling.sharpe_interval` — bootstrap confidence interval for the Sharpe ratio
      (kind `test`, look class `test`).
   b. `resampling.return_interval` — bootstrap interval for the yearly return.
   c. `resampling.drawdown_distribution` — Monte Carlo on the order of trades or returns:
      the range of worst drops the same trades could have produced, and where the realised
      worst drop sits in it.
   d. `trades.dependence` — are wins and losses clustered (runs / serial-correlation test)?
   e. `trades.win_rate_interval` — interval for the win rate against 50% and against the
      break-even win rate implied by the average win and loss.
   f. `overfit.deflated_sharpe` — the deflated Sharpe for this run given the ledger's count of
      ideas tested (the count the registry already exposes).
   g. `resampling.bar_permutation` — permutation test of the rule's result against the same
      rule's stored result on permuted bars, ONLY if the stored run already holds what the
      function needs; never re-run the strategy from the toolbox in this batch.
   h. `resampling.block_bootstrap_paths` — block-bootstrap range of final equity.
   For each one not built, say exactly why (no function, or a needed input is not stored).
2. **Rules for every entry.**
   - Call the existing function with its documented defaults; expose only parameters the
     function already has (resamples, block length, confidence level, seed), with those
     defaults. A non-default value is labelled by the runner as today; the seed counts as a
     setting tried, as today.
   - Seeded and reproducible: the same request gives the same result; state the seed in the
     output.
   - Kind and look class set honestly: `test` for anything that yields a p-value or interval.
     No entry is a `gate`. No entry searches over parameters, so none is look class `search`.
   - Each declares inputs, outputs with plain labels and units, one plain reading sentence, and
     a "cannot tell you" sentence that names the main assumption (for example: bootstrap
     assumes the future resembles the sampled past; trade-order Monte Carlo assumes trades are
     independent, which `trades.dependence` checks).
   - Honest edge cases: fewer observations than the function needs gives "not measurable"
     with the reason and the minimum needed; never a zero, infinity or a made-up interval.
   - No pandas inside `toolbox/` (semgrep). No statistic, resampling loop or formula written in
     `toolbox/`: glue only (read stored series, call, label, format).
   - Where an existing `alpha` command already exposes the same statistic, the entry must call
     the same function with the same defaults, and the tool card says the two give the same
     number. Do not remove the existing command in this batch; list it as a later one-in-one-
     out candidate.
3. **Tests.** For each entry: the result equals a direct call to the `alpha_validation`
   function on the same series with the same seed (so the entry adds no arithmetic of its own);
   one behaviour test on a series built so the answer's direction is known (for example a
   strongly positive series has an interval above zero; alternating win/loss trades are
   flagged as dependent); the edge case. Reference results in a JSON fixture compared with
   `pytest.approx(rel=1e-9, abs=1e-12)`; never hash floats. Resampling counts in tests kept
   small enough that the file runs in under 30 seconds.
4. **Docs.** One card per family at most (`research/tools/resampling-checks.md`, extend
   `run-level-checks.md` for the trade entries; cards ≤ 40 lines), the cite list, the toolbox
   component page (entry count, "Not built" list), the Monte Carlo page if an entry reaches one
   of the four methods, the capability record. Nothing is replaced, so nothing is deleted: say
   so, and list the one-in-one-out candidates.

## Files

Edited:
- `apps/alpha-cli/src/alpha_cli/toolbox/registry.py`
- `apps/alpha-cli/src/alpha_cli/toolbox/inputs.py`
- `tests/unit/test_toolbox_contract.py`
- `research/tools/run-level-checks.md`
- `research/tools/results-and-cite.md`
- `research/tools/README.md`
- `docs/reference/project/components/toolbox.md`
- `docs/reference/project/components/monte-carlo.md`
- `apps/alpha-cli/CONTEXT.md`
- `docs/roadmap/capabilities.toml`

New:
- `apps/alpha-cli/src/alpha_cli/toolbox/families/resampling.py`
- `apps/alpha-cli/src/alpha_cli/toolbox/families/trades.py`
- `apps/alpha-cli/src/alpha_cli/toolbox/families/overfit.py`
- `tests/unit/test_toolbox_resampling_checks.py`
- `tests/fixtures/toolbox_resampling_checks.json`
- `research/tools/resampling-checks.md`

This decision overrides the standing rule for: any file under
`apps/alpha-cli/src/alpha_cli/toolbox/` (existing trade entries may move into
`families/trades.py` if that keeps one home per family; ids must not change); test files
`tests/unit/test_toolbox_*.py` and their fixtures; generated pages, the capability trace and
the triage sheet the capability and command tests require (regenerate generated pages with
their scripts); any living document `scripts/fs.py stale` reports because of your edits
(verify with a real text change or `--reason`). If a named file does not exist, use the real
one. List each in the report; do not stop to ask; where a rule is open choose the more
cautious reading and state it.

## Do not touch

`packages/**` (read only), `workers/**`, `apps/alpha-web/**`, `tests/bias_guards`,
`tests/oracles`, `.semgrep/`, `.github/`, `.claude/`, `.agents/`, `scripts/`, `uv.lock`. The
runner's honesty rules, the store, the ledger row format, the frozen gate list. No `nosemgrep`,
`noqa`, `type: ignore`, `vars(`, `__doc__`, `inspect`, `.__dict__`; no use of private
(underscore) helpers of `alpha_validation`. Functions ≤ 150 lines, files ≤ 1,500 lines; tests
fully type-annotated; no test file named `*fixups*` or ending `_<N>.py`. No negative shifts.

## Checks

- `uv run pytest -q tests/unit/test_toolbox_resampling_checks.py tests/unit/test_toolbox_run_level_checks.py tests/unit/test_toolbox_contract.py tests/unit/test_toolbox_runner.py`
- `uv run pytest -q tests/unit -k "toolbox or spine or capabilities or code_size or filesystem or docs_links or playbook or command"`
- `uv run pytest -q tests/bias_guards`
- `uv run python scripts/gate.py semgrep`
- `uv run python scripts/fs.py stale`
- `uv run python scripts/gate.py check --base origin/main`

## Report

Per entry: id, the exact `alpha_validation` function and defaults, the stored inputs, the
reading sentence, the "cannot tell you" sentence, the three tests. Entries not built and why.
Existing commands that expose the same statistic (one-in-one-out candidates). Lines added.
Every file outside the list. Open readings chosen. What is unverified.
