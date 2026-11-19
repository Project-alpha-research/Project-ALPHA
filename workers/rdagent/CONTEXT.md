---
owner: rd-agent worker
sources:
  - workers/rdagent/*.py
  - workers/rdagent/pyproject.toml
  - workers/rdagent/uv.lock
verified: ce819bbea4d040e4
---

# RD-Agent worker workspace

## Purpose

Flat scripts and pinned locks that run Microsoft RD-Agent's native loops and the ALPHA-judged factor loop in their own environments.
No ALPHA package imports it. It has no market, inference or evidence authority.

## Read first

| Read | Section | When |
|---|---|---|
| [worker invariants](../../docs/reference/invariants/workers.md) | Shared rules | always |
| [RD-Agent invariants](../../docs/reference/invariants/rdagent.md) | Boundary and authority | always |
| [command line native](../../docs/reference/invariants/cli-native.md) | — | launching, approving or reading a native job; its claims |
| [RD-Agent invariants](../../docs/reference/invariants/rdagent.md) | — | changing install, gateway, loop, memory, panels or viewer |
| [what this part is for](../../docs/reference/project/components/rd-agent.md) | — | why it exists; before you keep, shelve or remove it |
| [worker README](README.md) | — | the file list, launching a loop |
| [change notes](CHANGE-NOTES.md) | — | the history of a rule or a dated fix-up |
| [RD-Agent invariants](../../docs/reference/invariants/rdagent.md) | Code map | finding a module or its tests |

## How to change it

- Code and tests: [code map](../../docs/reference/invariants/rdagent.md#code-map).
- Run `uv run python scripts/gate.py check` at the root. The worker has no CI gate component.
- Rule profiles rebuild when core, patterns or strategies change: [install and runtimes](../../docs/reference/invariants/rdagent.md#install-and-runtimes).
- Proposal pause and stand-in answers: [propose and discuss](propose-and-discuss.md). Funding, shortlist, thirds and ties: [judge rules](judge-rules.md).

## Outputs

- The owning document: `docs/reference/invariants/rdagent.md`. Identity split counts
  and write-offs reach proposer feedback; rescaling, reproducibility and family refusal rules: [change notes](CHANGE-NOTES.md#identity-breaks-across-a-gap).
