# Brief: quick screening (`alpha scan hypotheses`) counts its tries in the one trial ledger

Branch: `feat/m84-screening-counts-tries`. Rules: `docs/work/_common-rules-2026-11-21.md`.

Why: the owner decided on 2026-11-21 to KEEP quick screening, on one condition: its tries count. Today `alpha scan hypotheses` (and its
replay) tests many ideas on an asset and writes nothing to the trial ledger, so a later `alpha test` of the best one is deflated as if it
were the first try. Read `apps/alpha-cli/src/alpha_cli/scan_cmds.py`, the ledger writer used by `spine/run.py` and `toolbox/runner.py`,
`spine/trial_record.py`, `spine/trial_reader.py`, `deflation.py`, and `docs/reference/invariants/cli-trial-ledger.md`.

Build:
1. Each hypothesis that a screening run evaluates appends one trial through the existing ledger writer (no new ledger, no new table):
   asset, data fingerprint, period, the hypothesis identity as the rule, and a family so that the same-asset count used by `alpha test`
   and by diagnose now includes these tries. A re-run of the same screening on the same data counts once (same test key), as for tests.
2. A replay of a stored screening run adds no new trials.
3. The reader counts them: an `alpha test` reading on that asset after a screening of 40 hypotheses states M of at least 40, and the
   deflated Sharpe uses it. Prove this end to end on a synthetic store.
4. Reads are cut at the held-back boundary (`alpha_cli.spine.reserve`); the screening output says, in plain words, how many tries it
   added to the count and that a screen is a first look, not a test. No pass/fail word, no "best" pick stated as a finding.
5. Keep the other `scan` sub-commands as they are: their retirement is separate work.
6. Docs: the trial-ledger page, the scan tool card under `research/tools/`, capabilities if one changes.

Tests first (fail-first evidence in the report). Done: pull request ready with `ci-ok` green, and `report.md` in this folder.
