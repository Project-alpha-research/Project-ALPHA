---
owner: file system routing
sources:
  - "*/*/pyproject.toml"
---
# ALPHA: start here
## Purpose
Stop when you have what you need: the always rows, then only rows your task matches; then open code.
## Read first
| Read | Section | When |
|---|---|---|
| [project layer](docs/reference/project/overview.md) | — | what a part is for; owner decisions; reserved period |
| [alpha-core](packages/alpha-core/CONTEXT.md) | — | domain types, errors, settings |
| [alpha-data](packages/alpha-data/CONTEXT.md) | — | point-in-time store, snapshots, crypto |
| [alpha-patterns](packages/alpha-patterns/CONTEXT.md) | — | chart patterns, lookalikes |
| [alpha-strategies](packages/alpha-strategies/CONTEXT.md) | — | signals, sizing, rules |
| [alpha-backtest](packages/alpha-backtest/CONTEXT.md) | — | Nautilus backtests, fills, fees |
| [alpha-validation](packages/alpha-validation/CONTEXT.md) | — | walk-forward, nulls, Deflated Sharpe |
| [alpha-research](packages/alpha-research/CONTEXT.md) | — | phases, event studies, gates |
| [alpha-forecast](packages/alpha-forecast/CONTEXT.md) | — | the Kronos model |
| [alpha-study](packages/alpha-study/CONTEXT.md) | — | study projections |
| [alpha-cli](apps/alpha-cli/CONTEXT.md) | — | any `alpha` command, report or job |
| [alpha-web](apps/alpha-web/CONTEXT.md) | — | Workstation API or browser panels |
| [alpha-mcp](apps/alpha-mcp/CONTEXT.md) | — | the MCP server's tools |
| [qlib](workers/qlib/CONTEXT.md) | — | the Qlib worker |
| [literature](workers/literature/CONTEXT.md) | — | the literature worker |
| [rdagent](workers/rdagent/CONTEXT.md) | — | the RD-Agent worker |
| [afml](workers/afml/CONTEXT.md) | — | AFML labels, sample weights |
| [scripts](scripts/CONTEXT.md) | — | gate, CI steps, fs tools |
| [tests](tests/CONTEXT.md) | — | tests, markers, guards, oracles |
| [docs](docs/CONTEXT.md) | — | docs, ADRs, file system |
| [research](research/CONTEXT.md) | — | testing an idea (`research/PLAYBOOK.md`) |
## How to change it
Add a row per new workspace.
## Outputs
None of its own.
