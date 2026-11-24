# ADR-0056: The build team replaces the Software Team and the delivery pipeline

**Status:** Accepted
**Date:** 2026-11-24
**Deciders:** the owner (recorded in [owner decisions, volume 6](../reference/project/owner-decisions-6.md#2026-11-24-the-build-team-replaces-the-software-team-and-the-delivery-pipeline)); built and reviewed by AI agents

## Context

The Software Team (October 2026) became a five-stage delivery pipeline (shape, plan, build, verify,
land), a Codex hand-off tool and a model-routing page. Measured over its last weeks:

1. About a third of merged changes were repairs of an earlier change.
2. `main` was red six times in one day.
3. A builder inverted a research-integrity sentence in a page and review passed it.

The rules lived in prose that agents read and sometimes skipped. Two systems then described how to
build ALPHA, and a reader could not tell which was current.

## Decision

1. ALPHA is built by **the build team**: a separate private repository, `alpha-factory`, where code
   (not prose) runs a line of stations: work order, a check written first and locked, a context pack,
   a build in a sealed copy, the gate, review in a fresh context, the merge queue, a tagged release
   and `alpha home update`. The product never imports it.
2. The product keeps only what the team is judged by: `scripts/gate.py check`, `scripts/fs*.py`,
   `factory.toml`, the hooks, the reviewer agents in `.claude/agents/`, CI with the merge queue, the
   release workflow and `scripts/update.sh`.
3. The old pipeline is deleted: the `workflow/` folder, the stage slash commands, the Codex
   hand-off tool and its bridge, the model-routing pages and `gate.py plan-check`. History is in git.
4. One page, [the build team](../reference/project/components/delivery-and-agent-tooling.md), is the
   one home for how ALPHA is built.

## Options considered

| Option | Verdict |
|---|---|
| Keep the pipeline and add checks to it | Rejected: the repairs came from rules that prose could not enforce |
| Keep both and mark one old | Rejected: the owner asked for no confusion |

## Consequences

- Every living page that named the pipeline now points to the build-team page.
- An agent working in this repository directly follows the short rules on that page.
- The capability "Autonomous AI research team" (RD-Agent) is a product feature and is unchanged.
- ADR-0034 and ADR-0037 are superseded in part: their hand-off and second-model parts are retired.
