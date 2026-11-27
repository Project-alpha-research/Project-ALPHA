---
owner: command line application
sources:
  - apps/alpha-cli/src/alpha_cli/spine/**
---

# alpha-cli spine folder
## Purpose
The spine holds the pure maths and text behind a rule-test reading: the reading, the book, the honesty checks, the trial ledger and idea cards.

## Read first
| Read | Section | When |
|---|---|---|
| [research integrity](../../../../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | always |
| [command line runs](../../../../../docs/reference/invariants/cli-runs.md) | General rule trials | a change to the reading or the book |
| [one trial ledger](../../../../../docs/reference/invariants/cli-trial-ledger.md) | Rule-test counting | a change to `ledger`, `deflation` or the try count |
| [alpha-cli README](../../../README.md) | Code map | finding a module |

## How to change it
- Find a module: `uv run python scripts/fs.py map apps/alpha-cli --find WORDS`.
- Check: `uv run python scripts/gate.py check`.

## Outputs
- Tests in `tests/unit/` that share the module's name prefix.
