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
verified: 0000000000000000
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

## Other readers of the table

- The RD-Agent factor judge (`_rdagent_costs.py`) reads the crypto spot row at each call. It keeps no cost numbers of its own, so a
  change of the row reaches its next score.
- The native daily rule study (`_native_daily_rule_study.py`) states 10 bp fee and 5 bp slippage itself: the file is hash-bound for
  daily approvals and may not import the unbound table. A unit test holds its terms equal to the crypto spot row.
- A judge trial stores `costs` (`fee_bps`, `slippage_bps`, `source: class-default`, `asset_class`). A stored trial keeps the costs it was
  made with and is never rewritten; one without `costs` was made before the table (10 bp fee, 6 bp slippage). The judge feedback says how
  many earlier trials used other costs: they stay in the trial count and are not re-scored.
- Not on the table: `research_cmds.py` (old research-case lane, flat 1 and 2 bp) and the judge's worker prompt text in `workers/rdagent`.

## Rules

- The class comes from the store's dataset identity (`asset_class` and `venue`): US `etf` is the large ETF row, US `stock` the stock row,
  `crypto` the spot row. Without an identity, a slash pair or a crypto provider is crypto spot, and a broad US index fund named in
  `cost_classes.US_LARGE_ETFS` (SPY, QQQ, IWM, DIA, VOO, IVV, VTI) is the large ETF row; a yfinance store records no class.
  A perpetual cannot be told from spot in the record, so no asset maps to it today.
- A class that is not known takes the most cautious row (highest cost of one side: crypto spot) and the run is labelled `cost-class-assumed`.
- A spec that states its costs keeps them. Its hash, test key and numbers are as before (`tests/unit/test_cost_classes_pins.py`).
- A spec without costs asks for the class row, as `costs = "class-default"` does (owner decision, 2026-11-22). The spec dumps
  `mode = "class-default"`, so it has its own hash; every stored run states its costs and keeps its hash. The run is labelled
  `class-default-costs`, and stores the numbers it used in `spine.costs`. `alpha follow` of such a test uses those stored numbers.
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
