---
owner: data layer
sources:
  - packages/alpha-data/src/alpha_data/context/**
  - apps/alpha-cli/src/alpha_cli/context_cmds.py
  - apps/alpha-cli/src/alpha_cli/context_sources_cmds.py
verified: 72dd83d10ce8ebab
---

# Data layer invariants: context data

Rules and facts for context data in `alpha_data`: macro series, SEC filings and crypto derivatives. They explain
research results and never enter the bar store, snapshots or backtest inputs. The rest of the data layer is in
[data.md](data.md).

## Treasury, VIX and FRED macro series

Daily market series such as Treasury yields and the VIX have no revision history at FRED; each value is stored as
known from the day after its date and the series is marked `approximate`.

FRED/ALFRED macro series retain values as first published and every returned revision, with publication dates and
hashed provenance in `data_dir/context/fred/`: reference data for explaining research results, kept apart from the bar
store, snapshots and backtest inputs. `alpha context` pulls, lists and reads it. The default read takes publications
with `known_from <= cutoff` and no `known_until` or `known_until >= cutoff` (both ends inclusive). An observation with
no valid vintage is absent; a valid vintage with a missing value stays null and never falls back to an earlier value,
while an expired newest observation can leave an earlier still-valid one to carry. Explicit first-release and latest
views keep their historical and null-ended-only policies. Window endpoints carry the last observation knowable at each
boundary, capped by `--as-of`; window extrema use observation dates inside the window at that cutoff. The key comes
only from `FRED_API_KEY`; provider copyright restrictions are recorded in provenance. Live API behavior remains
unconfirmed. HTTP 400 on the full real-time range retries the same range in windows: one before 1920, five-year
buckets, and a final bucket ending 9999-12-31, for any cutoff year and without constructing year 10000. The schedule
follows the UTC date of the explicit aware-UTC `fetched_at` the CLI supplies, validated before transport or writes.
Identical vintage rows merge; conflicting or overlapping rows fail, comparing adjacent sorted rows of one series and
observation: an open-ended predecessor or a shared boundary is rejected, gaps remain valid. The generic launcher
classifies only `context list`, `show`, `window`, `show-edgar`, `show-binance` and `show-bybit` as safe local reads;
bare, unknown and `pull*` commands remain owner-only. The group appears under the Data menu.

## SEC EDGAR filings

SEC EDGAR filings and Form 4 insider transactions live under `context/edgar/`. A filing is known from its acceptance
time plus a 5-hour margin, because SEC's documentation does not say whether `acceptanceDateTime` is UTC or US Eastern:
the margin shows a filing late, never early (remove it once a live check confirms UTC). Rows with no readable
acceptance time are counted as rejected; an amendment keeps its own rows and clock. Earnings dates are the 8-K item
2.02 view. `ALPHA_SEC_USER_AGENT` (name and e-mail, as the SEC asks) is required and never stored or printed; requests
are 0.2 s apart and filing documents are cached. Live SEC check not yet run; Form 4 XML field names were checked
against SEC's ownership XML specification only.

## Binance and Bybit derivatives context

Binance USD-M funding (monthly files) and daily metrics (open interest, long/short ratios) live under
`context/binance/um/`, each ZIP checked against its `.CHECKSUM`. Funding is known at settlement, metrics five minutes
after their stamp. A changed stored value fails; missing periods are listed. File formats were checked live on
2026-11-16 (BTCUSDT). Reads show only rows known by an aware UTC cutoff; there is no "latest" view. Bybit linear
funding and hourly open interest are imported offline (`alpha context import-bybit --from <store>`) into
`context/bybit/linear/`, checksum-verified; funding is known at settlement, open interest 1 h 5 min after its hour
starts. First import 2026-11-17: 50 + 51 symbols, 2022-2026.
