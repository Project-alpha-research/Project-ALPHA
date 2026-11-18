---
owner: research primitives
sources:
  - packages/alpha-research/src/**
  - packages/alpha-research/pyproject.toml
verified: a6e89f5ba34a6607
---

# alpha-research workspace

## Purpose

Pure, deterministic research primitives: bars, the D0 to D3 phase split, event studies, multiplicity control and gate packets.
It imports only `alpha_core`; it has no network, persistence or authority.

## Read first

| Read | Section | When |
|---|---|---|
| [research invariants](../../docs/reference/invariants/research.md) | Package boundary | always |
| [engineering rules](../../docs/reference/invariants/engineering.md) | Hash-bound source bytes | always |
| [engineering rules](../../docs/reference/invariants/engineering.md) | Quant tier | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Research before strategy | always |
| [research invariants](../../docs/reference/invariants/research.md) | — | changing packets, phases, studies, bars or figures |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | changing event studies, bars or phase boundaries |
| [command line research](../../docs/reference/invariants/cli-research.md) | Projections and dossiers | a gate packet is assembled or shown differently |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Statistical evidence | changing a statistic |
| [what this part is for](../../docs/reference/project/components/research-cases-and-approval.md) | — | why it exists; before you keep, shelve or remove it |
| [research invariants](../../docs/reference/invariants/research.md) | Code map | finding a module or its tests |

## How to change it

- Code, tests and checks: [code map](../../docs/reference/invariants/research.md#code-map); run `uv run python scripts/gate.py check`.
- Stop first: every `.py` byte feeds the implementation hash: [package boundary](../../docs/reference/invariants/research.md#package-boundary).
- A visible figure change needs a `RENDERER_VERSION` bump: [figures and charts](../../docs/reference/invariants/research.md#figures-and-charts).

## Outputs

- Tests: see the [code map](../../docs/reference/invariants/research.md#code-map).
- The owning document: `docs/reference/invariants/research.md`.
