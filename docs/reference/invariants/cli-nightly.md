---
owner: command line runs and validation
sources:
  - apps/alpha-cli/src/alpha_cli/nightly_*.py
  - apps/alpha-cli/src/alpha_cli/spine/recheck*.py
  - tests/unit/test_nightly*.py
  - tests/unit/test_recheck*.py
verified: 7f5fb9c98549f7b4
---

# Command line nightly run invariants

## Steps and records
- `alpha nightly run` runs each step as the installed `alpha` command in a child process. It re-implements no step.
  A step failure never stops an independent step.
- A step is pass, minor defect, blocking defect or not run. A reading such as `not clear of chance` is never a defect.
- A record is `<home>/nightly/<UTC date>-<n>/record.json` plus `summary.txt`. It is append-only (exclusive create).
  It holds commands, ids, durations, verdict words, defect text and each follow's chain head only.
- Nightly tests are counted trials like any other. The run never hides a label and never passes `--accept-bad-data`.
- Data health reads the saved report first (`--stored`): a new report changes the test identity.
- The command installs no schedule. It prints one crontab line. N3 runs only when `rdagent_config` is set.
  It calls `alpha rdagent run --config <file>` unchanged and adds no cap.

## Same input, same output
- The nightly rule test is the same test every night. Research reads stop at the reserved boundary, so new bars never make it a new test.
  With unchanged code a normal run returns the stored run in about two seconds; that proves nothing about the engine.
- So N1.test, N2.study and N2.trade run `--recheck` first: computed again and compared with the stored result
  ([rule](cli-rule-readings.md#recheck), [setups](cli-setups.md#setup-study)). Nothing stored (night one): the normal command runs once.
  The step keeps a note. A recheck is not a trial: no ledger row, no run folder.
- A match is `computed`. The record keeps `seconds` and `code_changed` for the rule test.
- A difference is a blocking defect: "the same test gave a different result", with the field and both numbers.
  These numbers are the system's own check, not an idea's result. If `code_changed` is true the text adds that the code changed
  since the stored result and that a code change altered a stored result.
- Each step's `evidence` is `computed`, `reused` or `unknown`. It is read from the `executed` field of the command's JSON,
  never from the `repeat` label: `repeat` means the same test by key, even when the engine ran again. Old records read `unknown`.

## Ready
- `nightly_status.readiness` decides. Two latest non-partial runs, on two UTC dates, each with no blocking defect, with all
  three paths run (`full`), a `computed` rule-test step and a `computed` setup step.
  A computed rule test is a matched recheck, or a first normal run with `executed: true`.
- N4 (follow update) counts only if a follow exists; N0 is an opt-in refresh: [cli-follow.md](cli-follow.md#nightly-n4-n0).
- Partial `--only` runs are ignored. Old records read `unknown` and never qualify.
