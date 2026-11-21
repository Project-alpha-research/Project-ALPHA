---
owner: data layer
sources:
  - packages/alpha-data/src/**
  - packages/alpha-data/pyproject.toml
verified: aaf83ee0c9560850
---

# alpha-data workspace

## Purpose

Data ingestion and storage: vendor adapters, the raw Parquet store, the point-in-time `as_of` reader, snapshots and the crypto data house.
A read must never see data that was not knowable at the cutoff.

## Read first

| Read | Section | When |
|---|---|---|
| [data invariants](../../docs/reference/invariants/data.md) | Package boundary | always |
| [data invariants](../../docs/reference/invariants/data.md) | Point-in-time store | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Invalid data fails loud | always |
| [data invariants](../../docs/reference/invariants/data.md) | — | changing readers, receipts, snapshots or adapters |
| [data crypto invariants](../../docs/reference/invariants/data-crypto.md) | — | changing crypto storage, identity or Bybit context |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | — | changing splits, dividends, snapshots or receipts |
| [bar timeframes](../../docs/reference/invariants/data-bar-timeframes.md) | — | changing bar timeframes, intraday stores or intraday quality |
| [what this part is for](../../docs/reference/project/components/data-layer.md) | — | why it exists; before you keep, shelve or remove it |
| [data invariants](../../docs/reference/invariants/data.md) | Code map | finding a module or its tests |

## How to change it

- Code, tests and checks: [code map](../../docs/reference/invariants/data.md#code-map); run `uv run python scripts/gate.py check`.
- A new read path needs a future-poison guard: [point-in-time store](../../docs/reference/invariants/data.md#point-in-time-store).

## Outputs

- Tests: see the [code map](../../docs/reference/invariants/data.md#code-map).
- The owning document: `docs/reference/invariants/data.md` (crypto providers:
  `docs/reference/invariants/crypto-providers.md`; crypto commands: `docs/reference/invariants/cli-crypto-data.md`).
