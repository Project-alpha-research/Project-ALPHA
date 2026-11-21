---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/nightly_alert.py
  - apps/alpha-cli/src/alpha_cli/home_disk.py
verified: a976f66296419ad5
---
# Nightly failure marker and disk trend

**Reach for it when** you ask "did last night fail?" or "is the data home filling the disk?".
It reports on the system. It says nothing about whether an idea is good.

**Command**
```text
uv run alpha nightly status [--json]
uv run alpha next
```
Both only read. The [nightly run](nightly-run.md) writes the marker and the size.

**How to read it**
- A night with a blocking defect, or a run that stops with an error, writes `<home>/nightly/LAST_FAILED`. It is plain text:
  the date, the run, and each blocking defect in one sentence.
- While the marker exists, `nightly status` and `next` start with one line: "The last nightly run failed: …".
- The next run with no blocking defect removes the marker. A partial run (`--only`) never removes it.
- A run that stops with an error may leave no record. Then the marker is the only trace, and the command still exits with an error.
- Optional notice: put `notify = true` in `nightly.toml`. A failed night then calls the local program `notify-send` with one line.
  If the program is missing or fails, nothing changes. A run started by cron may have no desktop to show it on: the marker is the proof.
- `nightly status` shows the size of the data home now and the free space on its disk.
- Each new record keeps the size of the data home at the end of its run. Status shows the change from the first to the last
  recorded size. Records from before this field read "not recorded".
- `LOW DISK SPACE` appears when free space is under your storage reserve ([storage settings](../../docs/operations/storage-settings.md)).
  With no reserve set, the default applies: the larger of 15% of the disk and 100 GB.

**What it cannot tell you** Why the disk grew, or which folder grew. It sends no e-mail and uses no network: you must look.
A size is the sum of file sizes; the space used on disk can differ a little.

**Next** Read the marker file, then `uv run alpha nightly status` for the command that reproduces each defect.
Low on space: make a [backup](home-backup.md) on another disk before you delete anything.
