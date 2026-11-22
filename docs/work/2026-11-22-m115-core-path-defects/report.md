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

### 6. Prop firm: rules not shown, whole-history horizon, late check of the preset name, no tool card

- Cause: the simulation length defaulted to the whole return series (decades, so a trailing drawdown is breached almost
  surely: "bust 100%"); the rules were stored but never printed; the preset name was checked only after the backtest had read
  the data (the CLI did reject it then, so the silent fallback to "custom" could not be reproduced; the check now runs first).
- Change: `propfirm run` prints the rules used first (profit target, daily loss limit, maximum loss trailing or fixed, time
  limit, minimum trading days), then the evaluation length: 30 trading days by default, said so, or `--horizon` days. No preset
  states a time limit, so the 30-day default always applies unless `--horizon` is given. An unknown `--firm` is refused before
  any read, with the valid names. The run id now holds the resolved length.
- Tool card `research/tools/propfirm.md` (37 lines) and a row in `research/tools/README.md`.
- Seen, not mine: `research/tools/rule-test.md` had a 182-character line on main (the card test failed); wrapped within its
  40 lines.
- Test: `tests/unit/test_propfirm_words.py` (fail first: all 3 failed; the unknown preset read data first).

### 7. `alpha library search` needed the network and an e-mail

- Cause: `search` had only the network route (the literature worker) and a required `--unpaywall-email`.
- Change: `spine/library_search.py` searches offline by default: every checked and imported record (public and private:
  name, idea, mechanism, notes, market, holding time, and the imported facts as tags) and every kept paper (title, authors,
  source, why a search kept it); all words must match, case is ignored. Nothing is fetched or written. The network route is
  `--online`, and only it needs `--unpaywall-email` (refused in plain words without it).
- Test: `tests/unit/test_library_offline_search.py` (fail first: all 3 failed); `test_library_papers.py` now passes `--online`.
- Docs: `research/tools/library.md`.

### 8. Nightly example config named files that were not shipped

- Cause: `research/examples/nightly.example.toml` named `nightly-rule.toml` and `nightly-setup.toml`, which did not exist.
- Change: the two specs are shipped beside it (a fixed `ma_cross` 50/200 rule; the 20-day reclaim setup with an `[exit]`
  table), all on `SPY`; the config's assets are `SPY` and its header says the three files work together as they are.
- Test: `tests/unit/test_nightly_example_set.py` loads the config with `load_config`, parses both specs and checks the
  `[exit]` table and the shared assets (fail first: `rule_spec names .../nightly-rule.toml, which is not a file`).

### 9. `alpha follow update` with new bars

- Cause: no test drove the command itself through newly appended bars.
- Change: test only. `tests/unit/test_follow_update_new_bars.py` appends 2 synthetic bars to a temp store, runs
  `alpha follow update` (injected clock), runs it again, appends 3 more and runs it twice: the journal holds exactly the 5
  appended sessions, once each, in order (older ones `missed`, the newest one of each batch a `bar`). It passed on the first
  run: the behaviour was right, only unproven.

## Landing state

- Main was merged in once (merge commit). Conflicts in `research/tools/rule-test.md` and `library.md`: main's text kept,
  with this branch's offline-search line. The merge made `propfirm run` 152+ lines; it is split (`_report`, `_refuse_unknown`).
- Local gate: every test of this branch passes. Red on `origin/main` as well, so not this branch's: `test_reading_rule.py` (3),
  `test_reading_ledger_setup.py` (1) (pinned run ids) and 3 `test_research_playbook.py` checks (new toolbox cards on main).
- CI: the pull request is a draft as the rules ask, so `ci-ok` runs the quick checks only (they pass) and then fails by
  design. The full run starts when the owner or the reviewer marks it ready for review.

## Review round (landing)

- Item 5: `alpha test` now prints, under the headline, how the reading's deflated-Sharpe count relates to it
  ("This reading's deflated Sharpe counts 12 tries: 7 tests of spine:ma_cross on any asset, plus 5 nearby settings.").
  The deflated Sharpe counts the larger of the rule family on any asset and the tries on the asset, plus nearby settings,
  so the per-asset headline is its floor. `ledger families` prints no per-family row counts beside the headline.
  Test: `test_alpha_test_ties_the_headline_to_the_deflated_sharpe_count`.
- Final check: an older run of a test (the same test ran again after a code change) was refused with
  "0 differences". It now names the newest run to confirm. Test: `test_an_older_run_of_the_test_names_the_newest_run`.
- Final check: the plan showed the spec's placeholder costs (1 + 2 bps), and the reserved run took today's class table.
  Both now use the class costs the stored test used. Test: `test_the_final_check_keeps_the_class_costs_the_stored_test_used`.
- Recheck fields not compared (labels only): `manifest.execution_fingerprint`, `strategy_fingerprint`, `data_health`,
  `research_cutoff`, `reserve`; `spine.test_id`, `spine.reserve`, `spine.idea_card`; artifact `sha256`, `size_bytes`
  (tables compared value by value); the final check also allows `manifest.spine.reserve.held_back_bars`.
- Proven on a copy of the real data home: idea card, `--quick` SPY test linked to it, recheck "the same result, bit for
  bit", an exact repeat added no ledger row, plan and final check ran (both readings shown, slot listed), and a rule
  with no trades in the held-back years read "made no trades ... nothing can be concluded", with the warning before.
