# Report: m112 messages and names

Decisions are listed per item. Fail-first evidence: each test failed before its change.

- Trailer: the commit trailer follows the session attribution (Sonnet 5.5), not the brief's Fable 5.2 line, because the first names the real author.

## 1. Short asset names
`resolve_asset` (spine/stores.py) maps a short name to the one stored symbol with that first part. Otherwise the error lists the closest stored names and names `alpha data symbols`. Fail-first: 3 new tests in `tests/unit/test_spine_stores.py` failed before.

## 2. Crypto default costs
The #393 mechanism (spec without costs = `class-default`, class from `cost_classes.asset_class`) already gives a slash symbol or crypto provider the crypto row (10+5 bps). A test pins this (`test_cost_classes_crypto_default.py`); it passed before any change, so the tester ran an older build.
The gap found: a dash-quoted crypto ticker from a stock-data vendor (BTC-USD) was "not known". With class-default costs it is now crypto spot, by symbol, like the ETF rule. Fail-first: the ticker test failed before. Not changed: stated costs.

## 3. Screen on one asset
`_hypothesis_scan._need_assets` says "A screen needs at least N assets to compare, and you gave M" before any data is read (symbols and universe). The research package message is not touched (protected). `scan hypotheses --help` lists all signal names. `replay` was already shown in `alpha scan --help`; a test pins it. Fail-first: both tests in `test_scan_plain_messages.py` failed before.
