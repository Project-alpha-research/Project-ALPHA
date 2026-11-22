---
owner: web frontend
sources:
  - apps/alpha-web/frontend/src/panels/idea/**
  - apps/alpha-web/frontend/e2e/idea-workspace.spec.ts
verified: 3def381fc9c490c7
---

# Web frontend ideas page invariants

What must not break when changing the Ideas page. The rest of the browser app is in [web frontend](web-frontend.md).

## Ideas page

- Ideas (View › Research › Ideas, pane `IdeaWorkspace`) lists idea cards newest first, then one page per card from `GET /api/ideas/{card}`.
  It refetches when the `ideas` activity area moves, computes nothing and writes nothing. A left navigator lists 11 steps, each with a state dot and a count.
- The story column: idea, hypothesis, rule as built (exact spec in a disclosure), data, tests (a click selects a run), charts, checks, tools,
  RD-Agent (none linked yet), forward follow, open points. Each step has an empty state in words.
- Charts are the real `FigureCard` figures of the selected run, full width, with their summary and "Expand". Checks reuse `ReadingBlock` and `Gates`.
  Under "no research cases yet": the card count, newest card and a link. Enforced by `src/panels/idea/*.test.ts(x)`, `e2e/idea-workspace.spec.ts`.
