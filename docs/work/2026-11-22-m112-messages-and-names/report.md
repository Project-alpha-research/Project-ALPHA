# Report: m112 messages and names

Decisions are listed per item. Fail-first evidence: each test failed before its change.

- Trailer: the commit trailer follows the session attribution (Sonnet 5.5), not the brief's Fable 5.2 line, because the first names the real author.

## 1. Short asset names
`resolve_asset` (spine/stores.py) maps a short name to the one stored symbol with that first part. Otherwise the error lists the closest stored names and names `alpha data symbols`. Fail-first: 3 new tests in `tests/unit/test_spine_stores.py` failed before.
