---
owner: command line application
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/**
---

# alpha-cli toolbox folder
## Purpose
The toolbox runs `alpha tool`: the registry of checks, their inputs, gates and stored results.

## Read first
| Read | Section | When |
|---|---|---|
| [command line toolbox](../../../../../docs/reference/invariants/cli-toolbox.md) | Honesty rules | always |
| [command line toolbox](../../../../../docs/reference/invariants/cli-toolbox.md) | Adding a check | adding or changing a check |
| [toolbox](../../../../../docs/reference/project/components/toolbox.md) | — | why it exists; what is not built yet |
| [alpha-cli README](../../../README.md) | Code map | finding a module |

## How to change it
- A new check: follow [Adding a check](../../../../../docs/reference/invariants/cli-toolbox.md#adding-a-check).
- Check: `uv run python scripts/gate.py check`.

## Outputs
- Tests in `tests/unit/` that share the module's name prefix; the row in `registry.py`.
