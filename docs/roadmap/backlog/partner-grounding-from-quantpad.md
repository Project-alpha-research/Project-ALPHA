# What the research partner borrows from QuantPad

**Status:** Scoped
**Rough size:** M

## Problem / why

The owner named QuantPad as the reference product ("like QuantPad but more agentic",
[production grade](../../reference/project/owner-decisions-3.md#2026-11-15-what-production-grade-means)).
Two private studies (2026-11-15/16) compared it with ALPHA. What they concluded, in short:

- Copy three habits: one plain question leads to a chart; saved procedures as plain files;
  a visible review step. Beat it on honest judging, memory and autonomy. Skip sharing and the
  social features (personal use).
- Grounding: the AI never produces a number itself; tools are narrow and capped; known
  mistakes are warned about inside the tool descriptions; data is looked at in a fixed order.
- About nine plain verbs (get, idea, test, diagnose, tool, vary, results, learn, promote), each
  wrapping today's commands.
- A default report order (answer, what was tested, charts, benchmark, overfit tests, flags,
  what was tried, next) and default charts (equity against benchmark, regime shading, match
  gallery, profit by regime, sensitivity bars). A report may only name charts that exist.
- "Validated" may be written only when the audit has no flag and nothing unchecked.
- Audit checks not built yet: trade size against bar volume, break-even cost, a run-time
  future-poison check, the share explained by the market, settings moved by 20 per cent.
- Spine outputs get checked schemas with contract tests.
- TradingView script import is lower priority than the translation card.
- More of its tricks: prompts go through the model the user picks; code runs in throwaway
  sandboxes; the read-only tool server previews at most 500 bars.
- One label vocabulary on every result: exploratory, confirmation used, free data unconfirmed,
  survivor-biased, number of trials, look-ahead checked, costs flat or size-aware; agent-made
  evidence carries an "agent-made, owner-reviewed" label instead of a separate review lane.
- A retail-fit line in every report: holding period, capacity and costs at the owner's size.
- Lessons are about ten lines with scope, run ids, status and times used; promoted after three
  uses; the weekly health check lists lessons unused for 90 days or contradicted.
- In Claude Code a stop hook runs the answer check on replies that cite runs; other routes rely
  on the skill and the journey check. The app connection needs a remote transport (the tool
  server speaks only to local programs today).
- Practitioner guardrails: recompute statistics from the equity curve; review code against the
  spec and audit the trade log separately; quote a source's own definition before testing it.
- A papers tool card replaces the old literature-review protocol.
- Panels to fold away once their content shows elsewhere: the Codex bench, the AI console and
  dock, the two engine demos, and the pipeline view once Results and Trail exist.
- Which strict rules stay: the storage reserve, quarantine on cross-source differences, the
  hooks, the hidden-test guard, the commit hook; cosmetic-edit limits are relaxed.
- The studies' twelve-pull-request build order is replaced by the three golden paths.
Unverified about QuantPad: its price, documents behind a login, app support for tool servers.

## Where it would live

`research/` (playbook, tool cards, skills), `alpha results check`, `apps/alpha-mcp`.

## What "done" looks like

Each point above is either a checklist row's evidence or dropped by the owner; this note is
deleted when the last one lands.

## Dependencies

Pull request 209 (playbook and skills); the chat-panel and demo-view removal (stage 10).

## Sources

- [Checklist stage 8](../production-scope-2.md#8-ai-partner)
