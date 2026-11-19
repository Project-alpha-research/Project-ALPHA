---
owner: model context protocol server
sources:
  - apps/alpha-mcp/src/**
  - apps/alpha-mcp/pyproject.toml
verified: dbd165a561b534ae
---

# alpha-mcp workspace

## Purpose

A stdio MCP server that lets an AI client call bounded `alpha` commands, by running the CLI as a subprocess.
It can never approve or decide research, consume D2 confirmation, reveal a holdout or place orders.

## Read first

| Read | Section | When |
|---|---|---|
| [MCP invariants](../../docs/reference/invariants/mcp.md) | What the server is | always |
| [MCP invariants](../../docs/reference/invariants/mcp.md) | Authority | always |
| [engineering rules](../../docs/reference/invariants/engineering.md) | Subprocess boundary | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Owner authority | always |
| [MCP invariants](../../docs/reference/invariants/mcp.md) | — | changing a tool, its inputs, imports or CLI calls |
| [command reference](../../docs/reference/commands.md) | — | finding the command a tool wraps |
| [what this part is for](../../docs/reference/project/components/ai-assistants.md) | — | why it exists; before you keep, shelve or remove it |
| [MCP invariants](../../docs/reference/invariants/mcp.md) | Code map | finding a module or its tests |

## How to change it

- Code, tests and checks: [code map](../../docs/reference/invariants/mcp.md#code-map); run `uv run python scripts/gate.py check`.
- Adding or removing a tool: [changing the tool set](../../docs/reference/invariants/mcp.md#changing-the-tool-set).

## Outputs

- Tests: see the [code map](../../docs/reference/invariants/mcp.md#code-map).
- The owning document: `docs/reference/invariants/mcp.md`; regenerated
  `docs/governance/capability-authority-matrix.md`.
