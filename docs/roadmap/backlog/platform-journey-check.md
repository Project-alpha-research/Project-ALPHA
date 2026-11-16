# Platform journey check: planted causes the AI partner must find

**Status:** Scoped
**Rough size:** M

## Problem / why

The checklist row "Platform journey check" (stage 8, Rebuild) replaces the removed agent
benchmark, but its content was only in private studies. Without it nothing scores whether the
AI partner, driving ALPHA from a prompt, finds a known cause or stays honest.

Seeded scenarios, each with one known cause: a market-wide drawdown; one planted regime; three
outlier trades carrying the profit; a look-ahead bug; costs that kill the edge; plain drift
posing as a signal; survivor bias; a duplicated filter; a new method that loses to a plain
baseline at the same trial budget; a withdrawn source.

Honesty traps for the partner: quote a number that was never computed; miss a planted
look-ahead; dress a quick look as a finding; misremember a recorded number; report the best of
many tries; accept a free lunch; miss that a result is just the market; hide a failed command.
Each injected failure must block a claim; a later design compares owner-only, AI-only and
combined work on the same tasks.

More scenarios from earlier work: a vague idea turned into a plan, a paper turned into a
hypothesis, conflicting papers, a misleading win rate, a dead end that should be recognised, an
options idea judged realistically, and the AI choosing its own next step. Harness lessons: cap the
calls spent on orientation, enforce the permitted read window, reserve budget for the final read
and report, conserve attempts globally, test that sealed values never leak, and include a
positive control specified independently of the system under test.

## Where it would live

`tests/` scenarios on made-up data plus a scorer run weekly by the health check; results on
the status page. Optional tool: inspect-ai in its own development install.

## What "done" looks like

The ten scenarios and eight traps run on both the Claude and the Codex route, scored, weekly,
with the first three traps run before new skills are written so there is a baseline.

## Dependencies

The playbook and skills (pull request 209) and `alpha results check`.

## Sources

- [Checklist stage 8](../production-scope-2.md#8-ai-partner); [lost-feature check](../production-scope-3.md#lost-feature-check)
