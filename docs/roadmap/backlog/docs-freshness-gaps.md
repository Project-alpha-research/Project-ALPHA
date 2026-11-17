# File-system freshness gaps

**Status:** Scoped
**Rough size:** S

## Problem / why

Follow-ups from pull request 203 and the 2026-11-16 file-system audit:

- A document whose sources are only other documents can never go stale on code changes
  (the delivery-and-agent-tooling page is one).
- Module tables in workspace `CONTEXT.md` files are kept by hand; generate them from code.
- `rdagent_exposure.py` was missing from the command-line routing table.
- A refactor note for the web app's response models (`alpha_web/api/models.py`) was owed by the
  health plan and never written.
- Pull request 210 names a private folder path in the public register; remove the path.

## Where it would live

`scripts/fs.py`, `tests/unit/test_filesystem_contract.py`, the workspace `CONTEXT.md` files.

## What "done" looks like

Each point fixed or dropped with a reason.

## Dependencies

None.

## Sources

- [Health plan items](../health-plan.md)
