# Local Daily Data and Paper Operations

Other runbooks in this directory: [`owner-actions-checklist.md`](owner-actions-checklist.md)
(every credential, approval and opt-in that needs the owner's own hands) and
[`codex-second-model-runbook.md`](codex-second-model-runbook.md) (the optional Codex login).
To back up the data home and prove a restore, see [`data-home-backup.md`](data-home-backup.md).
For purposes, assumptions and interpretation of all four required path-risk families, see
[Four-family Monte Carlo](monte-carlo/README.md).

This runbook is for the single-operator local deployment. Do not commit `.env`, Tiingo
credentials, account identifiers, Docker secrets, generated journals, or copied market data.

The supplied Tiingo token and CoinGecko Demo key are stored in the
macOS keychain services `project-alpha-tiingo` and `project-alpha-coingecko` (the former QuantPad item, `project-alpha-quantpad`, is unused).
Repository files contain only those service names. The local `.env` is git-ignored and mode `0600`; it must not receive vendor or
broker secrets.

For CoinGecko, run exactly one bounded authenticated readiness check with:

```bash
scripts/alpha-with-keychain-provider coingecko check
```

The launcher injects `ALPHA_COINGECKO_API_KEY` into only that replacement process. CoinGecko market
reference, GeckoTerminal pool data, and Coin Metrics network data remain separate families;
CoinGecko verification does not qualify any downloaded dataset.

Acquire and mechanically qualify the bounded CoinGecko contract catalog through a separate fixed
launcher action:

```bash
scripts/alpha-with-keychain-provider coingecko catalog
```

Acquire the broad USD market-reference universe through its own fixed action:

```bash
scripts/alpha-with-keychain-provider coingecko reference
```

Neither action accepts arbitrary provider, family, instrument, or output arguments. Each freezes
the exact paginated responses and qualification receipt; the key remains process-local and is
absent from request receipts, manifests, logs, and command arguments. The reference universe is
supplemental research context and cannot satisfy venue-price, validation-price, or execution-price
requirements.

## 1. QuantPad (removed 2026-11-14)

The owner no longer uses QuantPad. Its command (`alpha quantpad-data`), adapter, archive code and
launcher action were removed on 2026-11-14
([ADR-0018 note](../adr/0018-quantpad-external-research-data-boundary.md#owner-supersession--2026-11-14)).
Research datasets already registered from a QuantPad receipt stay readable. Archived QuantPad bytes
and manifests already on disk are plain files; nothing in ALPHA reads or rewrites them any more.
The `project-alpha-quantpad` keychain item is no longer used; deleting it is the owner's choice.

## 2. Configure daily Tiingo work

Set `ALPHA_TIINGO_API_KEY` through the OS keychain service `project-alpha-tiingo`. Add or update the key
manually with macOS `security`, without committing the command or its value to a repository file.

Check the source status first:

```bash
uv run alpha data source-status SPY --json
```

Inspect any quarantined receipt with `alpha data audit PROVIDER RECEIPT_ID`. Promote it only after
review with `alpha data repair PROVIDER RECEIPT_ID --approve-differences`. If promotion itself was
interrupted, restore the exact pre-promotion bytes with
`alpha data rollback-promotion SYMBOL --acknowledge`. These are distinct recovery operations.

The Readiness Center and `alpha info providers --json` are local projections and never probe a
provider. `scripts/alpha-with-keychain-provider tiingo check` performs one bounded SPY
authentication/schema check and stores a redacted `ProviderCheckReceiptV1`. That receipt does not
qualify data: ingestion, audit, and promotion remain separate steps.

## 3. Dell mini deployment candidate

An i5/16-GB Dell mini is sufficient for light ingestion and monitoring. It is not yet an approved host and should not hold
the only canonical dataset or a large L2 archive. Before moving any process, record its exact CPU,
storage, Linux distribution, disk encryption, LAN address, SSH-key policy, backup target, Docker
version, time synchronization, and unattended-restart behavior. Keep the Mac as the development and
recovery authority until a separate multi-host operations/threat-model review is complete.
