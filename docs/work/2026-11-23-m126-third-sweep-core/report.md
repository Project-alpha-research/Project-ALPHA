# Report: m126 third sweep, core path

Decision: the commit trailer names the model that did the work (Sonnet 5.5), not the line the common rules quote.

## 1. Symbol names
- Cause: `ledger tries` compared the typed name (BTC) with the stored name (BTC/USDT) as plain text.
- Change: `typed_symbol` (in `spine/stores.py`) calls `resolve_asset`, the resolver `alpha test` uses. `ledger tries`, `ledger list --asset` and `ledger query` use it and say "BTC is stored as BTC/USDT." A name that is not stored stays as typed.
- Test: `tests/unit/test_m126_symbol_names.py` (failed first: "0 ideas on BTC").

## 2. Labels (and 7b, compare table)
- Cause: only `alpha test` called `label_lines`; the other views printed the bare names.
- Change: `label_block` and `legend_line` (in `spine/label_meaning.py`) now serve `report`, `results show`, `results compare` (block) and `results` list (one legend line under the table).
- Test: `tests/unit/test_m126_labels_compare.py`.

## 7b. Compare table
- Cause: every run had value, diff and ratio columns, each headed with the run id.
- Change: each id prints once; the first run keeps only its value column (no 0.00 / 1.00x). Later runs add "change from first" and "ratio to first". Two old tests changed to match.
