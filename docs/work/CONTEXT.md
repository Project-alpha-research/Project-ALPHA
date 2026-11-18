---
owner: delivery pipeline
sources:
  - scripts/handoff_routing.py
verified: 67c86f235104b502
---

# Task folders: what each build was asked and what it did

## Purpose

One folder per build, `docs/work/<yyyy-mm-dd>-<slug>/`, written by `scripts/handoff.py build` and merged with the work.
It holds `brief.md` and `report.md`, and the stage files of a planned task. These are outputs, not reference documents.
What each file holds: [task folders](../../workflow/README.md#task-folders).

## Read first

| Read | Section | When |
|---|---|---|
| [delivery pipeline](../../workflow/CONTEXT.md) | — | before writing a brief or a plan |
| [model routing](../reference/model-routing.md) | — | choosing the build class and the reviewer |

## How to change it

- Write a brief outside the repository, then run `uv run python scripts/handoff.py build --brief <file>`;
  the tool copies it here. To relaunch, edit this copy and build from it.
- Landing, the required check and who merges: [from an idea to a merged change](../../workflow/README.md#from-an-idea-to-a-merged-change).
- Never put logs, token counts, model names or machine paths in these files.

## Outputs

- The two files in [task folders](../../workflow/README.md#task-folders), committed on the branch with the work.
