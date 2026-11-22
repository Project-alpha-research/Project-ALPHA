# Report: saved owner rules, parameter variants and the count sentence (m81)

Branch `feat/m81-saved-rules-count`. All four parts are built. Local gate (`gate.py check --base origin/main`) and `lint-imports` pass.

## What changed

1. **Saved rule.** `rule = {kind = "owner", saved = "<name>"}` now loads. `load_spec` (`spine/spec.py`, new `data_dir` argument, passed by
   `test_cmds.py`) reads the file with `rules_cmds.load_rule_text` (the `alpha rules` reader; no second store). It builds the full
   `OwnerRule` before the spec is hashed. A missing, invalid or short-side saved rule fails with its name. `saved` with `[rule.spec]` is refused.
2. **Count sentence.** `spine/owner_reading.py` (new). `diagnose.trials` adds `trials.owner_counts` for owner families only
   (`shape_tests` = family `n_trials`, `asset_tests` = `available_sharpes`, `n_used` = `n_trials_used`). `build_reading` adds
   `count_sentence` and `variant_table` to an owner-rule reading. `alpha test` text prints both. How N is computed did not change.
3. **Variants.** `spine/owner_variants.py` (new) lists neighbour specs. `diagnose.variant_specs` runs each as a full-sample re-run,
   counted as a try like the old variants. The "not built yet" note (`VARIANTS_NOTE`) is gone.
4. **Docs.** `owner-rule-language.md`, `cli-rule-readings.md`, `research/tools/rule-test.md`, `invariants/README.md`. To keep
   `cli-rule-readings.md` at 200 lines I moved its "Context gate plan" section, word for word, to the new
   `docs/reference/invariants/cli-rule-context-gate.md`. The readings page is now 183 lines.

## Decisions (nobody could be asked)

- **`--diagnostics` does not exist.** Diagnostics already run by default (`--no-diagnose` turns them off). The variants run in that
  default step. I added no flag.
- **Cap of 8** counts parameter variants only. `costs_x2` runs first and is extra, as for the old kinds. A rule can have 9 rows.
- **What is a window:** the params of `sma`, `ema`, `rsi`, `atr`, the first of `bbands`, all three of `macd`, and a lag (floor 1, not
  2; lag 0 is "today" and is left alone). Bollinger width and the research indicators' params are not varied: their meaning is not
  a window length. Order: left to right through the conditions, first all numbers of condition 1, and so on.
- **History:** a variant keeps the rule's `history`; if the new window needs more, the language default is used.
- **Counts include variants.** K and M are what the code already used, and it counts scored variants as tries. So K is not just ledger rows.
- **Old stored runs** keep the reading they stored: no count sentence is invented for them.
- **Attribution line.** The common rules ask for a `Co-Authored-By: Claude Fable 5.2` line. The session that built this is not that
  model, so commits carry the session's own attribution line instead.
- **`gh` is not installed in this environment.** The pull request was handled with the GitHub tools.

## Fail-first evidence

- `tests/unit/test_owner_saved_rule.py`: 7 of 8 failed with `TypeError: load_spec() got an unexpected keyword argument 'data_dir'`
  before the change (the 8th, "saved needs a data dir", passed by accident through the old error text).
- `tests/unit/test_owner_counts.py`: failed at import (`No module named alpha_cli.spine.owner_reading`) before the change.
- `tests/unit/test_owner_variants.py` was written together with its module; no separate fail-first run was kept.

## Tests

- Hash, family, dumped spec equal for saved and inline; edit after load changes nothing; missing, invalid, short-side, mixed and bad-name refusals.
- Old run rechecks to `match: true, computed: true` after the saved rule is edited (stored `spec.json` carries the full rule).
- K and M on a temp ledger with 3 thresholds of one shape and 2 other shapes; the sentence text; a repeat counts once;
  an `ma_cross` reading has neither key.
- Variant list: four for a window and a constant, rounding and floors, equal variant skipped, zero constant, cap of 8, history, Bollinger width, lag.
- Golden pins, research-cut guard, follow separation, code-size, recheck, reading tests: pass unchanged. `test_owner_rule_run.py` had one
  assertion that said "only costs_x2 runs"; it now says the table has `costs_x2` first and at most 9 rows.

## Not done / numbers

- No protected path was edited. `commands.md`, `STATUS.md` and the OpenAPI file did not change (no command or route changed).
- `fs.py verify` was not run. Pages I edited may list as stale.
- Code size: `test_code_size.py` asked for no lowering. Lines: see the pull request diff.
- The new count tests run 5 quick gauntlets: about 2 minutes.
