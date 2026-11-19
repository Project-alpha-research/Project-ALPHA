---
owner: validation statistics
sources:
  - packages/alpha-validation/src/**
  - packages/alpha-validation/pyproject.toml
verified: c77d422704dbeb1c
---

# alpha-validation workspace

## Purpose

Engine-agnostic statistics that decide whether a backtest is believable: splits, nulls, Deflated Sharpe, PBO, path risk and verdicts.
It imports only `alpha_core`. Quant tier: every primitive needs an oracle.

## Read first

| Read | Section | When |
|---|---|---|
| [validation invariants](../../docs/reference/invariants/validation.md) | Splits and resampling | walk-forward, CPCV, purging, embargo or bootstrap |
| [validation invariants](../../docs/reference/invariants/validation.md) | — | a gate, null model, selection statistic, report or verdict |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Statistical evidence | always |
| [engineering rules](../../docs/reference/invariants/engineering.md) | Quant tier | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | changing splits, embargo or out-of-sample stitching |
| [command line runs](../../docs/reference/invariants/cli-runs.md) | Validation and optimisation | changing how a gate is composed or reported |
| [investigation tools](../../docs/reference/invariants/cli-investigation-tools.md) | — | changing attribution, regimes or change points |
| [four-family Monte Carlo guide](../../docs/operations/monte-carlo/README.md) | Read the outputs | changing or explaining a path-risk family |
| [what this part is for](../../docs/reference/project/components/validation-and-evidence.md) | — | why it exists; before you keep, shelve or remove it |
| [validation invariants](../../docs/reference/invariants/validation.md) | Code map | finding a module or its tests |

## How to change it

- Code, tests and checks: [code map](../../docs/reference/invariants/validation.md#code-map); run `uv run python scripts/gate.py check`.
- Compare floats with tolerances, never `==`: [oracles and tolerances](../../docs/reference/invariants/validation.md#oracles-and-tolerances).

## Outputs

- Tests: see the [code map](../../docs/reference/invariants/validation.md#code-map).
- The owning document: `docs/reference/invariants/validation.md`.
