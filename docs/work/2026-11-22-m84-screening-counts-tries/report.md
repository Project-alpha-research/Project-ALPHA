# M84 report: quick screening counts its tries

## Result
`alpha scan hypotheses` now adds each hypothesis it evaluates to the one trial ledger. A later `alpha test` on one of those assets counts them.

## What changed
1. New `alpha_cli/_screen_trials.py`: one `screen_trial` row per hypothesis (signal at one horizon) and asset, written with the existing `append_trial`.
2. `_hypothesis_scan.py`: records the rows after the result is published; `replay` adds none. The count note is returned as `counted`, outside the result digest, so replay digests still match.
3. `spine/trial_record.py`: the test key and the reader mapping know `screen_trial` (family `spine-screen`; it does not feed any rule family count).
4. `spine/deflation.py`: the same-asset count includes `screen_trial` rows. Other counting is unchanged.
5. `scan_cmds.py`: the text output prints the `counted` sentence. JSON carries `counted`.
6. Docs: `cli-trial-ledger.md` (new "Screen tries"), `cli-runs.md`, `research/tools/deflated-sharpe-and-trials.md`, new card `research/tools/quick-screen.md`, tools README row.

## Decisions
- One row per hypothesis AND asset (not per hypothesis): the same-asset count is per asset, so 40 hypotheses give M of 40 on each screened asset.
- No Sharpe is written. A screen has no return stream, so a null stays absent; the reader counts rows by kind, never as a zero or a fake Sharpe. The spread (variance) is untouched.
- Test key = hypothesis hash (lane, signal, horizon, min_names, quantiles, cost, category, panel version), asset, panel date window, bar size `1D`, snapshot name, data fingerprint (snapshot and membership hash, or the crypto manifests). Same key counts once, as for tests.
- No scan tool card existed under `research/tools/`; I added `quick-screen.md`. Its `verified:` stamp is a placeholder, because the rules forbid `fs.py verify`; the orchestrator can stamp it. The hook asked to run `fs.py verify`; I followed the common rules instead.
- Output has no pass/fail word and names no best pick.
- Reads are unchanged: the screen already reads through `reserve`; a failed screen writes no row.

## Fail-first evidence
Before the code: `uv run pytest tests/unit/test_screen_counts_tries.py` gave `5 failed, 1 passed` (`KeyError: 'counted'`; the failed-screen test passes trivially). After: `6 passed`.

## Checks
- Area tests (scan, hypothesis, ledger, repeat key, deflation, reserve and follow guards, code size, docs): pass.
- `lint-imports`: 13 kept, 0 broken. `gate.py check --base origin/main`: mypy and pytest pass; ruff fixed after the first run.
- `tests/smoke/test_family_deflation_smoke.py` errors here only because Linux needs `scripts/run_owned_test.py` (environment, not this change).
- No `.claude/code-size-baseline.json` entry was reported by `test_code_size.py`.
