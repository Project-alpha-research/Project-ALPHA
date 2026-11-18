---
owner: data layer
sources:
  - packages/alpha-data/src/alpha_data/health.py
  - apps/alpha-cli/src/alpha_cli/spine/data_health.py
  - apps/alpha-cli/src/alpha_cli/_data_health.py
  - apps/alpha-cli/src/alpha_cli/data_cmds.py
verified: 0814b2295c388803
---

# Daily data health

**Reach for it when** you want to know whether a stored daily series has a known data fault before you test on it.

**Command** `uv run alpha data health SPY@home`. A symbol alone searches every registered store.
Add `--universe members.csv` (membership intervals) to check survivorship. `--json` adds thresholds and all dates.

**How to read it** Four groups come in order: adjustments, timestamps, gaps, survivorship.
Each group shows its worst status, then one sentence per check. The verdict is the worst status of all.
Statuses, best to worst: not-applicable (the check does not apply, such as splits for crypto), pass, warn and fail.
- Adjustments: an overnight jump close to a split ratio with no recorded split. The command compares no other series,
  so such a jump warns. A real crash that happens to match a ratio also warns; check it by hand.
- Timestamps: time zone, order, midnight UTC stamps, closed-exchange days, unfinished bars, and data that stops early.
- Gaps: repeated or impossible bars, missing trading days, zero volume, a spike that reverses the next day,
  and prices that stay frozen (the whole bar repeats) for 5 bars while volume trades.
- Survivorship: needs a membership history; without one the list is survivors only.
Prices are raw. Dividends are separate cash events; this report does not check them.

**Saved report** Each check writes `health/<symbol>.json` in the store. `--stored` reads it back.
If any input byte changed since, it says "out of date" instead of the old verdict. Run it again without `--stored`.
**On a run** A rule test or a setup find, study or trade looks up this report for each series it reads.
It counts only if it was made from the same bytes the run reads. Each series is pass, warn, fail, out-of-date (the bytes changed) or unchecked (no report).
The run takes the worst, in order: fail, out-of-date, unchecked, warn, pass. Its label is `data-health-<verdict>`;
out-of-date also gets `data-health-unchecked`. The run never makes a report unless you add `--check-data`.
`--check-data` makes missing or out-of-date reports first. For a stock it compares up to 20 other stock series
in the same store, on the same calendar, with overlapping dates. The summary gives the peer count.
A fail stops the run before any test work. Fix the data, or run again with `--accept-bad-data "reason"` (one command only).
The verdict covers all stored bars, as checked at the report time shown. Older runs read "Data health: not recorded."

**What it cannot tell you** A clean report only means these faults were not found. The prices can still be wrong.
**Next** Check flagged dates against another source. RD-Agent panels remain the next integration.
