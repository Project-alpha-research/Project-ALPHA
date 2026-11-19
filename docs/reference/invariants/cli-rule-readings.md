---
owner: command line runs and validation
sources:
  - apps/alpha-cli/src/alpha_cli/spine/reading.py
  - apps/alpha-cli/src/alpha_cli/spine/reading_read.py
  - apps/alpha-cli/src/alpha_cli/spine/idea_file.py
  - apps/alpha-cli/src/alpha_cli/spine/idea_file_text.py
  - apps/alpha-cli/src/alpha_cli/spine/idea_map.py
  - tests/unit/test_idea_file.py
  - apps/alpha-cli/src/alpha_cli/spine/run.py
  - apps/alpha-cli/src/alpha_cli/test_cmds.py
  - apps/alpha-cli/src/alpha_cli/results_cmds.py
  - apps/alpha-cli/src/alpha_cli/next_cmds.py
  - tests/unit/test_reading_rule.py
verified: 100a1aa69bfee9a6
---

# Command line rule-test readings invariants

What must not break when changing the reading of a rule test. Owner decision 2026-11-19: results are readings in context, not
grades. The stored run files are in [command line runs](cli-runs.md#stored-facts-and-diagnostics).

## Rule-test readings

- A new run manifest stores `reading` (`AlphaReadingV1`, `spine/reading.py`) beside the old `verdict`. Both stay in the file.
  The reading only arranges numbers the gauntlet stored. It computes no statistic and changes no id, trial count or threshold.
- Parts: `checks` (sound, fault or not-checked), `measures`, `evidence` (word and reasons), `aim`, `counts`, `sentence`.
- Four evidence words. Their one home is `WORDS` in `spine/reading.py`; the list below is that text, and
  `tests/unit/test_reading_rule.py` fails when the two differ. The precedence is the list order from the bottom up:
  `too little to read` wins, then `not clear of chance`, then `some evidence`; `clear of chance` needs every check.
  - `too little to read`: Under 30 closed trades or under 100 out-of-sample observations, or either count was not stored. This word wins over every other.
  - `not clear of chance`: The Sharpe is not above 0, its interval includes 0, random data did as well as the rule in more than 5%
    of draws, or the deflated Sharpe after counting trials is under 0.95. A missing interval, null test or deflated Sharpe reads
    the same way.
  - `some evidence`: The Sharpe interval is above 0, every null test holds and deflated Sharpe is at least 0.95, but
    cross-validation, a plausibility caution or a plausibility check that did not run, or trials not counted from a ledger family
    hold back the top word.
  - `clear of chance`: Every check holds after counting all trials: each null test at 0.95, the 95% Sharpe interval above 0,
    deflated Sharpe at least 0.95 with the trials counted from the ledger family, cross-validated mean Sharpe above 0, and the
    plausibility check ran and raised nothing.
- Only the deflated Sharpe counts trials. The bootstrap interval and the null tests do not. So no positive word is printed when the
  trial-corrected figure is under its line or missing, and a missing number never makes a word stronger.
- The aim today is buy-and-hold over the same scored days, on the run's price basis, with no costs. The relation uses the strategy's
  stored 95% bootstrap Sharpe interval: an aim below it reads `above the aim`, above it `below the aim`, inside it
  `within the uncertainty of the aim`. The benchmark's own uncertainty is not included, and the basis line says so. With no
  same-days benchmark or no stored interval there is no aim row.
- A statistic that could not be computed, a look-ahead flag in the audit, or a failed data check is a fault:
  "Fault: ... Fix this first. No reading." Fact checks stay hard.
- A manifest without `reading` gets one derived from its stored numbers on read. A ledger row with only a letter reads
  "graded C under the old rules". Owner text for rule tests never prints a letter grade, "supported", "rejected", "pass", "fail" or "profit".
- `--json` keeps `verdict` and adds `reading`. The ledger row and its outcome words still come from the letter; the next change moves them.
- A run id hashes every `alpha_cli` source byte, so any edit moves it. `tests/unit/test_reading_rule.py` holds that input fixed and
  proves the reading changes no id.

## Idea file

- `alpha idea file <card id> [--json]` prints one page per idea. It joins records that exist. It computes no statistic.
- Read-only: no file under the home changes, no ledger row, no network, no model call. A test compares the home before and after.
- Order: the card; the map; readings oldest first; counts; open points. `--json` keys: `card`, `map`, `readings`, `counts`, `open_points`.
- Each reading is the one `spine/reading.py` stores or derives, with the evidence word unchanged. A fault prints as a fault.
  Check results print with their declared or exploratory word. No best result is picked.
- The map is facts, never a gate. A line is `done` with its evidence ids, `not yet`, or `not recorded` when linked runs cannot be read.
  A run that is a fault does not count towards a map line.
  - Examples: a setup find is linked. Controls: a setup study of a linked find, or a stored random-data test.
  - Baseline: an aim row in a reading. Settings: stored variants, or more than one rule setting linked.
  - Costs: a `costs.break_even` result. Independent check: stored out-of-sample numbers.
  - Held-back confirmation and following forward on paper read `not built yet`. The forward-use code is not read.
- Text caps at 20 readings: the first 10 and last 10 print, the middle is counted. `--json` carries all.
- Text for the owner never prints a letter grade, "supported", "rejected", "pass", "fail" or "profit". A scan test holds this.
