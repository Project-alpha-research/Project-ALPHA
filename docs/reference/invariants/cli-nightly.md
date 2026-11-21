---
owner: command line runs and validation
sources:
  - apps/alpha-cli/src/alpha_cli/nightly_*.py
  - apps/alpha-cli/src/alpha_cli/home_*.py
  - apps/alpha-cli/src/alpha_cli/spine/recheck*.py
  - tests/unit/test_nightly*.py
  - tests/unit/test_home_backup.py
  - tests/unit/test_recheck*.py
verified: be9e873810f717b5
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
  These numbers are the system's own check, not an idea's result. The text then says the code changed since the stored run
  (and that this does not excuse the difference), the code is the same, or (setups, `code_changed: null`) it is not recorded.
  A mismatch step has `evidence: unknown`, never `reused`: the engine ran, but nothing was proven.
- A recheck that could not run (exit code other than 0 or 4, timeout, no JSON, an asset error) is blocking and never `computed`.
- `N1.diagnose` needs `audit` and `flags`. `labels` is optional: `alpha diagnose` prints it only for a too-few-trades run.
- Each step's `evidence` is `computed`, `reused` or `unknown`. It is read from the `executed` field of the command's JSON,
  never from the `repeat` label: `repeat` means the same test by key, even when the engine ran again. Old records read `unknown`.

## Ready
- `nightly_status.readiness` decides. Two latest non-partial runs, on two UTC dates, each with no blocking defect, with all
  three paths run (`full`), a `computed` rule-test step and a `computed` setup step.
  A computed rule test is a matched recheck, or a first normal run with `executed: true`.
- N4 (follow update) counts only if a follow exists; N0 is an opt-in refresh: [cli-follow.md](cli-follow.md#nightly-n4-n0).
- Partial `--only` runs are ignored. Old records read `unknown` and never qualify.

## Failure marker and notice
- `nightly_alert` owns `<home>/nightly/LAST_FAILED`: plain text, written atomically (`alpha_core.atomic`).
  Line one is "The last nightly run failed: run <date>-<n> …"; then the date, the run and one sentence per blocking defect.
- A run with a blocking defect writes it. A run that stops with an exception (also Ctrl-C) writes it too, then raises the same exception;
  a marker that cannot be written prints a warning and never hides that exception or changes the run's result:
  a crash leaves the marker even when no record exists.
- A later full-attempt run (no `--only`) with no blocking defect removes it. A partial run never removes it.
- `alpha nightly status` and `alpha next` show one line while it exists (`failed_line`). `alpha next` carries it in `last_night`.
- `notify = true` in the config calls `notify-send` (found on PATH) with one line, for a failed night only.
  A missing program, a non-zero exit or a timeout is never an error and never changes the record or the exit code.
  No network, no e-mail, no schedule is installed.

## Disk trend
- Each new record keeps `home_bytes`: the sum of file sizes under the data home at the end of the run. Links are not followed.
  Old records have no such field and read "not recorded".
- `alpha nightly status` adds `disk`: size now, free and total bytes of the file system, the reserve and its source, and the trend
  (first and last recorded size, the change). It only reads (`home_disk`).
- The reserve is read from `<home>/crypto/storage-config.json` (`free_space_reserve`, ADR-0043); with none, the ADR-0032 default.
  Under the reserve, status prints one `LOW DISK SPACE` line. An unreadable settings file is said in words; nothing is refused here.

## Backup and restore
- `alpha home backup <dir>` writes one tar (`home/<path>` entries, then `manifest.json`) and `<archive>.sha256` beside it.
  The manifest has the relative path, size and SHA-256 of every file, every folder, and each excluded entry with its reason.
- Lock rule: the backup takes `flock` on `<home>/nightly/.lock` without waiting, the lock the crontab line holds for a nightly run.
  If it is held, the backup refuses and writes nothing. It holds the lock until the archive is complete.
- Before writing, it estimates the size (every file plus 2 kB per entry plus 1 MB) and refuses if the target disk has less free.
  A folder it cannot read stops it. A second name of one file (hard link) is stored in full: each header comes from a fresh helper.
- A file whose size or modification time changes while it is read stops the backup; the partial archive is removed.
- The archive is created with mode `0600` (owner only) from its first byte: it holds every private file of the home.
- It refuses a target inside the home. Symbolic links are never followed: each is excluded and listed. Nothing is excluded silently.
- `verify-backup` re-reads the archive, compares every file with the manifest and the archive with its `.sha256`, and names
  each bad file. Exit code 1 on any problem. It extracts nothing.
- `verify-backup` also names a double entry, a folder missing from or extra to the manifest and an unreadable manifest row.
- `restore <archive> <dir>` (module `home_restore`) verifies first, then writes only regular files and folders into a new or empty folder,
  keeps file and folder modes and times, then reads every written file again from disk against the manifest. A failure leaves an incomplete folder, said so.
  It refuses a non-empty target, the live home, a folder inside it and a folder that holds it. Unsafe entry names are refused.
- `home_backup` (the only backup module that walks the home) is on the follow-store reader list (`test_follow_separation.py`)
  on purpose: it copies bytes, parses nothing and feeds no research result. The `nightly_*` modules stay off that list.
- The Workstation launcher refuses every `alpha home` command (`catalog.classify_generic_command`: owner-only). Terminal only.
