---
owner: command line application
sources:
  - apps/alpha-cli/src/alpha_cli/figures/**
---

# alpha-cli figures folder
## Purpose
The figures folder reads immutable run artifacts and builds the figure specs and answer sentences; `alpha_research.figures` draws them.

## Read first
| Read | Section | When |
|---|---|---|
| [command line figures](../../../../../docs/reference/invariants/cli-figures.md) | Figures | always |
| [command line runs](../../../../../docs/reference/invariants/cli-runs.md) | Figures | a figure for a run |
| [alpha-cli README](../../../README.md) | Code map | finding a module |

## How to change it
- A new figure: add a `builders_*.py` module and register it in `_builders.py`.
- Check: `uv run python scripts/gate.py check`.

## Outputs
- Tests in `tests/unit/` that share the module's name prefix.
