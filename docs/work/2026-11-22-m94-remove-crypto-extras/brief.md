# Brief: remove the crypto extras; keep basic crypto data and everything from neurotrader888

Branch: `chore/m94-remove-crypto-extras`. Rules: `docs/work/_common-rules-2026-11-21.md` (deletion-only build). Extra rules for this build: the owner wants the project SMALLER
and SIMPLER: add no shim, no "moved" notice, no alias, no new option, no new guard. Do not copy other briefs or the common rules into your
branch; add only your own `report.md` in this task folder. NEVER delete anything that comes from neurotrader888: before deleting a file,
run `grep -il neurotrader <file>`; a hit means keep it and say so in the report (his material: `packages/alpha-patterns`,
`alpha_research/pip_miner.py`, `retracements.py`, `rolling_pca.py`, `alpha_validation/mcpt.py`, `bar_permutation.py`,
`trade_dependence.py`, `tests/fixtures/neurotrader/`, `alpha_data/crypto/features.py`). Report lines removed and added, and commands removed.

Decided by the owner on 2026-11-22. KEEP: crypto bar download and backfill (`acquire`, `backfill`, `backfill-status`), `coverage`,
`quality`, the snapshot query that the native daily rule study uses, crypto in `alpha test`/Setup Lab/follow/context data (COT for
BTC), and `packages/alpha-data/src/alpha_data/crypto/features.py` (it cites neurotrader888: do not delete or trim it).
REMOVE, only where your grep proves nothing kept reaches it: crypto profiles and asset masters, the crowding and hedged-basis checks
that serve the old research cases, the DefiLlama / GeckoTerminal / CoinMetrics sources, the `compare` tool, their commands (about 31),
web routes (about 32), the four crypto windows in the Workstation, tests, docs, ADR mentions (add one line "removed 2026-11-22" to an
ADR; do not delete ADRs) and capability rows. Protected and NOT to be edited: `tests/bias_guards/test_crypto_crowding_future_poison.py`
and `packages/alpha-research/src`: if a protected test or module still imports something you want to delete, KEEP that thing and list
it in the report as "blocked by a protected file". Work from the leaves inward and stop at anything uncertain: a smaller safe deletion
is better than a broken one. Do not touch `alpha_cli/research_crypto_data.py` loaders that `crypto_data_cmds` or kept tests read.

Done: pull request ready, `ci-ok` green except possibly the code-size test, `report.md` listing removed, kept (with reason), and blocked.
