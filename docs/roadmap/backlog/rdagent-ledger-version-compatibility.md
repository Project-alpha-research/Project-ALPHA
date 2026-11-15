# One trial ledger, many code versions

**Status:** Scoped
**Rough size:** M

## Problem / why

The RD-Agent trial ledger (`rdagent-factor-trials.jsonl`) is a single append-only file outside
git, shared by every run on the machine. The code that reads it lives on whatever branch a run
uses. On 2026-11-15 the system tests on the stacked pull requests #178, #183, #187 and #191 wrote
V2 rows, V3 rows and rule-family rows into the shared file. Another session's runs also wrote to
it from its own branch. Main's reader (V1 only) now refuses the whole ledger
("invalid trial ledger line 15"). So until those pull requests merge, no loop can run from main
against the real ledger. Readers fail closed, which is right for integrity, but one newer row
blocks every older reader, and nothing says which code version can read the file.

## What "done" looks like

- The ledger has a small header or sidecar that names the newest schema version it holds. A
  reader that is too old gives a plain message naming that version and the minimum code
  version, instead of a parse error on a line number.
- Older readers keep counting rows they cannot interpret, for the family size and total trials.
  They skip such rows with a warning, and never use them in a statistic.
- A test proves a V1-only reader and a V3 reader both work on a mixed ledger.

## Dependencies

The four pull requests above; ADR-0049 and ADR-0050 (schemas).

## Sources

- System test of 2026-11-15 (pull requests #178, #183, #187, #191; the hand-back's system findings).
