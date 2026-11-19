---
owner: command line runs and validation
sources:
  - apps/alpha-cli/src/alpha_cli/spine/reading.py
  - apps/alpha-cli/src/alpha_cli/spine/reading_read.py
  - apps/alpha-cli/src/alpha_cli/spine/run.py
  - apps/alpha-cli/src/alpha_cli/test_cmds.py
  - apps/alpha-cli/src/alpha_cli/results_cmds.py
  - apps/alpha-cli/src/alpha_cli/next_cmds.py
  - tests/unit/test_reading_rule.py
verified: 919d902c443ae2bd
---

# Command line rule-test readings invariants

What must not break when changing the reading of a rule test. Owner decision 2026-11-19: results are readings in context, not
grades. The stored run files are in [command line runs](cli-runs.md#stored-facts-and-diagnostics).

## Rule-test readings

- A new run manifest stores `reading` (`AlphaReadingV1`, `spine/reading.py`) beside the old `verdict`. Both stay in the file.
  The reading only arranges numbers the gauntlet stored. It computes no statistic and changes no id, trial count or threshold.
- Parts: `checks` (sound, fault or not-checked), `measures`, `evidence` (word and reasons), `aim`, `counts`, `sentence`.
- Four evidence words, defined in one module with the source of each number: `clear of chance`, `some evidence`, `not clear of chance`,
  `too little to read`. `too little to read` (under 30 closed trades or 100 out-of-sample observations) wins over every other word.
  A result that looks too good (`implausibly-good`) cannot read `clear of chance`.
- The aim today is buy-and-hold over the scored days, from point estimates. No interval for the difference exists, so the words are
  `above the aim`, `below the aim`, or `within the uncertainty of the aim` only when both Sharpe values round alike.
- A statistic that could not be computed, a look-ahead flag in the audit, or a failed data check is a fault:
  "Fault: ... Fix this first. No reading." Fact checks stay hard.
- A manifest without `reading` gets one derived from its stored numbers on read. A ledger row with only a letter reads
  "graded C under the old rules". Owner text for rule tests never prints a letter grade, "supported", "rejected", "pass", "fail" or "profit".
- `--json` keeps `verdict` and adds `reading`. The ledger row and its outcome words still come from the letter; the next change moves them.
- A run id hashes every `alpha_cli` source byte, so any edit moves it. `tests/unit/test_reading_rule.py` holds that input fixed and
  proves the reading changes no id.
