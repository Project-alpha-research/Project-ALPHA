# Report: core-path defects (m115)

Brief: `docs/work/2026-11-22-m115-core-path-defects/brief.md` on `origin/work/m102-briefs`.
Rules: `docs/work/2026-11-21-common-build-rules/brief.md`.

## Decisions

- Commit trailer: the commits name the model that did the work, as the session asks; the common rules name another model.

## Items

### 1. Final check and recheck blocked by the idea-card link

- Cause: the spec excludes the card link from every hash, so a recheck run has no `spine.idea_card`, but the comparison compared it.
- Change: `spine.idea_card` joins the fields the recheck does not compare (`recheck_compare.SKIPPED`); the stored link stands.
  The other fields were checked: `name` and `idea` are in the spec hash (test-defining), `test_id`, `reserve`, health labels
  and fingerprints were already skipped; every number is still compared.
- Test: `tests/unit/test_recheck_idea_card.py` (fail first: `manifest.spine.idea_card` stored `9f4a…`, recomputed `<missing>`).

### 2. `confirm run` refusal without a reason; slot line printed too early

- Cause: the command printed "Spending 1 slot now" before the recheck ran, so a refusal read as a spent slot. The silent exit could
  not be reproduced here: in every refusal tried (recheck mismatch, real CLI in a subprocess) the reason was printed on stdout.
- Change: `confirm_run(..., on_spent=...)` calls back right after the slot receipt is written; the command prints the slot line
  there, on stdout. A refusal prints only the plan and the reason ("... No slot was used.").
- Tests: `tests/unit/test_confirm_run_words.py` (fail first: the slot line was in the refused output);
  `test_reserved_confirmation_surfaces.py` now asserts the slot line is absent when the run is refused.

### 3. No trades in the held-back years read as a fault

- Cause: the reading treated a missing Sharpe as a fault in every case, and the report library's charts divided by zero on the
  flat equity line of a rule with no trades (the numpy and scipy warnings came from `render_tearsheet_html`).
- Change: `spine/reading.no_trades`: 0 scored trades and a volatility of exactly 0 give the sentence "The rule made no trades
  from <first> to <last>; nothing can be concluded from this period." with `too little to read`; the numbers check is
  `not-checked`. Any other missing statistic stays a fault. The same applies in an ordinary `alpha test` and in the old-style
  report line (`report_readings`). The tearsheet render hides warnings only when every out-of-sample return is 0.
  `confirm plan` (and the plan that `confirm run` prints) states the trades per year of the earlier scored period and warns in
  one sentence when fewer than 5 trades are to be expected in the held-back span; computed from the stored run only.
- Tests: `tests/unit/test_confirm_no_trades.py` (fail first: all 4 failed on the old code; the repro printed
  "Reading: fault. Fault: the out-of-sample Sharpe could not be computed." and the numpy warnings).
- Docs: `cli-rule-readings.md` (the exception), `research/tools/reserved-confirmation.md`.
- Seen, not mine: `test_reading_rule.py` (3) and `test_reading_ledger_setup.py` (1) fail on `origin/main` too (pinned run ids).

### 4. An exact repeat wrote a ledger row

- Cause: `run_idea` appended a ledger row for every result, also when the stored run was served (`executed: false`). The row
  was labelled `repeat` and left out of the deflation counts, but it raised the raw row count, the family `rows` of
  `alpha ledger families` (the 11 to 12), `same_asset_repeats` and the ledger entry number. The diagnostics wrote no row.
- Change: a served repeat writes no ledger row (the idea-card link is still noted). Decision: a repeat after a code change ran
  the engine again into a new run folder, so it keeps its labelled row (that run must stay findable by `confirm` and `recheck`).
- Test: `tests/unit/test_repeat_adds_nothing.py` (fail first: rows 1 to 2, family rows 1 to 2, same-asset repeats 0 to 1).
  Updated to the new rule: `test_run_identity_held_back.py`, `test_idea_card.py` (they asserted the repeat row).
- Docs: `cli-trial-ledger.md`.

### 5. Four different "how many tries" numbers

- Cause: each command printed its own count: `ledger families` the deflation total over every family (rdagent included),
  `ledger summary` the record count by kind, `alpha results` the ledger row count, `alpha test` the ledger row number.
- Change: one definition in `spine/tries.py`: a try is one distinct test on an asset, the same rows `same_asset_tests`
  counts for the deflated Sharpe (the loop moved to `deflation.distinct_asset_tests`, shared by both). `alpha test` (per
  asset), `alpha results`, `ledger summary` (with by kind and by family; they add up to the total), `ledger families` and the
  new `alpha ledger tries <ASSET>` print it as "Tries on SPY: N tries (family n, ...)". The other counts stay in the JSON only.
  `alpha ledger query` lists the valid question names in plain text when it rejects one. Unknown rows are still disclosed.
- Not changed: the reading sentence's "family counted as N tries" is the deflated Sharpe's own N (it adds the sensitivity
  variants). It is part of the stored reading and of the recheck comparison; changing it would move every stored reading.
- Tests: `tests/unit/test_tries_headline.py` (fail first: 4 of 5 failed); `test_ledger_cmds.py` wording updated.
- Docs: `cli-trial-ledger.md`, `research/tools/deflated-sharpe-and-trials.md`, `research/PLAYBOOK.md` example.
  `docs/reference/commands.md` is not regenerated (brief); it will list `ledger tries` when it is next regenerated.
