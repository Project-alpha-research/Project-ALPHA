---
owner: command line runs and validation
sources:
  - apps/alpha-cli/src/alpha_cli/spine/idea_file.py
  - apps/alpha-cli/src/alpha_cli/spine/idea_file_text.py
  - apps/alpha-cli/src/alpha_cli/spine/idea_map.py
  - apps/alpha-cli/src/alpha_cli/follow_counts.py
  - tests/unit/test_idea_file.py
verified: 70817702c141b473
---

# Command line idea file invariants

What must not break when changing `alpha idea file`. The readings it joins are described in
[rule-test readings](cli-rule-readings.md#rule-test-readings).

## Idea file

- `alpha idea file <card id> [--json]` prints one page per idea. It joins records that exist. It computes no statistic.
- Read-only: no file under the home changes, no ledger row, no network, no model call.
  The ledger is read with `read_trials_readonly`, which never creates the lock file.
  A test compares the home before and after, with no lock file present.
- Order: the card; the map; readings oldest first; paper follows; counts; open points.
  `--json` keys: `card`, `map`, `follows`, `readings`, `counts`, `open_points`.
- `follows[]` comes from `follow_counts.follows_of_card`, a listed reader: the file never opens `forward/`. The map line `followed forward on paper`
  is `done` when a follow record names the card. Each rule test carries `figures_available`: figure ids only; nothing is drawn.
  `alpha idea list --json` adds `saved_at` and `tests_linked` to each card.
- Each reading is the one `spine/reading.py` stores or derives, with the evidence word unchanged. A fault prints as a fault.
  Check results print with their declared or exploratory word. No best result is picked.
- The map is facts, never a gate. A line is `done` with its evidence ids, `not yet`, or `not recorded` when linked runs cannot be read.
  A run that is a fault does not count towards a map line.
  - Examples: a setup find is linked. Controls: a setup study of a linked find, or a stored random-data test.
  - Baseline: an aim row in a reading. Settings: stored variants tried, or more than one setting of the same rule linked.
  - Costs: a stored `costs.break_even` result. Out-of-sample numbers recorded: stored out-of-sample numbers; this is not an independent replication.
  - A setup study that cannot be read does not count. The study sentence prints; its outcome word does not (old wording), and the page says so once.
  - Held-back confirmation and following forward on paper read `not built yet`. The forward-use code is not read.
- Text caps at 20 readings: the first 10 and last 10 print, the middle is counted. `--json` carries all.
- Text for the owner never prints a letter grade, "supported", "rejected", "pass", "fail" or "profit". A scan test holds this.
