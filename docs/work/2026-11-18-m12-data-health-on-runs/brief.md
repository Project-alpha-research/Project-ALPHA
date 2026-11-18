# Brief: every run carries the health verdict of its data

**Build class:** hard

## Task

`alpha data health` (PR #278) reports four groups of checks on a stored series and stores the
report with the source fingerprint. No run reads it: a backtest on bad data looks the same as
one on clean data, and every run carries the same fixed label `dev-machine-data`. Step 2:
when a rule test or a setup run starts, look up the health report for each series it reads,
attach the verdict to the run, show it, and stop on a `fail` unless the user overrides it.

## Read first

| Read | Section | When |
|---|---|---|
| `apps/alpha-cli/CONTEXT.md`, `packages/alpha-data/CONTEXT.md` | whole | always |
| `research/tools/data-health.md`, `docs/reference/project/components/data-layer.md` | what the report checks, stores and cannot tell you | always |
| `packages/alpha-data/src/alpha_data/health.py`, `apps/alpha-cli/src/alpha_cli/_data_health.py`, `data_cmds.py` (`health`) | the report, where it is stored, the fingerprint, "out of date" | always |
| `apps/alpha-cli/src/alpha_cli/spine/run.py` (`_prepare`, labels), `spine/stores.py` (`resolve_asset`), `_runner.py` (`source_fingerprint`) | where a run resolves its data and sets labels | always |
| `apps/alpha-cli/src/alpha_cli/setup_cmds.py` (label handling near line 155) | setup runs | always |
| `apps/alpha-web/src/alpha_web/_setup_runs.py` and the rule-test report model (`ruleTestModel.ts`) | how labels are explained on screen | screen |
| `research/PLAYBOOK.md` | labels, flags and trial counts wording | labels |

## Decision already made

1. **Lookup, never a silent check.** At run start, for each series the run reads, find the
   stored health report whose fingerprint matches the series' current bytes. Outcomes per
   series: `pass`, `warn`, `fail`, `out-of-date` (a report exists for other bytes) or
   `unchecked` (no report). The run does not compute the report itself in this step; the
   message names the exact command to run (`uv run alpha data health <symbol>[@store]`).
   Exception: with the new option `--check-data`, the run computes and stores the missing or
   out-of-date reports first, then proceeds with the result.
2. **Run verdict** = worst series outcome, order `fail` > `out-of-date` > `unchecked` > `warn` >
   `pass`. Stored on the run as `data_health` (verdict, per-series outcome, each failing or
   warning check's id and one-sentence finding, report time, fingerprint) and as one label:
   `data-health-pass`, `data-health-warn`, `data-health-fail`, `data-health-unchecked`
   (covers out-of-date; the stored field keeps the distinction). The label joins the existing
   labels; `dev-machine-data` stays as it is.
3. **A fail stops the run** before any backtest work, with a plain message: which series, which
   check, the finding, the first dates, and the two ways forward: fix the data, or re-run with
   `--accept-bad-data "reason"`. With the override the run proceeds, stores the reason, and
   carries the extra label `data-health-overridden`. `unchecked` and `warn` never stop a run.
   No override is remembered between runs.
4. **Peers for the split check.** When computing reports under `--check-data` for a stock, pass
   the other stock series in the same store as peers (same calendar, overlapping dates), so an
   unflagged split can `fail` instead of only `warn`. Cap at 20 peers; say how many were used.
5. **Where it shows.** `alpha results show` and the run's printed summary state the verdict in
   one plain sentence with its findings ("Data health: warn. The data stops 12 sessions before
   the check time."). `alpha results check` (the citation checker) requires a report that
   quotes a run with `data-health-fail`/`overridden`/`unchecked` to say so (add to the existing
   label rules; do not weaken any). The Workstation's label explanations gain the five labels
   with plain text; the rule-test Summary and Setup Lab show the data-health line near the
   headline when it is not `pass`. No new screen.
6. **Old runs** have no `data_health`: they read "data health: not recorded" and get no label.
   Nothing is back-filled.
7. **Scope:** rule tests (`alpha test` / spine runs) and setup runs (`find`, `study`, `trade`).
   Not RD-Agent panels in this change (they already block on unqualified crypto manifests);
   list that as the next step. No change to ingest, quarantine, or the health checks' rules.
8. **Tests** (fail first; synthetic stores only): each outcome for one series; worst-of for
   several; fail stops before backtest work (assert no engine call) and the message text;
   override proceeds, stores the reason and both labels; out-of-date after one byte changes;
   `--check-data` computes, stores and uses reports and passes peers; old run reads "not
   recorded"; the citation checker rule; the screen's label text (frontend unit test). Existing
   run fixtures that pin the label list or a run digest: change a pin only where the test is
   about labels or layout, and show that dropping the new field and label restores the old
   bytes.
9. Update the data-health card, the rule-test and setup cards, the playbook's label section,
   the data-layer page (≤ 200 lines), the capability record (`data-health-on-runs` → working
   for rule tests and setups, RD-Agent panels not built). When work lands, any page that listed
   it as queued or not built is updated in the same change (decision log status line,
   ideas-and-considered). Nothing is replaced: say so; list which run-time checks could later
   be retired in favour of the report.

## Files

Edited:
- `apps/alpha-cli/src/alpha_cli/spine/run.py`
- `apps/alpha-cli/src/alpha_cli/spine/stores.py`
- `apps/alpha-cli/src/alpha_cli/setup_cmds.py`
- `apps/alpha-cli/src/alpha_cli/_data_health.py`
- `apps/alpha-cli/src/alpha_cli/results_cmds.py`
- `apps/alpha-web/src/alpha_web/_setup_runs.py`
- `apps/alpha-web/frontend/src/rundetail/ruleTestModel.ts`
- `apps/alpha-web/frontend/src/rundetail/RuleTestReport.tsx`
- `research/tools/data-health.md`
- `research/tools/rule-test.md`
- `research/PLAYBOOK.md`
- `docs/reference/project/components/data-layer.md`
- `docs/roadmap/capabilities.toml`
- `apps/alpha-cli/CONTEXT.md`

New:
- `apps/alpha-cli/src/alpha_cli/spine/data_health.py`
- `tests/unit/test_run_data_health.py`

This decision overrides the standing rule for: other modules under
`apps/alpha-cli/src/alpha_cli/` that start a rule test or setup run, print a run summary, or
check citations; `apps/alpha-web/` files that explain labels (backend reader, frontend model,
panel, tests, styles) and generated API files if a response model changes (follow the
route-change steps in `apps/alpha-web/CONTEXT.md`); test files under `tests/unit/` and
`tests/smoke/` for rule tests, setups, labels and results; the setup tool cards; generated
pages, the capability trace and the triage sheet (regenerate generated pages with their
scripts); `docs/reference/project/owner-decisions-5.md` and `ideas-and-considered.md` for a
dated status line only; any living document `scripts/fs.py stale` reports because of your edits
(verify with a real text change or `--reason`). If a named file does not exist, use the real
one. List each in the report; do not stop to ask; where a rule is open choose the more cautious
reading and state it.

## Do not touch

`packages/**` (read only; `alpha_data.health` is called, not changed), `workers/**`,
`tests/bias_guards`, `tests/oracles`, golden files and browser baselines, `.semgrep/`,
`.github/`, `.claude/`, `.agents/`, `scripts/`, `uv.lock`. Health check rules and thresholds,
ingest and quarantine behaviour, cost rules, statistic definitions. No `nosemgrep`, `noqa`,
`type: ignore`, `eslint-disable`, `vars(`, `__doc__`, `inspect`, `.__dict__`. Functions ≤ 150
lines, files ≤ 1,500 lines (`spine/run.py` may be near its ceiling: put logic in the new
module); tests fully type-annotated; no test file named `*fixups*` or ending `_<N>.py`. No
wall clock in code under test without an injected time.

## Checks

- `uv run pytest -q tests/unit/test_run_data_health.py`
- `uv run pytest -q tests/unit -k "spine or setup or data_health or results or labels or playbook or capabilities or code_size or filesystem or docs_links or command"`
- `uv run pytest -q tests/bias_guards`
- `uv run python scripts/fs.py stale`
- `uv run python scripts/gate.py check --base origin/main`

Also the frontend lint, type-check and unit tests named in `apps/alpha-web/CONTEXT.md`.

## Report

The lookup rule and where the report is found. Each outcome's printed sentence. The exact
message when a run is stopped, and the override path. What is stored on the run. Pins changed
and the byte proof. What old runs show. Run-time checks that could later be retired. Every file
outside the list. Open readings chosen. What is unverified (no real data was used).
