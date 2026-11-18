---
owner: delivery pipeline
sources:
  - workflow/stages/*/CONTEXT.md
  - scripts/roadmap_index.py
  - scripts/handoff.py
  - tests/unit/test_filesystem_contract.py
verified: d5db60fa476b54ce
---

# Delivery pipeline — how a change gets made

## Purpose

A planned change to ALPHA walks five stages, in order; the small route skips the stage files. Each stage reads the previous stage's file, does one job,
leaves one plain file the owner can read and edit, and stops at a checkpoint. Pick your stage from the table, open its `CONTEXT.md` and follow it.

| Stage | Takes in | Leaves behind | Command |
|---|---|---|---|
| [01 shape](stages/01-shape/CONTEXT.md) | the owner's idea, in their words | `01-brief.md`, or a backlog file | `/shape` |
| [02 plan](stages/02-plan/CONTEXT.md) | `01-brief.md` | `02-plan.md` | `/plan` |
| [03 build](stages/03-build/CONTEXT.md) | `02-plan.md` | commits on a branch | `/build` |
| [04 verify](stages/04-verify/CONTEXT.md) | the branch and `02-plan.md` | `04-verify.md` | `/verify` |
| [05 land](stages/05-land/CONTEXT.md) | `04-verify.md` | `05-handoff.md`, a pull request | `/land` |

Which stage am I in? No task folder yet: 01. A brief but no plan: 02. A plan whose slices are not
all `done`: 03. Slices done but no `04-verify.md`: 04. Otherwise: 05.

How do I land a change? See [From an idea to a merged change](#from-an-idea-to-a-merged-change) below.

## From an idea to a merged change

The whole path in one place. Other pages link here and do not repeat it.

1. **Who builds.** Claude plans, decides, reviews, commits and opens the pull request. Codex builds (`gpt-6.2-sol` for small and standard work, `gpt-6.2-astra`
   for hard) in a sandboxed worktree with the network off; it never commits. A Claude sub-agent builds only on a fallback (exit 10 to 13) or when the work
   needs the network or a decision ([model routing](../docs/reference/model-routing.md)).
2. **The brief.** Write it outside the repository with the headings Task, Decision already made, Files, Do not touch, Checks, Report. Hand it over with
   `uv run python scripts/handoff.py build --brief <file>`, outside any sandbox. A planned task uses `--task docs/work/<task>/` instead. The tool drives
   up to two fix rounds, then you review (stage 04).
3. **Where the files land.** `brief.md` and the builder's `report.md` go to `docs/work/<yyyy-mm-dd>-<slug>/`, merge with the work and are linked from the pull
   request. The JSON build record stays outside the repository, in the handoff folder ([task folders](../docs/work/CONTEXT.md)).
4. **Checks.** Locally: `uv run python scripts/gate.py check`. On the pull request the one required check is `ci-ok`. Open the pull request as a draft.
5. **Who merges.** The orchestrating session merges once `ci-ok` is green and the branch is current: `gh pr merge <n> --merge` (a merge commit). The owner keeps
   branch-protection changes ([stage 05](stages/05-land/CONTEXT.md)).
6. **Marking a document re-read.** `uv run python scripts/fs.py stale` lists documents whose sources changed; `fs.py owners <path>` names those describing a
   file. Re-read each, fix it, then run `fs.py verify <doc>`. If it needed no fix, `fs.py verify <doc> --reason "<why still correct>"` (at least three words;
   kept in `docs/verified-reasons.txt`). The gate fails while any document is stale.

## Read first

| Read | Section | When |
|---|---|---|
| [documentation invariants](../docs/reference/invariants/documentation.md) | Feature plans | always |
| [engineering rules](../docs/reference/invariants/engineering.md) | Working style | always |
| [research integrity](../docs/reference/invariants/research-integrity.md) | — | the change touches data, strategies, statistics or owner actions |
| [what this part is for](../docs/reference/project/components/delivery-and-agent-tooling.md) | — | why it exists; before you keep, shelve or remove it |

## The task folder

- A build from a brief leaves `brief.md` and `report.md` in `docs/work/<yyyy-mm-dd>-<slug>/` (step 3 above). Read a stage file's other `docs/work/<task>/`
  paths as the optional route.
- The optional route: one folder per planned task, on its branch while the pull request is open (stage 05 removes it), holding `01-brief.md`, `02-plan.md`,
  `03-build.json`, `04-verify.md` and `05-handoff.md`; one is committed only with a `02-plan.md`. The owner may edit any stage file between stages.
- The small route skips the folder: a fix in one module with an obvious test, or a documentation-only change. It runs stages 03 to 05 on a branch from a
  short brief and the area's `CONTEXT.md`; 04's results go under `## Checks run` in the pull request; 05 fills the template directly.

## How to change it

- Each stage file follows the shape checked by `tests/unit/test_filesystem_contract.py`:
  Purpose, Inputs, Read first, Process, Outputs, Checkpoint; at most 80 lines.
- A rule a stage needs belongs in a reference file (`docs/reference/`); the stage links it.
- Agents (`.claude/agents/`) and commands (`.claude/commands/`) are entry points into these
  stages and hold no rules of their own.

## Outputs

- The stage files of each task on its branch, and the pull request (the lasting record).
- The owning document for the plan and roadmap rules: `docs/reference/invariants/documentation.md`.
