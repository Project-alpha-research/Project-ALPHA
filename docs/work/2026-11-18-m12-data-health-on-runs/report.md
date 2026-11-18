# Build report: m12-data-health-on-runs

## Changed files

Rule tests and setup `find`, `study`, and `trade` now read the health report from the resolved daily store at `store/health/<symbol>.json`. A failed check stops the run before engine work. `--accept-bad-data "reason"` applies to one invocation. All changes are uncommitted.

[stripped: instruction-shaped text]

† marks files covered by the brief’s scope extension or its instruction to use the actual frontend path.

| Path | Change |
|---|---|
[stripped: instruction-shaped text]
| `apps/alpha-cli/src/alpha_cli/_data_health.py` | Shared sidecar reading and writing. Bound stock peer prices and provenance to computed reports. |
| `apps/alpha-cli/src/alpha_cli/spine/stores.py` | Exposed the daily store for an already-resolved asset. |
| `apps/alpha-cli/src/alpha_cli/spine/run.py` | Checked inputs before rule execution and recorded health in the identity, manifest, result, and ledger. |
| `apps/alpha-cli/src/alpha_cli/test_cmds.py` † | Added both CLI options and printed each asset’s health sentence. |
| `apps/alpha-cli/src/alpha_cli/setup_cmds.py` | Added both options to all three setup commands and recorded health on finds. |
| `apps/alpha-cli/src/alpha_cli/spine/setup_find.py` † | Checked selected sources before detection and preserved legacy find identities and control seeds. |
| `apps/alpha-cli/src/alpha_cli/spine/setup_study.py` † | Checked study inputs afresh and recorded the verdict on the study and its facts. |
| `apps/alpha-cli/src/alpha_cli/spine/setup_trade.py` † | Checked trade inputs afresh and recorded the verdict on the trade run and its facts. |
| `apps/alpha-cli/src/alpha_cli/results_cmds.py` | Put the health sentence first in `results show`, added find-summary lookup, and carried run labels into tool citations. |
| `apps/alpha-cli/src/alpha_cli/spine/check.py` † | Required disclosure of failed, overridden, and unchecked data. Accepted the printed verdict wording. |
| `apps/alpha-web/src/alpha_web/_setup_runs.py` | Added plain explanations for all five labels. |
| `apps/alpha-web/frontend/src/panels/ruleTestModel.ts` † | Added label explanations and formatting for saved and legacy verdicts. |
| `apps/alpha-web/frontend/src/panels/rundetail/RuleTestReport.tsx` † | Displayed non-pass health findings beside the headline. |
| `apps/alpha-web/frontend/src/panels/SetupLabPanel.tsx` † | Displayed each find, study, and trade’s own health line. |
| `apps/alpha-web/frontend/src/panels/ruleTestModel.test.ts` † | Tested the five labels and the rendered finding. |
| `apps/alpha-web/frontend/src/panels/SetupLabPanel.test.tsx` † | Tested separate setup verdicts, pass suppression, and legacy text. |
[stripped: instruction-shaped text]
| `tests/unit/test_spine_honesty_3.py` † | Proved that removing the health field and label restores the existing rule identity pin. |
| `tests/unit/test_spine_report_edges.py` † | Added health to the prepared publication fixture. |
| `tests/unit/test_setup_study.py` † | Added the required disclosure to the valid citation draft. |
| `tests/smoke/test_rule_check_smoke.py` † | Added the disclosure to the installed-command citation fixture. |
| `tests/smoke/test_rule_test_smoke.py` † | Added assertions for the stored verdict and label across two stores. |
| `tests/smoke/test_setup_find_smoke.py` † | Added assertions for the find verdict and label. |
[stripped: instruction-shaped text]
| `research/tools/rule-test.md` | Documented per-asset health and `--check-data`. |
[stripped: instruction-shaped text]
| `research/tools/setup-study.md` † | Documented the fresh check before measuring returns. |
| `research/tools/setup-trade.md` † | Documented the fresh check before simulating exits. |
| `research/tools/results-and-cite.md` † | Documented the verdict in `results show`. |
| `research/PLAYBOOK.md` | Added health-label disclosure wording. |
| `apps/alpha-cli/CONTEXT.md` | Linked the run-health tool card. |
| `docs/reference/project/components/data-layer.md` | Recorded rule-test and setup support and the pending RD-Agent work. The page is 200 lines. |
| `docs/reference/project/components/setup-lab.md` † | Documented headline findings and legacy text. |
| `docs/reference/invariants/cli-results-check.md` † | Documented the required citation phrases and accepted printed wording. |
| `docs/reference/invariants/cli-runs.md` † | Documented health labels, immutable setup identities, and control seeds. |
| `docs/reference/invariants/web-frontend.md` † | Documented placement of non-pass findings. |
| `docs/reference/project/owner-decisions-5.md` † | Added the dated implementation status. |
| `docs/reference/project/ideas-and-considered.md` † | Updated the queued entry to distinguish delivered work from RD-Agent panels. |
| `docs/roadmap/capabilities.toml` | Marked rule-test and setup health working and linked the proof cases. |
| `STATUS.md` † | Regenerated the capability status. |
| `docs/reference/commands.md` † | Regenerated the CLI reference. |
| `docs/verified-reasons.txt` † | Recorded living-document verification reasons. |
| `apps/alpha-web/CONTEXT.md` † | Reverified frontend and backend routing. |
| `docs/reference/invariants/web-api.md` † | Reverified the existing API contract. |
| `docs/reference/project/components/ai-assistants.md` † | Reverified assistant and citation behavior. |
| `docs/reference/project/components/command-line.md` † | Reverified the CLI component description. |
| `docs/reference/project/components/strategies-and-signals.md` † | Reverified strategy behavior. |
| `docs/reference/project/components/validation-and-evidence.md` † | Reverified the validation and evidence description. |
| `research/CONTEXT.md` † | Reverified research workflow routing. |
| `research/tools/README.md` † | Reverified tool-card routing. |
| `research/tools/benchmark-and-drawdowns.md` † | Reverified benchmark behavior. |
| `research/tools/charts.md` † | Reverified chart behavior. |
| `research/tools/deflated-sharpe-and-trials.md` † | Reverified trial accounting. |
| `research/tools/diagnose-and-audit.md` † | Reverified the diagnostic and audit workflow. |
| `research/tools/sensitivity.md` † | Reverified sensitivity behavior. |

## Checks

| Command | Status | Exit code |
|---|---|---:|
| `uv run pytest -q tests/unit/test_run_data_health.py` | PASS · 16 passed | 0 |
| Requested broad unit selection, with the five socket-dependent cases excluded | PASS · 1,176 passed, 2 platform skips | 0 |
| Requested broad unit selection without sandbox exclusions | UNVERIFIED | — |
| `uv run pytest -q tests/bias_guards` | PASS · 207 passed, 4 dependency skips | 0 |
| `uv run python scripts/fs.py stale` | PASS · 116 checked, 0 stale | 0 |
| `uv run python scripts/gate.py check --base origin/main` with sandbox exclusions | PASS | 0 |
| Same gate without exclusions | UNVERIFIED | — |
| `uv run ruff check` on all 19 changed Python files | PASS | 0 |
| `uv run ruff format --check` on the same files | PASS | 0 |
| `uv run mypy` on all 12 changed Python source files | PASS | 0 |
| `node_modules/.bin/oxlint --deny-warnings` | PASS | 0 |
| `node_modules/.bin/tsc --noEmit` for the app, Node, and e2e configurations | PASS | 0 |
| `node_modules/.bin/vitest run --coverage` | PASS · 703 passed | 0 |
| `node_modules/.bin/vite build --outDir <temporary directory>` | PASS | 0 |
| `scripts/status.py --check`, `scripts/commands_reference.py --check`, and `git diff --check` | PASS | 0 |

The following sentences came from synthetic stores. An out-of-date report receives `data-health-unchecked` while retaining `out-of-date` in the stored verdict.

| Outcome | Printed sentence |
|---|---|
| Pass | `Data health: pass. ABC@home: 0 stock peers used.` |
| Warn | `Data health: warn. ABC@home: The data stops 18 sessions before the check time. ABC@home: 0 stock peers used.` |
| Unchecked | `Data health: unchecked. ABC@home: No report. Check it with uv run alpha data health ABC@home.` |
| Out of date | `Data health: out-of-date. ABC@home: The stored report is out of date. Check it with uv run alpha data health ABC@home.` |
[stripped: instruction-shaped text]

[stripped: instruction-shaped text]

```text
Data health: fail. SPLIT@home: unflagged_split. 1 overnight jump looks like a split that is not recorded. Other series were quiet that day. First dates: 2024-01-04. SPLIT@home: 1 stock peer used. Fix the data, or re-run with --accept-bad-data "reason".
After a repair, check again with uv run alpha data health SPLIT@home.
```

No numeric or identity pin was replaced. Removing the new health field and label from the rule identity input reproduced `3d7c42078dd76b34`. The legacy setup find ID `32d1f3b953038de2` and the existing trade-row and statistic byte pins also passed.

## UNVERIFIED

- Four selected FastAPI `TestClient` cases require the orchestrator. A fifth case, `test_claimed_pre_spawn_filesystem_failure_is_accounted`, attempted a Unix socket bind and received `PermissionError`. The final sandbox run excluded all five.
- The three changed installed-command smoke tests, browser e2e checks, and unrestricted gate remain for the orchestrator. The frontend production build used a temporary output directory.
- Four AFML bias guards skipped because the worker is absent. Two broad unit cases skipped because the host lacks the expected fontconfig rule and explicit synthetic native assets.
- No real market data was used.

## Deviations

The implementation used the brief’s actual-path and scope extensions marked † above. For legacy series without a declared asset class, peer selection uses recognized equity-provider provenance and the series calendar. `--check-data` selects up to 20 overlapping peers in stable symbol order.

Nothing was retired. Duplicate-date, gap, and invalid-OHLC checks are candidates for later consolidation. RD-Agent panels remain the next integration.

## Questions

None.

## Review round (2026-11-19)

Every changed file falls in a class the brief allows. No file was reverted.
The printed wording in the tables above is superseded by the wording below.

Changes in this round:
1. A blank `--accept-bad-data` reason now stops the command with `BAD_OPTION`. Before, a rule test recorded it as a
   per-asset error and wrote a trial row; `setup study` and `trade` showed a traceback.
2. The stop message names the check in words ("check unflagged split") and the period the report covers.
3. Each verdict sentence says "report of <date> covers all stored bars". The report is made from the same bytes the
   run reads, so it holds no bars after the run's data end.
4. The next step after a fail is "run the same command again with --check-data". `alpha data health` alone uses no
   peers, so a re-check with it could turn a split `fail` into a `warn`.
5. The unchecked line also offers `--check-data`. "re-run" became "run again" (one name for one thing).
6. The `data-health-pass` explanation on screen now keeps the limit: "The data checks found no fault. The prices
   can still be wrong." The data-health card again carries the full "What it cannot tell you" sentence.
7. New tests: no run folder and no trial row after a stop; blank reasons; a byte proof that a stored `pass` report
   changes nothing in the run folder except the health record, its label and the ids that hash them.
8. Docs: the run section of the data-health card was rewritten; the playbook keeps "Always consider"; `cli-runs.md`
   again says sheet limits do not affect the find id and the manifest is atomic.

Synthetic check (throwaway home, rule `ma_cross` 10/50, `--quick`):

```text
Data health: pass. GOOD@home: report of 2026-11-18 covers all stored bars.
Data health: warn. WARN@home: The data stops 15 sessions before the check time. WARN@home: report of 2026-11-18 covers all stored bars.
Data health: unchecked. NEW@home: No report. Check it with uv run alpha data health NEW@home, or run again with --check-data.
```

The stop (`--check-data` made the report, with 6 stock peers; no run folder and no trial row were written):

```text
Data health: fail. BAD@home, check unflagged split: 1 overnight jump looks like a split that is not recorded. Other series were quiet that day. First dates: 2026-01-07. BAD@home: report of 2026-11-18 covers all stored bars. BAD@home: 6 stock peers used. Fix the data, or run again with --accept-bad-data "reason".
After a repair, run the same command again with --check-data.
```

With `--accept-bad-data "testing the override"` the run carries `data-health-fail` and `data-health-overridden` and ends with
"Data health overridden: testing the override." The next run without the option stops again.

Checks after the main merge: the run-health tests (19 passed); the broad unit selection (1,458 passed, 3 skipped); bias guards
(207 passed, 4 skipped); smoke `rule or setup or health` (9 passed); frontend lint, build with type-check, 703 unit tests;
browser lanes at the reference viewport (passed, no baseline changed; native lane skipped); semgrep; `fs.py stale` (0 stale);
`alpha partner selftest` (25 of 25). Screenshots of the warn and overridden Summaries are kept outside git.
CI found one more draft that cites a new run without saying "data health unchecked" (`tests/smoke/test_inverted_control_smoke.py`).
The draft now discloses it, as the new checker rule requires.
