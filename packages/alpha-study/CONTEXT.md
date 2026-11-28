---
owner: study projections
sources:
  - packages/alpha-study/src/**
  - packages/alpha-study/pyproject.toml
---

# alpha-study workspace

## Purpose

An additive research-plane seam: immutable feature, event and factor contracts, one operator registry and derived projections.
It owns no persistence, commands, approvals, evidence or trading authority.

## Read first

| Read | Section | When |
|---|---|---|
| [study invariants](../../docs/reference/invariants/study.md) | Package boundary | always |
| [study invariants](../../docs/reference/invariants/study.md) | Projection only | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Owner authority | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | always |
| [study invariants](../../docs/reference/invariants/study.md) | — | changing clocks, setup rules, operators or capabilities |
| [research invariants](../../docs/reference/invariants/research.md) | Phase allocation | the change touches D0 or D1 references |
| [command line research](../../docs/reference/invariants/cli-research.md) | Projections and dossiers | the change surfaces through `alpha research` |
| [what it is for (being removed)](../../docs/reference/project/components/research-cases-and-approval.md) | — | before you keep, shelve or remove it |
| [study invariants](../../docs/reference/invariants/study.md) | Code map | finding a module or its tests |

## How to change it

- Code, tests and checks: [code map](../../docs/reference/invariants/study.md#code-map); run `uv run python scripts/gate.py check`.

## Outputs

- Tests: see the [code map](../../docs/reference/invariants/study.md#code-map).
- The owning document: `docs/reference/invariants/study.md`.
