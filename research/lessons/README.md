---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/facts.py
verified: c30578ad48266a0d
---

# Lessons

What research on ALPHA has taught so far, one short file per lesson, so the next piece of work starts from
it. A lesson is a suggestion for whoever works next, never a rule: it can be wrong, and a later run may
contradict it. Read the lessons before proposing a test; say in the answer which ones you checked.

There are no lessons yet. The `record-lesson` skill (`.agents/skills/record-lesson/SKILL.md`) writes them.

## Format

One file, `research/lessons/<slug>.md`, about ten lines, no front matter:

```text
# <the claim, as a short title>

- Claim: one sentence that should change what is tried next.
- Scope: assets, bar size, period. No wider than what was tested. Or "system" for a lesson about ALPHA.
- Evidence: <value> [<run id>:<metric>], one line per run. At least one run.
- Status: open | held | contradicted
- Date: yyyy-mm-dd
- Times used: 0
```

## How lessons live

- **Evidence is a run.** Every lesson names at least one run id, with a number quoted through
  `uv run alpha results cite <run_id> <metric>`. The owner's view is written "Owner hypothesis:" until a run
  supports it.
- **Use counts.** When a lesson shapes a later test, add one to "Times used".
- **Contradicted, not deleted.** New evidence against a lesson changes its status and adds the run id.
- **Small.** A lesson used three times, or confirmed, becomes a one-line edit to
  [the playbook](../PLAYBOOK.md) or a [tool card](../tools/README.md). Lessons unused for a long time, or
  contradicted, are removed by an ordinary pull request.
- **Finding one.** Read this folder, or `uv run python scripts/fs.py search "<words>"`. A lessons search
  command is not available yet.
