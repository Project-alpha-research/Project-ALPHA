---
owner: delivery pipeline
sources:
  - .github/pull_request_template.md
  - scripts/handoff.py
  - scripts/status.py
verified: b54e1f508d77c80d
---

# Stage 05 — land: pull request to merged and closed

## Purpose

Get the verified branch merged through a green pull request whose description is the lasting record of the task.

## Inputs

- `docs/work/<task>/04-verify.md` with nothing open under `## Review findings`.

## Read first

| Read | Section | When |
|---|---|---|
| [engineering rules](../../../docs/reference/invariants/engineering.md) | Checks and commits | always |
| [documentation invariants](../../../docs/reference/invariants/documentation.md) | Generated files | always |
| [documentation invariants](../../../docs/reference/invariants/documentation.md) | Document lifecycle | closing the task |

## Process

1. Check "done" (below). Anything not met goes back to stage 03 or 04, or into the hand-off.
2. Write `05-handoff.md`, push the branch and open a **draft** pull request whose body is that file: `gh pr create --draft --body-file
   docs/work/<task>/05-handoff.md`. Then remove a planned task's folder in a last commit (`git rm -r docs/work/<task>`); a brief's `brief.md` and `report.md`
   stay.
3. CI on the pull request is the merge gate ([ADR-0039](../../../docs/adr/0039-ci-is-the-merge-gate.md)). Fix every failing job on the branch; mark the pull
   request ready only when CI is green. Review by another model goes on the pull request and is advisory.
4. The orchestrating session merges once `ci-ok` is green and the branch is up to date: `gh pr merge <n> --merge` (a merge commit, never squash or rebase).
   The owner delegated routine merging on 2026-11-14. It grants nothing else: research approvals, branch protection, required checks and credentials stay with
   the owner. When the change altered what a capability does, update its block in `docs/roadmap/capabilities.toml` on the branch.
   Do not regenerate `STATUS.md`, `docs/roadmap/README.md` or `docs/reference/commands.md` in a feature change: the sweep change does
   (`workflow/README.md`, step 6).
5. When CI failed twice or more for this work, add a short dated retrospective with a `## Watch-outs` section to `docs/operations/retrospectives/`.

## Outputs

`docs/work/<task>/05-handoff.md`, with the headings of `.github/pull_request_template.md`, in plain English: `## What changed for you`, `## How to see it`,
`## Checks run` (from `04-verify.md`, including what was not run), `## Who built and who reviewed` (from `03-build.json` — or, on the small route, the record
`handoff.py` printed — and `04-verify.md`: tool, model, effort, rounds, fallback, reviewers), `## The one document updated`, `## What I am unsure about`, `##
Protected files touched`.

Done means the list in [engineering § Checks and commits](../../../docs/reference/invariants/engineering.md#checks-and-commits).

## Checkpoint

The owner may read the pull request (it mirrors `05-handoff.md`) and ask for changes; the orchestrating session merges it once `ci-ok` is green (step 4).
After the merge, the pull request and git log are the task's history.
