---
owner: delivery pipeline
sources:
  - scripts/handoff_routing.py
verified: 67c86f235104b502
---

# Task folders: what each build was asked and what it did

## Purpose

One folder per build, `docs/work/<yyyy-mm-dd>-<slug>/`, written by `scripts/handoff.py build` on the
build's branch and merged with the work. These are outputs (the paper's Layer 4), not reference
documents: they carry no front matter, no line limit and are never re-verified.

- `brief.md`: what was asked and what was already decided, as the builder received it. Edit it
  before a relaunch; the next build reads the edited file.
- `report.md`: the builder's final report: what it changed, which checks it ran, what is
  unverified, deviations and open questions. Home paths and model names are removed.
- A planned task (`02-plan.md`, the [delivery pipeline](../../workflow/CONTEXT.md)) keeps its stage
  files here too; the build adds its `report.md` beside them.

The pull-request description links both files.

## Read first

| Read | Section | When |
|---|---|---|
| [delivery pipeline](../../workflow/CONTEXT.md) | — | before writing a brief or a plan |
| [model routing](../reference/model-routing.md) | — | choosing the build class and the reviewer |

## How to change it

- Write a brief outside the repository, then run `uv run python scripts/handoff.py build --brief <file>`;
  the tool copies it here. To relaunch, edit this copy and build from it.
- Landing, the required check and who merges: [from an idea to a merged change](../../workflow/CONTEXT.md#from-an-idea-to-a-merged-change).
- Never put logs, token counts, model names or machine paths in these files.

## Outputs

- The two files above, committed on the branch with the work.
