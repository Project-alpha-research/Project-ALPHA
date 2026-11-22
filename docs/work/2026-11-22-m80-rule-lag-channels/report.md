# Report: `lag` on indicators and `highest` / `lowest` channels

Branch `feat/m80-rule-lag-channels`. Gate `scripts/gate.py check --base origin/main`: all pass. The guards
`test_code_size`, `test_research_reads_are_cut`, `test_follow_separation` and `test_spine_golden_pins` pass unchanged.

## What changed
1. `lag` (whole bars, default 0) now works on every indicator operand, as it already did on price sources. Bar t reads the
   value of bar t - lag. A lagged indicator is read on the same decision window, so its recursion (RSI, EMA) starts at the
   window's first bar, as the unlagged one does.
2. New indicators `highest` and `lowest`: `{indicator = "highest", params = [20], field = "high"}`. The window **includes the
   current bar**. `lag = 1` excludes it. `close > highest(20, high, lag 1)` is a true breakout test.
3. Warm-up: needed bars = base need + lag (`highest`: window + lag). Before that the value is NaN, the condition is false
   and no trade happens. A `history` below the need is refused.
4. `lag = 0` is not written, so every existing spec hash, family and golden pin is unchanged. Proof:
   `test_existing_rule_hash_and_family_do_not_move_with_lag_support` (pinned from `origin/main`: same hash and family
   before and after).
5. Family shape: a lag and a window are `#`. Whether a lag exists is part of the shape.
6. Speed path `rule_paths.py`: lagged indicators read the shorter window (first `history - lag` bars); channels use a
   rolling max/min. Equality (`==`) with the bar-by-bar path is tested for 13 new operands and 2 new rules.
7. Price-sized refusal covers `highest` / `lowest`. Their `high` / `low` fields add the `null-closes-for-high-low` label.
8. Docs: `owner-rule-language.md`, `research/tools/rule-test.md`; example `research/examples/owner-breakout-rsi-cross.toml`.

## Decisions
- **Channel source is the `field` key**, not a new key. `field` already carries the series choice for `bbands` and `macd`, and
  `source` would clash with the source-operand parser.
- **Channels are not in `INDICATOR_ARITY` / `INDICATOR_FIELDS`.** Those tables mirror the chart overlays and the Workstation
  rule builder (`ruleBuilderModel.ts`), guarded by drift tests; I did not weaken them. New tables `RULE_ARITY`,
  `RULE_FIELDS`, `CHANNEL_FIELDS` hold the superset. **Consequence:** the Workstation rule builder does not offer `lag` on
  indicators or the channels yet; a rule written in a spec file works everywhere else. A front-end change is a follow-up.
- "Crossed above" stays two conditions, as the brief says. No new operator.
- Window must be at least 2 bars (the existing window rule).
- Commit trailer and PR footer follow the session's attribution instruction, not the common-rules model line.

## Tests (fail-first)
Tests were written alongside the code. I then removed the source changes (`git stash` of `packages` and `apps`) and re-ran:
16 of 47 tests in `test_owner_rule.py` and `test_rules_indicator_lag.py` failed on the old code, the rest pass on both
(they pin old behaviour). New: look-ahead (poison bars after t, with a control), lag and window edges, undefined warm-up,
malformed channels, hash stability, family holes, path equality.
The old test "lag is refused on an indicator" was replaced: only a constant refuses `lag` now.

## Not done / numbers
- `rules.py` grew from 633 to 667 lines (limit rule is for new modules; `test_code_size` did not ask to lower anything).
- Not run: full CI. The Linux orphan test (`test_assistant_cleanup`) needs `run_owned_test.py`; it is unrelated and the gate runs it as designed.
