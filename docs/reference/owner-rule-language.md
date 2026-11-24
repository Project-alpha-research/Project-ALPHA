---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/owner_rule.py
  - packages/alpha-strategies/src/alpha_strategies/rules.py
  - packages/alpha-strategies/src/alpha_strategies/rule_paths.py
  - apps/alpha-cli/src/alpha_cli/spine/owner_variants.py
  - apps/alpha-cli/src/alpha_cli/spine/owner_reading.py
---
# Owner rule language in `alpha test`

What an owner rule can say today, and what it cannot. The tool card is [rule test](../../research/tools/rule-test.md).

## Form

- A spec has `rule = {kind = "owner", spec = {...}}`. The `spec` table is the rule language's `RuleSpec`.
- Today a rule is long while all `long_when` conditions hold, and flat otherwise. All-in sizing, daily bars, as for the old kinds.
- The spec is stored in one canonical form: parsed, then written with defaults (`history`). The rule `name` is a constant
  inside the hash, so two specs that differ only in that name are one test. The display name is the spec's own `name`.
- `history` is the number of bars each decision sees. The default is 4 times the longest window, at least 60 and at most 2,000 (the largest `history` allowed).
  A recursive indicator (`rsi`, `ema`)
  costs time in proportion to it: set `history` lower, but not below the longest window, to run faster.
- `history` below the longest window (a lag counts: `lag = 20` needs 21 bars) or above 2,000 is refused; it is never cut short.
- Every indicator starts again on each decision's window. So `rsi` and `ema` differ a little from values over the full price
  history (their recursion starts at the window's first bar). The value is the same on every run and in every place that
  reads it: the engine, the random-price test and `alpha rules`.
- Example: `research/examples/owner-rsi-dip.toml`.

## Operands

| Operand | Meaning |
|---|---|
| `{source = "close"}` (or `high`, `low`), optional `lag = n` | the price n completed bars before the decision bar; 0 is today's close |
| any indicator below, optional `lag = n` | the indicator's value n bars before the decision bar; never a later bar |
| `highest`, `lowest` with `params = [n]`, `field` high, low or close | the highest or lowest value of that price over the last n bars |
| `{value = x}` | a constant |
| `sma`, `ema` with `params = [n]` | simple or exponential average of closes over n bars |
| `rsi` with `params = [n]` | RSI of closes, 0 to 100 |
| `atr` with `params = [n]` | average true range; reads high and low |
| `bbands` with `params = [n, k]`, `field` upper, middle or lower | Bollinger bands |
| `macd` with `params = [fast, slow, signal]`, `field` line, signal or histogram | MACD |
| `hawkes`, `cmma`, `runs_z`, `perm_entropy`, `vg_path`, `reversibility` | research indicators; ask the owner before use |
| `vsa` | refused: it reads volume, which the rule window does not keep |

- `highest` and `lowest` include the bar they are read on. So `close > highest(20, high)` can never be true for the same bar.
  Write `lag = 1` on the channel for a true breakout: `{indicator = "highest", params = [20], field = "high", lag = 1}` is the
  highest high of the 20 bars before today. The channel window is at least 2 bars.
- "Crossed above 30" is two conditions: `rsi(14) > 30` and `rsi(14, lag = 1) <= 30`.
- Warm-up: the history a rule needs is its longest window plus its lag. Before that the value is undefined, the condition is
  false and no trade happens; it is never zero. A `history` below that is refused.
- A lagged indicator is read on the same decision window, so it starts its recursion at the window's first bar like the
  unlagged one. `lag = 0` is the default and is not written in the stored form: older specs keep their hash.
- A condition is `left`, `op` (`>`, `<`, `>=`, `<=`) and `right`. A side is the AND of at most 12 conditions.
- `short_when` that is present and not empty is refused: "the short side is not built yet in alpha test".
- A price-sized operand compared with a fixed number (`close > 400`) or with a scale-free indicator (`close > rsi`) is refused.
  The first random-price test rebuilds prices from returns, starting at 1, so a fixed price level has no meaning there.
  Price-sized: a source, `sma`, `ema`, `atr`, `bbands`, `macd`, `highest`, `lowest`. Scale-free: `rsi` and the research indicators.
- Allowed: price-sized against price-sized (`close > sma`, `atr 5 < atr 20`, `macd line > macd signal`), price-sized against 0
  (`macd histogram > 0`), and scale-free against a number (`rsi < 30`).
- Example: "RSI(14) below 30 and close above the 200-day average" is two conditions in `long_when`.

## Labels

- `null-closes-for-high-low`: the rule reads high or low (`atr`, `hawkes`, `cmma`, a high or low source, a channel of high or low). The first random-price
  null has no intrabar range, so it uses closes for high and low. The engine runs and the other nulls use the real bars.

## Family

- The ledger family of an owner rule is `owner:<12 hex>` (so `spine:owner:<12 hex>` in the reader). The hex is a hash of the
  rule shape: no name, no history, every number a hole, `<` as `<=`, a constant on the right, conditions sorted, a repeated
  condition once. The indicator name, its `field` and the source are part of the shape. A lag is a number (a hole) but
  whether a lag is present is part of the shape. A window is a hole too.
- Thirty RSI thresholds, or thirty channel windows, are one family. A different structure is another family. The trial count for the deflated Sharpe is
  the larger of the family count and the count of all tests on the same asset.
- Every owner-rule reading says it: "This rule shape: K tests on this data. All rules on <asset>: M tests. The deflated Sharpe
  uses N = max(K, M)." Repeats of the same test count once. Parameter variants count as tries in K and M.

## Parameter variants

- `alpha test` re-runs the rule with each window and each non-zero constant at 0.8 and 1.2 times its value, one change at a time.
  Windows are the params of `sma`, `ema`, `rsi`, `atr`, `highest`, `lowest`, the first of `bbands`, all three of `macd`, and a lag. They round to whole
  bars (at least 2; a lag at least 1). A variant equal to the original, or one the language refuses, is left out. At most 8 run.
  A Bollinger width, a research indicator's params and a constant of 0 stay as written.
- The reading shows them as a table of readings (Sharpe, total return, maximum drawdown). It picks no best one and gives no verdict.

## Engine and random-price test

- The engine reads prices rounded to the cent; the first random-price test reads the stored closes, rescaled to start at 1.
  A condition that is an exact tie on one and not the other can decide differently on that bar. This is the same for the old
  kinds. Measured: 0 of 8,212 SPY bars for the example rule; up to 7 of 3,881 bars for `close > close lag 1` on synthetic
  prices with many decimals. The full-engine random-price test reads the real bars and does not have this difference.
- The first random-price test computes every bar of a path in one pass (`rule_paths.py`). Its numbers equal the
  bar-by-bar rule exactly: `tests/unit/test_rule_paths.py`.

## What it cannot say yet

- Exits and time stops ("hold until RSI is above 60, or 10 days at most"). The rule only holds while its conditions hold.
- Shorts in `alpha test`. Volume and open prices. Fixed price levels (`close > 400`). A one-word crossing
  (write the two conditions above). Arithmetic on operands (`close > 1.02 * sma`).
- OR groups. Calendar. Other assets as inputs.
- Position sizing other than all-in.
