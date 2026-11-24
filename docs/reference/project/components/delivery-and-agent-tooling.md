---
owner: project layer
sources:
  - factory.toml
  - scripts/gate.py
  - .github/workflows/ci.yml
  - .github/workflows/release.yml
  - scripts/update.sh
verified: fc78b5602ae6b5e3
---

# The build team

The build team replaces the Software Team (October 2026) and the five-stage delivery pipeline (November 2026). Both are retired; their history is in git.

## Why it exists

The owner is not a coder. A third of merged changes had been repairs, and `main` was red six times in one day. Prose rules did not hold. Code now holds them
([decision](../owner-decisions-6.md#2026-11-24-the-build-team-replaces-the-software-team-and-the-delivery-pipeline),
[ADR-0056](../../../adr/0056-the-build-team-replaces-the-delivery-pipeline.md)).

## Its job in the research loop

None directly. It protects the loop: the gate, the guards and the oracles stop a change that would break point-in-time reads or the try count.

## Intended design

The build team lives in a separate private repository, `alpha-factory`. The product never imports it. The line, in order:

1. Work order: one outcome, written down.
2. The acceptance check is written first and locked.
3. Code builds the context pack.
4. One writer builds in a sealed copy.
5. Code runs the gate.
6. A reviewer reads the change in a fresh context.
7. The merge queue runs the full suite on the commit that will land.
8. A tagged release is cut.
9. `alpha home update` installs it, checks it and returns to the last good version by itself.

| Role | Job |
|---|---|
| Planner | Turns the owner's wish into work orders. |
| Spec writer | Writes the acceptance check first. |
| Builder | Writes the change in the sealed copy. |
| Reviewer | Looks for defects in a fresh context. |
| Quant verifier | Checks research-integrity code against its source. |
| Sweeper | Finds and removes dead code and stale pages. |

## What is real today

Stays in this product: `scripts/gate.py check` (the one check); `factory.toml` (the law the team is judged by: protected paths, the size limit, three
changes in flight, the freeze date); the hooks; `.claude/agents/` (reviewer, quant verifier, navigator); CI and the merge queue; `scripts/update.sh`.
The map tools `scripts/fs*.py` stay too.

Rules for any agent that works in this repository directly:

- One outcome per change.
- At most about 400 product lines.
- Never edit a guarded path without the owner's yes.
- The pull request goes through the merge queue. No direct push to `main`.

The weekly health check is a scheduled task, "ALPHA weekly health check" (Mondays 13:23 Australia/Brisbane, on the Dell). It opens small clean-up pull
requests and never merges ([decision](../owner-decisions-2.md#2026-11-14-a-weekly-automatic-health-check)).

## Where it lives

- **Workspaces:** `scripts`, `tests`, `docs`
- **Capabilities:** none
- Code: `scripts/` (gate, file-system tools, update), `tests/`, `.claude/`, `.github/`, `factory.toml`.
- Decision records: [ADR-0039](../../../adr/0039-ci-is-the-merge-gate.md), [ADR-0040](../../../adr/0040-one-file-system-atlas-retired.md),
  [ADR-0041](../../../adr/0041-no-hidden-test-suite.md), [ADR-0056](../../../adr/0056-the-build-team-replaces-the-delivery-pipeline.md).
- How to change it: [scripts/CONTEXT.md](../../../../scripts/CONTEXT.md), [tests/CONTEXT.md](../../../../tests/CONTEXT.md),
  [docs/CONTEXT.md](../../../CONTEXT.md).
- **Plan:** [stage 12](../../../roadmap/production-scope-3.md#12-health-and-hygiene) of the checklist; [health plan](../../../roadmap/health-plan.md).

## Decisions and open questions

- Decided, 2026-11-24: the build team replaces the Software Team and the delivery pipeline ([log](../owner-decisions.md)).
- Decided: a weekly automatic health check that never merges.
- Purpose: keep every change small, checked and recorded.
- Reasoning: code holds rules that prose could not.
- Plan: the build team runs the line.
- Location: the `alpha-factory` repository, plus the parts listed above.

## Never

- Never weaken bias guards, oracles or the guarded holdout path to make a change pass.
- Never copy a fact into a second file; link to its one home.
- The rules: [engineering](../../invariants/engineering.md), [testing](../../invariants/testing.md),
  [documentation](../../invariants/documentation.md).
