# Build report: m19-rdagent-post-judge-checks

ALPHA now runs the Sharpe interval and block-bootstrap paths after the verdict for every factor with a shown lead-clock replay and recorded evidence, whether it passed or failed. Attempts go to `<run>/checks/ledger/trials.jsonl`. Outputs go to `<run>/checks/diagnostics/<target>/`. The agent’s feedback and journey step 7 carry the readings or errors.

**All 98 focused tests passed.** `test_checks_leave_verdict_and_factor_ledger_identical` verified identical decisions, factor rows, legacy results and factor ledger bytes with checks enabled or disabled. The four toolbox rows contributed zero deflation trials. `test_parity_attempts_and_cache` verified both tools against direct validation calls and reproduced identical result bytes without adding attempts.

From the synthetic planted-factor run:

- **Feedback excerpt:** “ALPHA checks after the verdict for factor (fixed set rdagent-post-judge; they do not change the verdict), on the daily return above the equal-weight basket after costs: Yearly Sharpe ratio was 4.05. Resampling this history puts it between 3.18 and 5.08.”
- **Journey step 7 excerpt:** “ALPHA check after the verdict (does not change it): Yearly Sharpe ratio was 4.05. Resampling this history puts it between 3.18 and 5.08.”

## Changed files

All 21 files are uncommitted and unstaged. The change adds 560 lines and removes 33.

| Path | + / − | Change |
|---|---:|---|
| `apps/alpha-cli/src/alpha_cli/_rdagent_checks.py` | 172 / 0 | Validates replay evidence, runs the fixed checks and builds feedback. |
| `apps/alpha-cli/src/alpha_cli/toolbox/runner.py` | 2 / 1 | Accepts a supplied target through the keyword-only `source` argument. |
| `apps/alpha-cli/src/alpha_cli/toolbox/sets.py` | 4 / 1 | Declares both checks in execution order. |
| `apps/alpha-cli/src/alpha_cli/rdagent_factor_eval.py` | 3 / 0 | Attaches checks and feedback under the existing evaluation lock. |
| `apps/alpha-cli/src/alpha_cli/rdagent_journey.py` | 9 / 1 | Matches each idea to its recorded checks. |
| `apps/alpha-cli/src/alpha_cli/rdagent_journey_words.py` | 19 / 2 | Adds readings, errors and output sources to step 7. |
| `tests/unit/test_rdagent_post_judge_checks.py` | 277 / 0 | Tests parity, eligibility, counts, caching, failures, reserve rejection and journey bytes. |
| `tests/fixtures/rdagent_post_judge_checks.json` | 14 / 0 | Stores numerical references and the pre-change journey bytes. |
| `tests/unit/test_rdagent_factor_eval.py` | 15 / 0 | Adds assertions for the new fields before the existing whole-record comparison. |
| `docs/reference/project/components/toolbox.md` | 17 / 10 | Documents the series, honesty rules, storage and outstanding work. |
| `docs/reference/invariants/cli-investigation-tools.md` | 6 / 2 | Records the evidence, reserve and ledger boundaries. |
| `docs/reference/project/components/rd-agent.md` | 4 / 3 | Updates fixed-check availability and the status of agent choice. |
| `research/tools/rdagent-journey.md` | 2 / 2 | Updates step 7 within the 40-line limit. |
| `research/tools/resampling-checks.md` | 2 / 1 | Identifies the return series used for factors. |
| `docs/roadmap/capabilities.toml` | 4 / 3 | Updates the working capability and links its synthetic proof. |
| `STATUS.md` | 1 / 1 | Regenerates the capability listing. |
| `docs/reference/project/ideas-and-considered.md` | 2 / 1 | Adds the dated implementation status. |
| `docs/reference/project/owner-decisions-5.md` | 1 / 0 | Adds a dated status note to the existing recommendation. |
| `apps/alpha-cli/CONTEXT.md` | 2 / 2 | Updates and verifies the stale workspace guide. |
| `docs/reference/project/components/command-line.md` | 2 / 1 | Updates the stale CLI component page with the feedback path. |
| `docs/reference/project/decisions-by-topic.md` | 2 / 2 | Updates the stale topic index to distinguish fixed checks from agent choice. |

## Checks

| Command | Result | Exit code |
|---|---|---:|
| `uv run pytest -q tests/unit/test_rdagent_post_judge_checks.py tests/unit/test_rdagent_factor_eval.py tests/unit/test_rdagent_journey.py` | PASS — 98 passed | 0 |
| Requested broad `tests/unit -k` selection, unfiltered | UNVERIFIED — includes socket and browser tests | — |
| Broad selection with sandbox exclusions, `-n 3 --tb=line` | FAIL — 1,317 passed, 23 skipped, 30 failed, 45 errors | 1 |
| `uv run lint-imports` | PASS — 13 contracts kept | 0 |
| `uv run pytest -q tests/bias_guards` | PASS — 207 passed, 4 skipped | 0 |
| `uv run python scripts/fs.py stale` | PASS — 0 stale | 0 |
| `uv run python scripts/gate.py check --base origin/main`, with the Unix-socket retry excluded | FAIL — static checks passed; pytest had 1 failure, 1,079 passes and 5 skips | 1 |
| `uv run ruff check` on all eight changed Python files | PASS | 0 |
| `uv run ruff format --check` on the same files | PASS | 0 |
| `uv run mypy` on all six changed source files | PASS | 0 |
| Filesystem reference-source test with a temporary Git index containing the new files | PASS | 0 |
| `scripts/status.py --check`, `scripts/roadmap_index.py --check`, `git diff --check` | PASS | 0 |

The gate’s remaining failure was a gateway retry test. Its storage guard rejected `/tmp` because this sandbox places a `.git` marker there. The broad failures were in gateway setup and launch, plus one documentation test that requires referenced source files to be tracked. That documentation test passed with the temporary index. [Gate output](/tmp/m19-last-gate.log) · [Broad test output](/tmp/m19-last-broad.log)

## UNVERIFIED

- No real RD-Agent loop, model call, browser, smoke test or localhost server was run through completion. The full unfiltered broad selection and gate need an outside-sandbox run.
- An in-process HTTP test stalled in the sandbox and was interrupted. The other 46 web projection tests passed with both asynchronous HTTP cases excluded.
- Four AFML bias guards skipped because their worker was unavailable.

## Deviations

- The reserve guard checks **every selected exit** against the reserved date. The determinism test uses the evaluator’s existing fixed-clock, fresh-factor-ledger convention and a separate output path.
- The required edit to `evaluate()` changes `inputs.evaluator_fingerprint`, which hashes that file’s bytes. The protected judge and worker files retain their original bytes.
- The shared tools retain their existing JSON `basis` wording about walk-forward equity. The factor labels, feedback and documentation identify the actual input as daily after-cost return above the equal-weight basket.

## Questions

None.

## Fix round 1

**The full gate passed with the worktree’s real Git index.** The three reference pages now use `_rdagent_*.py`, which matches tracked evaluator modules and includes the new adapter. `fs.py owners` confirmed that changes to `_rdagent_checks.py` still mark all three pages stale.

## Changed files

| Path | Change in this fix |
|---|---|
| `docs/reference/invariants/cli-investigation-tools.md` | Updated the source glob and verification stamp (+2/−2). |
| `docs/reference/project/components/rd-agent.md` | Updated the source glob and verification stamp (+2/−2). |
| `docs/reference/project/components/toolbox.md` | Updated the source glob and verification stamp (+2/−2). |

## Checks

| Command | Result | Exit code |
|---|---|---:|
| `uv run python scripts/gate.py check --base origin/main` | PASS | 0 |
| `uv run pytest -q tests/unit/test_filesystem_contract.py` | PASS — 50 tests, including the reported failure | 0 |
| `uv run python scripts/fs.py stale --strict` | PASS — 120 documents checked, zero stale | 0 |
| `uv run python scripts/fs.py owners apps/alpha-cli/src/alpha_cli/_rdagent_checks.py` | PASS — all three pages listed | 0 |
| `git diff --check` | PASS | 0 |

## UNVERIFIED

The post-fix gate ran inside the sandbox. An outside-sandbox rerun is pending.

## Deviations

None. All changes remain uncommitted.

## Questions

None.
