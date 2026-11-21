---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/owner_rule.py
  - packages/alpha-strategies/src/alpha_strategies/rules.py
verified: bdcb713befa5d419
---
# Owner rule language in `alpha test`

What an owner rule can say today, and what it cannot. The tool card is [rule test](../../research/tools/rule-test.md).

## Form

- A spec has `rule = {kind = "owner", spec = {...}}`. The `spec` table is the rule language's `RuleSpec`.
- Today a rule is long while all `long_when` conditions hold, and flat otherwise. All-in sizing, daily bars, as for the old kinds.
- The spec is stored in one canonical form: parsed, then written with defaults (`history`). The rule `name` is a constant
  inside the hash, so two specs that differ only in that name are one test. The display name is the spec's own `name`.
- Example: `research/examples/owner-rsi-dip.toml`.

## Operands

| Operand | Meaning |
|---|---|
| `{source = "close"}` (or `high`, `low`), optional `lag = n` | the price n completed bars before the decision bar; 0 is today's close |
| `{value = x}` | a constant |
| `sma`, `ema` with `params = [n]` | simple or exponential average of closes over n bars |
| `rsi` with `params = [n]` | RSI of closes, 0 to 100 |
| `atr` with `params = [n]` | average true range; reads high and low |
| `bbands` with `params = [n, k]`, `field` upper, middle or lower | Bollinger bands |
| `macd` with `params = [fast, slow, signal]`, `field` line, signal or histogram | MACD |
| `hawkes`, `cmma`, `runs_z`, `perm_entropy`, `vg_path`, `reversibility` | research indicators; ask the owner before use |
| `vsa` | refused: it reads volume, which the rule window does not keep |

- A condition is `left`, `op` (`>`, `<`, `>=`, `<=`) and `right`. A side is the AND of at most 12 conditions.
- `short_when` that is present and not empty is refused: "the short side is not built yet in alpha test".
- A price level compared with a fixed number (`close > 400`), or with an unscaled indicator, is refused. The random-price test
  rebuilds prices from returns, so a fixed price level has no meaning there. A comparison with 0 is allowed (`macd` histogram).
- Example: "RSI(14) below 30 and close above the 200-day average" is two conditions in `long_when`.

## Labels

- `null-closes-for-high-low`: the rule reads high or low (`atr`, `hawkes`, `cmma`, a high or low source). The first random-price
  null has no intrabar range, so it uses closes for high and low. The engine runs and the other nulls use the real bars.

## Family

- The ledger family of an owner rule is `owner:<12 hex>` (so `spine:owner:<12 hex>` in the reader). The hex is a hash of the
  rule shape: no name, no history, every number a hole, `<` as `<=`, a constant on the right, conditions sorted.
- Thirty RSI thresholds are one family. A different structure is another family. The trial count for the deflated Sharpe is
  the larger of the family count and the count of all tests on the same asset.

## What it cannot say yet

- Exits and time stops ("hold until RSI is above 60, or 10 days at most"). The rule only holds while its conditions hold.
- Shorts in `alpha test`. Volume and open prices. Crossings ("crossed above"). Arithmetic on operands (`close > 1.02 * sma`).
- OR groups. Calendar. Other assets as inputs. Parameter variants in `alpha diagnose` (only the doubled-cost variant runs).
- Position sizing other than all-in.
