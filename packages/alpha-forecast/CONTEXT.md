---
owner: forecasting model
sources:
  - packages/alpha-forecast/src/**
  - packages/alpha-forecast/pyproject.toml
---

# alpha-forecast workspace

## Purpose

The facade around the Kronos foundation model: pinned vendored code, a typed `Forecaster` protocol and an offline `FakeForecaster`.
It imports only `alpha_core`; importing it never imports torch.

## Read first

| Read | Section | When |
|---|---|---|
| [forecast invariants](../../docs/reference/invariants/forecast.md) | Package boundary | always |
| [forecast invariants](../../docs/reference/invariants/forecast.md) | Sampling contract | always |
| [forecast invariants](../../docs/reference/invariants/forecast.md) | Settings and leakage | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Models and isolated workers | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | always |
| [forecast invariants](../../docs/reference/invariants/forecast.md) | — | changing the vendored model, values, signal or fake |
| [command line machine learning](../../docs/reference/invariants/cli-ml.md) | Kronos forecasts | changing how the CLI runs or caches forecasts |
| [engineering rules](../../docs/reference/invariants/engineering.md) | Polars by default | touching the pandas edge in `kronos.py` |
| [what this part is for](../../docs/reference/project/components/forecasting.md) | — | why it exists; before you keep, shelve or remove it |
| [forecast invariants](../../docs/reference/invariants/forecast.md) | Code map | finding a module or its tests |

## How to change it

- Code, tests and checks: [code map](../../docs/reference/invariants/forecast.md#code-map); run `uv run python scripts/gate.py check`.
- Tests use `FakeForecaster`; nothing downloads weights: [fake forecaster](../../docs/reference/invariants/forecast.md#fake-forecaster).

## Outputs

- Tests: see the [code map](../../docs/reference/invariants/forecast.md#code-map).
- The owning document: `docs/reference/invariants/forecast.md`.
