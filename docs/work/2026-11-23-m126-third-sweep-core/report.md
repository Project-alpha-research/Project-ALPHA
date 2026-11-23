# Report: m126 third sweep, core path

Decision: the commit trailer names the model that did the work (Sonnet 5.5), not the line the common rules quote.

## 1. Symbol names
- Cause: `ledger tries` compared the typed name (BTC) with the stored name (BTC/USDT) as plain text.
- Change: `typed_symbol` (in `spine/stores.py`) calls `resolve_asset`, the resolver `alpha test` uses. `ledger tries`, `ledger list --asset` and `ledger query` use it and say "BTC is stored as BTC/USDT." A name that is not stored stays as typed.
- Test: `tests/unit/test_m126_symbol_names.py` (failed first: "0 ideas on BTC").
