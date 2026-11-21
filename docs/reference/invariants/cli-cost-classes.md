---
owner: command line runs and validation
sources:
  - apps/alpha-cli/src/alpha_cli/spine/cost_classes.py
  - apps/alpha-cli/src/alpha_cli/spine/spec.py
  - apps/alpha-cli/src/alpha_cli/toolbox/families/costs.py
  - tests/unit/test_cost_classes.py
  - tests/unit/test_cost_classes_pins.py
  - tests/unit/test_cost_classes_recheck.py
  - apps/alpha-cli/src/alpha_cli/spine/recheck.py
  - apps/alpha-cli/src/alpha_cli/spine/recheck_compare.py
verified: 1feb169bd782f16b
---

# Command line cost classes invariants

Default costs and annualisation by asset class for rule tests. The one home of the numbers is `ROWS` in `spine/cost_classes.py`;
the table below is that text. Every number is a working assumption of the owner's lane, not a venue quote. Not verified.

## Table

Per side, in basis points (bp). Borrow is a yearly rate. Periods are daily bars a year.

| Class | Fee | Slippage | Borrow | Periods |
|---|---|---|---|---|
| US large ETF | 1 | 1 | 30 | 252 |
| US stock | 2 | 5 | 50 | 252 |
| Crypto spot (taker) | 10 | 5 | none: a spot position cannot be shorted | 365 |
| Crypto perpetual | 5 | 5 | 1095 (3 bp a day of funding times 365) | 365 |

Sources:
- US large ETF: fee is the old flat default; slippage is about half the spread of a liquid fund; borrow is an easy-to-borrow fund.
- US stock: fee is small-order regulatory and exchange fees; slippage is spread and impact of a mid-cap or small-cap;
  borrow is the setup lane (`SHORT_BORROW_BPS_PER_YEAR`).
- Crypto spot: the setup lane (`CRYPTO_FEE_BPS`, `CRYPTO_SLIPPAGE_BPS`).
- Crypto perpetual: fee is a common taker schedule; funding is the setup lane (`SHORT_CARRY_BPS_PER_DAY`).

## Rules

- The class comes from the store's dataset identity (`asset_class` and `venue`): US `etf` is the large ETF row, US `stock` the stock row,
  `crypto` the spot row. Without an identity, a slash pair or a crypto provider is crypto spot. Nothing else is read, never the ticker text.
  A perpetual cannot be told from spot in the record, so no asset maps to it today.
- A class that is not known takes the most cautious row (highest cost of one side: crypto spot) and the run is labelled `cost-class-assumed`.
- A spec that states its costs keeps them. Its hash, test key and numbers are as before (`tests/unit/test_cost_classes_pins.py`).
- "No costs stated" cannot be told from "the default stated": both dump `{"fee_bps":1.0,"slippage_bps":2.0}` and share one hash. So a
  spec without costs keeps the flat default of 1 and 2 basis points. Changing it would give old and new results one identity.
- `costs = "class-default"` in a spec asks for the class row. The spec dumps `mode = "class-default"`, so it has its own hash. The run
  is labelled `class-default-costs`, and stores the numbers it used in `spine.costs`. `alpha follow` refuses such a test.
- A recheck of a `class-default` run uses the fee and slippage stored in its `spine.costs`, never today's table: a later change of a
  row does not move a stored result. A recheck of a run stored before `spine.costs` existed compares it without the costs statements
  (`spine.costs`, `reading.costs`); its fee and slippage are still compared in the spec fields (`tests/unit/test_cost_classes_recheck.py`).
- Every new run stores `spine.costs` (`line`, `fee_bps`, `slippage_bps`, `asset_class`, `periods`) and the reading carries `costs`
  with the `line` and `periods` text. A run from before this change has `line: null` with a reason. `alpha report` prints the line.
- Periods per year: stays derived from the stored bars, snapped to 252 or 365 (`spine/stores.annualisation`, which reads the two
  constants from `cost_classes`). Stock runs are unchanged. The run states which number it used and, when the class is known, the rule.
- `costs.break_even` adds `result_after_borrow`, `borrow_charge` and `borrow_note` for a run with short trades: a plain sum of
  rate x entry value x days held / 365, at the class rate (the highest rate when the class is unknown). A long-only run has none of them,
  with a reason; the value is never zero. A run with short trades carries the label `short-borrow-not-charged`: the borrow is a fact
  beside the result, never taken from it (owner decision). The rule-test engine does not short, so this reads runs from the older lane.
