# Report: remove the crypto extras (m94)

Branch `chore/m94-remove-crypto-extras`. Deletion-only build. Fail-first evidence does not apply: no new behaviour.
Proof that each part was unreached: grep over `apps`, `packages`, `workers`, `tests`, `scripts`, `docs`, run before each delete.
`grep -il neurotrader` found no hit in any deleted file. Nothing from neurotrader888 was touched.

## Removed

Commands (15, all under `alpha crypto-data`): `compare`, `snapshot-query`, `yield-pools`, `profile-create`, `profile-show`, `profiles`,
`profile-run`, `profile-resume`, `profile-batches`, `profile-select-one-minute`, `liquidity-freeze`, `snapshot-verify-crowding`,
`snapshot-verify-hedged-basis`, `asset`, `asset-contract`.

Web routes (11): `GET /yield-pools`; `GET` and `POST /profiles`; `GET /profiles/{id}`; `POST /profiles/{id}/batches`; `GET /batches`;
`POST /batches/{id}/resume`; `POST /profiles/{id}/liquidity-membership`; `POST /profiles/{id}/one-minute-selection`; `GET /assets/{symbol}`;
`GET /assets/contracts/{network}/{address}`. Their 18 request and response models are gone. OpenAPI file, `generated.ts` and the operation
classification are regenerated.

Files deleted: `alpha_cli/crypto_snapshot_query.py`, `alpha_cli/_crypto_yield_catalog.py`; tests `test_crypto_snapshot_query.py` (unit and CLI),
`test_crypto_yield_catalog.py`, `test_crypto_comparison.py`.

Code deleted: `compare_market_observations` and `MarketComparisonSummaryV1` (`alpha_data/crypto/quality.py`); `comparison_frame`
(`_crypto_analysis.py`); the profile, liquidity, batch and crowding/basis verify helpers in `crypto_data_cmds.py` (4,704 to 3,536 lines).

Workstation: the "Default coverage profile" card, the liquidity and one-minute cards, the asset lookup and contract resolver in Assets &
Contracts, the yield-pool search, and the "Reviewed crypto assets" block in Data Manager. Matching client calls, types and e2e mocks.
Tests: the profile, liquidity, batch, asset-lookup and compare tests, cut by function. Docs: `commands.md`, ARCHITECTURE,
research-platform-contracts, cli-crypto-data, capability rows. ADR-0032 and ADR-0036 each got one "Removed 2026-11-22" line.

Lines: 9,883 removed, 1,321 added over 40 files. Most added lines are regenerated `openapi.json` (+1,293 / -3,049 is mostly reformat of the
removed schemas). Hand-written additions are about 20 lines.

## Kept, with reason

- `acquire`, `backfill`, `backfill-status`, `coverage`, `quality`, `snapshot-create`, `snapshot-verify`, `crypto_price_snapshot_query.py`: owner decision.
- `alpha_data/crypto/features.py` and the `feature-*` commands: cites neurotrader888.
- `asset-master-create`, `asset-master-verify`, `asset-masters` and their routes and Assets view: `snapshot-create` and `snapshot-verify` read
  custom asset masters. Removing them would narrow a kept command.
- DefiLlama, GeckoTerminal and CoinMetrics provider modules and their `acquire` fetchers: the provider names are closed enums in
  `contracts.py` and `storage.py`, and `providers.py` and `provider_readiness.py` list them. Removing them means changing stored-data
  identity. Stopped here as uncertain.
- `crypto_data_cmds` crowding and hedged-basis helpers: see blocked.

## Blocked by a protected file

- `alpha_data/crypto/profiles.py`: imported by `tests/bias_guards/test_crypto_profiles_future_poison.py`; also by `_crypto_coverage.py` (`coverage`, kept).
- `alpha_data/crypto/quality.py` (rest), `features.py` and the DefiLlama module: imported by `tests/bias_guards/test_defillama_availability.py`
  and `test_crypto_features_future_poison.py`.
- Crowding and hedged-basis research code (`research_crypto_*`, `strategy_candidate_*`, `crypto_crowding_*`, `alpha_strategies/hedged_basis.py`,
  `crypto_data_cmds.crypto_crowding_*` and `crypto_hedged_basis_*`): `tests/bias_guards/test_crypto_crowding_future_poison.py` imports
  `research_crypto_data`; `alpha-research/src` is protected. Only the two verify commands were removed.
- Not touched, protected: `apps/alpha-mcp` (`front_door_tools.py` mentions crypto; no removed command is named there).

## Not done

- The four crypto windows stay: Acquisition, Assets, Coverage and Quality views still serve kept commands. Only their removed parts went.
- The `compare` tool in the toolbox (`research_compare.py`, `ml_compare.py`): not crypto code; compares runs. Left alone.

## Code-size test (left red on purpose)

`tests/unit/test_code_size.py` is the one red test. CI names the baseline changes, in `.claude/code-size-baseline.json`:
- lower `files` entry `apps/alpha-cli/src/alpha_cli/crypto_data_cmds.py` from 4704 to 3536;
- remove function entry `apps/alpha-cli/src/alpha_cli/crypto_data_cmds.py::_freeze_binance_liquidity` (156).

## Decisions

- Commit trailer: the harness gave exact attribution lines for this session. They override the model name in the common rules.
- Not run: `fs.py verify` (common rules forbid it), live-provider tests (no network here). Playwright e2e ran after CI found one stale route list; 194 of 195 pass or ran. `tsc -b`, `oxlint` and 874 vitest tests pass.
- Smoke tests need `scripts/run_owned_test.py` on Linux; they were not run through it.
