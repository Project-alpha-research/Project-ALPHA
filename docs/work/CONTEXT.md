---
owner: project layer
sources:
  - docs/reference/project/components/delivery-and-agent-tooling.md
verified: 98ff6f758bf06846
---

# Task folders: what each build was asked and what it did

## Purpose

One folder per build, `docs/work/<yyyy-mm-dd>-<slug>/`, merged with the work. It holds `brief.md` and `report.md`.
These are outputs, not reference documents. How the build team works: [the build team](../reference/project/components/delivery-and-agent-tooling.md).

## Read first

| Read | Section | When |
|---|---|---|
| [the build team](../reference/project/components/delivery-and-agent-tooling.md) | — | before writing a brief |

## How to change it

- Write `brief.md` before the build: the one outcome, the files, the checks. Keep it short.
- Never put logs, token counts, model names or machine paths in these files.

## Outputs

- `brief.md` and `report.md`, committed on the branch with the work.
