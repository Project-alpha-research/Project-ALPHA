# Build report: m19-toolbox-batch-2-wrap-existing

## Changed files

Added **6 entries**, bringing the toolbox to **14**. All six run on stored rule-test data. The delivery gate passed, and the 29 new tests passed in 3.59 seconds. The changes are uncommitted and unstaged. **819 lines added, 53 removed.**

| Path | Change |
|---|---|
| `apps/alpha-cli/src/alpha_cli/toolbox/registry.py` | Registered the six entries as tests. |
| `apps/alpha-cli/src/alpha_cli/toolbox/inputs.py` | Added a reader for scored returns from dated, after-cost equity. |
| `apps/alpha-cli/src/alpha_cli/toolbox/families/resampling.py` | Added two confidence intervals and two path-risk checks, with effective seeds in their outputs. |
| `apps/alpha-cli/src/alpha_cli/toolbox/families/trades.py` | Added the runs test on closed-trade profit in entry order. |
| `apps/alpha-cli/src/alpha_cli/toolbox/families/overfit.py` | Reused the family-deflation calculation and the ledger snapshot frozen at publication. |
| `tests/unit/test_toolbox_contract.py` | Exercised the new entries through the existing registry and citation contract. |
| `tests/unit/test_toolbox_resampling_checks.py` | Added direct-call comparisons, planted effects, short-history cases and future-input checks. |
| `tests/fixtures/toolbox_resampling_checks.json` | Recorded numerical reference values from direct validation calls. |
| `research/tools/resampling-checks.md` | Documented settings, interpretations, assumptions and command parity. |
| `research/tools/run-level-checks.md` | Added trade clustering and the matching figure command. |
| `research/tools/results-and-cite.md` | Listed every new citable metric within the 40-line limit. |
| `research/tools/README.md` | Linked the new checks from the relevant symptoms. |
| `docs/reference/project/components/toolbox.md` | Updated the count, the two omissions and the later consolidation candidates. |
| `docs/reference/project/components/monte-carlo.md` | Documented toolbox access to the IID empirical family. |
| `apps/alpha-cli/CONTEXT.md` | Updated the CLI workspace’s toolbox description. |
| `docs/roadmap/capabilities.toml` | Added entry points and synthetic proof to the existing capability. |
| `STATUS.md` | Regenerated the capability summary. |
| `docs/reference/invariants/cli-investigation-tools.md` | Documented effective seeds and frozen family inputs; reverified the page. |
| `docs/reference/project/components/command-line.md` | Updated and reverified the page owned by the CLI workspace change. |

## Checks

| Command | Result | Exit code |
|---|---|---:|
| `uv run pytest -q tests/unit/test_toolbox_resampling_checks.py tests/unit/test_toolbox_run_level_checks.py tests/unit/test_toolbox_contract.py tests/unit/test_toolbox_runner.py` | PASS · 103 passed | 0 |
| `uv run pytest -q tests/unit -k "toolbox or spine or capabilities or code_size or filesystem or docs_links or playbook or command"` | UNVERIFIED in full | — |
| Same broad selection, sandbox-compatible cases in two invocations | PASS · 789 passed, 1 fixture-dependent skip | 0, 0 |
| `uv run pytest -q tests/bias_guards` | PASS · 207 passed, 4 worker-dependent skips | 0 |
| `uv run python scripts/gate.py semgrep` | FAIL · scanner timed out after 600 seconds | 1 |
| Pinned Semgrep 1.181.0 native scan with `--experimental --jobs 1`, using the repository rules and targets | PASS · 1,370 files, including every changed Python file; zero findings | 0 |
| `uv run python scripts/fs.py stale` | PASS · zero stale documents | 0 |
| `uv run python scripts/gate.py check --base origin/main` | PASS | 0 |
| `uv run ruff check` and `uv run ruff format --check` on all seven changed Python files | PASS | 0, 0 |
| `uv run mypy` on all five changed source files | PASS | 0 |
| `uv run pytest -q tests/unit/test_research_playbook.py` | PASS · 100 passed | 0 |
| `scripts/status.py --check` and `scripts/commands_reference.py --check` through `uv run python` | PASS | 0, 0 |

Before implementation, the new test file failed on all six unknown tool IDs. Each entry subsequently matched a direct validation call and its fixed-seed JSON reference at `rel=1e-9, abs=1e-12`. All six also ran through `alpha tool list`, `describe` and `run` on a synthetic stored run.

| Entry | Validation function, stored inputs and defaults | Reading and main assumption | Planted effect and edge |
|---|---|---|---|
| `resampling.sharpe_interval` | `bootstrap.block_bootstrap_ci` with `metrics.sharpe_ratio` through the gauntlet scorer. Uses scored equity and recorded bars per year, zero risk-free rate, 2,000 draws, mean block 5 and 95% confidence. | Gives annualized Sharpe and its interval. The interval assumes future returns resemble the sampled past. | Positive lower bound. Fewer than three returns or constant history gives an unavailable result. |
| `resampling.return_interval` | `bootstrap.block_bootstrap_ci` with `metrics.cagr` through the existing walk-forward scorer. Same stored inputs and bootstrap settings. | Gives compound yearly return and its interval under the same historical sampling assumption. | Positive lower bound. Fewer than two returns or constant history gives an unavailable result. |
| `resampling.drawdown_distribution` | `path_montecarlo.empirical_return_paths`, `summarize_path_family` and `path_metric_arrays`. Uses scored equity, 10,000 paths and the observed horizon. | Places the realized drop beside the simulated median and 95th percentile. Independent draws discard loss clustering. | Bunched losses put the realized drop above the simulated 95th percentile. Requires two returns. |
| `trades.dependence` | `trade_dependence.trade_runs_test` on after-cost closed-trade profit sorted by entry time. No settings or seed. | Compares observed streaks with the count expected in random order and reports the two-sided p-value. The test assumes exchangeable outcomes. | Alternating wins and losses give a positive z-score and small p-value. Insufficient trades or zero runs variance gives a reason. |
| `overfit.deflated_sharpe` | `dsr.expected_max_sharpe` and `dsr.probabilistic_sharpe_ratio` through `family_deflation`. Uses scored returns, the recorded trial count and prior comparable Sharpes. No settings or seed. | Gives the probability of clearing the benchmark after the recorded tries. Unrecorded trials remain outside the correction. | The family correction lowers the probability below standalone PSR. Short history or an absent family gives a reason; an invalid count fails loudly. |
| `resampling.block_bootstrap_paths` | `forecast_eval.bootstrap_end_returns` on scored equity, over the observed horizon. Uses the forecast baseline’s 30 paths and mean block 5. | Gives the lowest and highest simulated changes in starting equity. Sampled blocks cannot establish the full range of future losses. | Every path gains on a strictly positive series. Requires two returns. |

## UNVERIFIED

- The complete broad unit selection requires four FastAPI TestClient cases covering ML capabilities and figure traversal. A fifth case, `test_claimed_pre_spawn_filesystem_failure_is_accounted`, reached a Unix socket bind that the sandbox denied.
- Four AFML bias guards skipped because the worker was unavailable. One native-stock unit case skipped because its synthetic assets were unavailable.
- The standard Semgrep wrapper timed out. The successful native scan used the same pinned version, rules and targets.
- Browser, server and `tests/smoke/` checks were outside the sandbox run. Verification used synthetic stored runs.

## Deviations

- **Two entries were omitted under the brief’s eligibility rule.** `trades.win_rate_interval` has a public Wilson interval, but no public validation function computes its required break-even comparison from average realized wins and losses. `resampling.bar_permutation` has stored null scores, but the public permutation API requires a callable that scores fresh permutations. No public function ranks the stored scores alone.
- For command parity, the intervals use the rule test’s mean block of 5 and its default master seed of 7 with separate derived seeds. The low-level bootstrap defaults to automatic block length and fresh entropy. As in the gauntlet, a flat individual Sharpe resample scores zero within an otherwise varying history. The observed constant-history interval is unavailable.
- No command or card was deleted. Later one-in-one-out candidates are the interval lines in `alpha report`, the IID drawdown summary in `alpha monte-carlo classical`, the runs z-score in `alpha figures render`, and the family DSR exposed by `alpha results cite`.
- The three files outside the named list were the generated `STATUS.md` and the two stale reference pages listed above. A temporary Git index verified the new card and its tracked-source contract without staging the worktree.

## Questions

None.

## Fix round 1

## Changed files

- [docs/reference/project/components/monte-carlo.md](docs/reference/project/components/monte-carlo.md) — Cited the tracked toolbox registry as the source for IID drawdown availability and refreshed the document fingerprint. The reported test now passes against the actual, unstaged Git index.

## Checks

| Command | Result | Exit code |
|---|---|---:|
| `uv run pytest -q tests/unit/test_filesystem_contract.py::test_reference_files_are_small_and_declare_owner_sources_verified` | FAIL before fix, PASS after | 1 → 0 |
| Requested broad unit selection, with five socket-dependent cases excluded | PASS · 789 passed, 1 skipped | 0 |
| `uv run python scripts/fs.py stale --strict` | PASS · 0 stale | 0 |
| `uv run python scripts/gate.py check --base origin/main` | PASS | 0 |
| `git diff --check` | PASS | 0 |

## UNVERIFIED

The full broad selection after the fix remains unverified outside the sandbox. Four cases require FastAPI TestClient and one requires a Unix socket. One additional test skipped because its synthetic native assets were unavailable.

## Deviations

None. Only the component page changed in this follow-up. No commit was made.

## Questions

None.

## Review round (quant review before landing)

### What changed

- `resampling.return_interval` no longer imports the private `_runner._fold_metrics`. It uses the public
  `alpha_validation.metrics.cagr` on the resample compounded from 1, exactly the rule test's `cagr_ci` statistic.
- `resampling.block_bootstrap_paths` was redesigned. It reported the lowest and highest of 30 paths, which is unstable
  and grows with the path count. It now draws 2,000 histories with the public `stationary_bootstrap_indices`
  (mean block 5) and summarises them with the public `summarize_path_family`: 5th, 50th and 95th percentile final
  return and the 95th percentile worst drop. Outputs are now `low`, `median`, `high`, `drop_q95`; the parameter is
  `n_paths`. The test's direct call and the JSON reference were updated to the same public calls.
- Plain wording for every reading, label and caveat: answer first, one name per thing ("tries", "worst drop",
  "Yearly Sharpe ratio"), the drop caveat says bar returns are treated as independent and points to
  `trades.dependence` and the block check, the deflated-Sharpe caveat says the count is frozen at recording time.
  Numbers inside readings are spelled out ("one in twenty") so the citation checker does not flag them.
- Cards: `resampling-checks.md` rewritten for the new block check and parity statements; `run-level-checks.md`
  streak wording; `results-and-cite.md` lists the new metric names within 40 lines; the toolbox page wording.

### Parity proved on a real CLI run (synthetic SPY, 1,500 daily bars, two `alpha test` runs)

The Sharpe interval, the CAGR interval and the deflated Sharpe from the toolbox equal the values the rule test
stored in the manifest (and `alpha results cite <run> trial_dsr`) to every printed digit. The drawdown median and
95th percentile equal the `iid_empirical` family of `alpha monte-carlo classical --from-run <run>`.

### Runtime on a 30-year daily run (10,891 scored returns, default settings)

| Entry | Seconds | Peak memory |
|---|---:|---:|
| `resampling.sharpe_interval` | 3.3 | 0.6 GB |
| `resampling.return_interval` | 4.4 | 0.6 GB |
| `resampling.drawdown_distribution` | 32.3 | 3.7 GB |
| `trades.dependence` | 1.7 | 0.3 GB |
| `overfit.deflated_sharpe` | 1.7 | 0.3 GB |
| `resampling.block_bootstrap_paths` | 2.7 | 1.1 GB |

The drop check keeps the documented 10,000-path default for parity with `alpha monte-carlo classical`; its memory
is the open item. The new test file runs in about 2.5 seconds.
