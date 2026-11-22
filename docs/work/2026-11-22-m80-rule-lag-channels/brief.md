# Brief: `lag` on indicators and `highest` / `lowest` channels in the owner rule language

Branch: `feat/m80-rule-lag-channels`. Rules: `docs/work/_common-rules-2026-11-21.md`.

Why: the owner (a swing trader) cannot yet say "RSI crossed above 30" or "close above the 20-day high". The rule language lives in
`packages/alpha-strategies/src/alpha_strategies/rules.py` (RuleSpec; read `docs/reference/owner-rule-language.md` first). It is used by
`alpha test` with `[rule] kind = "owner"` (example `research/examples/owner-rsi-dip.toml`).

Build:
1. `lag` (whole bars, 0 by default) on every indicator operand, so a condition can compare today's value with the value N bars ago. A
   "crossed above" is then two conditions: `rsi(14) > 30` and `rsi(14, lag=1) <= 30`. A lag never reads a later bar.
2. Indicators `highest(window, source)` and `lowest(window, source)`: the rolling extreme over the last `window` bars. State clearly, and
   test, whether the window includes the current bar; add a way to exclude it (through `lag=1`) so "close > highest(20, high, lag=1)" is
   a true breakout test and never compares a bar with itself.
3. Warm-up: the history a rule needs grows by its largest lag and window; until then the value is undefined, the condition is false, and
   no trade happens (never zero, never true).
4. Canonical form: `lag = 0` serialises exactly as today, so the spec hash, the family and the golden pins
   (`tests/unit/test_spine_golden_pins.py`) of every existing rule do not change. Prove it with a test. In the family shape a non-zero lag
   and a window are numbers (replaced by `#`), so 30 window sizes are one family.
5. The speed path `alpha_strategies/rule_paths.py` and the surrogate must give the same values as the bar-by-bar path: add an equality
   test on random data for the new operands.
6. The price-sized refusal (a price-sized operand against a fixed number) covers `highest`/`lowest` of a price source.
7. Docs: `docs/reference/owner-rule-language.md`, `research/tools/rule-test.md`; one new example file under `research/examples/`.

Tests first: a look-ahead test (change bars after t; values at t do not change), the lag and window edge cases, undefined warm-up, hash
stability, path equality. Done: pull request ready with `ci-ok` green, and `report.md` in this folder.
