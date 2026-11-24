# Reviewer: checklists by folder and a required coverage list

**Status:** Idea
**Rough size:** S

## Problem / why

A trial of an outside code reviewer (2026-11-16, kept in the owner's folder) found nothing
ALPHA's own reviewers missed, but two of its ideas are worth borrowing: a checklist chosen by
the folder a file lives in (look-ahead and point-in-time; fail-loud; secrets and network), and
a required list showing every changed file was reviewed or deliberately skipped.

The trial also found ten defects in two branches (a diagnose lock, audit slippage, a crash in
facts, results show, the delay flag, a memory receipt, a ledger path error, the gap check at
series ends, a verify message). Whether each is fixed on main has not been checked.

## Where it would live

`.claude/agents/reviewer.md` (protected: a reviewed pull request).

## What "done" looks like

The reviewer uses folder checklists and prints a coverage list; each of the ten defects is
confirmed fixed or has its own fix.

## Dependencies

None.

## Sources

- [Outside projects register](../../reference/project/outside-projects.md#notes-on-single-rows)
