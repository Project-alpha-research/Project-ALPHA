---
owner: data layer
sources:
  - packages/alpha-data/src/alpha_data/health.py
  - apps/alpha-cli/src/alpha_cli/_data_health.py
  - apps/alpha-cli/src/alpha_cli/data_cmds.py
verified: e09788c145598921
---

# Daily data health

**Reach for it when** you want to know whether a stored daily series has a known data fault before you test on it.

**Command** `uv run alpha data health SPY@home`. A symbol alone searches every registered store.
Add `--universe members.csv` (membership intervals) to check survivorship. `--json` adds thresholds and all dates.

**How to read it** Four groups come in order: adjustments, timestamps, gaps, survivorship.
Each group shows its worst status, then one sentence per check. The verdict is the worst status of all.
- Adjustments: an overnight jump close to a split ratio with no recorded split. The command compares no other series,
  so such a jump warns. A real crash that happens to match a ratio also warns; check it by hand.
- Timestamps: time zone, order, midnight UTC stamps, closed-exchange days, unfinished bars, and data that stops early.
- Gaps: repeated or impossible bars, missing trading days, zero volume, a spike that reverses the next day,
  and prices that stay frozen (the whole bar repeats) for 5 bars while volume trades.
- Survivorship: needs a membership history; without one the list is survivors only.
Prices are raw. Dividends are separate cash events; this report does not check them.

**Saved report** Each check writes `health/<symbol>.json` in the store. `--stored` reads it back.
If any input byte changed since, it says "out of date" instead of the old verdict. Run it again without `--stored`.

**What it cannot tell you** A clean report only means these faults were not found. The prices can still be wrong.
Runs do not read this report yet.

**Next** Check each flagged date against a second source before you use the series.
