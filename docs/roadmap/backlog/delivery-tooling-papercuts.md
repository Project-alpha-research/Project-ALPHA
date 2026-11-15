# Delivery tooling paper cuts found while building the swing-judge stack

**Status:** Idea
**Rough size:** S

## Problem / why

- **Briefs fail late.** `handoff.py build` checks a brief's headings only after `uv sync`, about
  two minutes in. The headings must match exactly: `# Task: ...` and
  `## Decision already made (do not revisit)` are rejected.
- **Builds stop to ask.** Twice, a Codex build stopped in under 90 seconds to ask a design
  question, about a degenerate-factor bucket file and about ledger write atomicity. Briefs need
  a standing "choose the simpler correct option and say so" line.
- **The structural-digest trap.** Codex wrote `argparse.ArgumentParser(description=__doc__)` in
  two new command modules. The structural-digest guard forbids that outside its reviewed list,
  and the local gate does not run that test for new files. CI caught it, at the cost of one
  round trip each time.
- **`gh pr edit` fails.** Its call errors on the Projects (classic) deprecation. The REST call
  `gh api -X PATCH repos/.../pulls/N -F body=@file` works.

## What "done" looks like

- `handoff.py` validates a brief before syncing and accepts heading prefixes.
- The brief template carries the "decide and state" line and names the `__doc__` trap.
- The local gate maps any new `alpha_cli` module to `tests/unit/test_structural_digest.py`.
- The landing guide uses the REST call for editing a pull request body.

## Dependencies

`scripts/handoff.py` and `scripts/gate*` are protected files: the owner-approved route applies.

## Sources

- Pull requests #178, #183, #187 and #191 (build records under the hand-off home).
