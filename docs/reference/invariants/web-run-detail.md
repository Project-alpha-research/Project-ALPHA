---
owner: web frontend
sources:
  - apps/alpha-web/frontend/src/panels/**
  - apps/alpha-web/frontend/e2e/**
verified: e8dd8bb18aca843d
---

# Web run detail invariants

How the run detail, RD-Agent journey and Setup Lab panels bind to the selected run. The other frontend rules are in [web-frontend.md](web-frontend.md).

## Run detail binding

- `panels/rundetail/index.tsx` tags every async result with the `runId` and request id that asked for it, and renders only results for the currently selected
  run and its latest request. A previous run's summary, figures or trades must never show or export under the new run.
- States are explicit: no run selected → "Select a run"; error → the error; pending → "Loading run…". A trades request error stays distinct from a genuinely
  empty trades list. Enforced by `e2e/rundetail-trades-race.spec.ts`.
- `reportModel.summaryRows` shows recorded manifest values only (`not recorded` otherwise) — no client arithmetic.
- `reportModel.reportTree` keeps empty leaves visible with their reason. In the figure overlay a Copy the browser cannot do is disabled with the reason, and
  question, uncertainty and caveat prose stays in the DOM in both explain modes.
- The rule-test Summary takes its headline dates from the first executable open through the final tradable open. Loaded dates appear below. Each dated row
  reads its own stored returns, annual growth, worst drop, closed trades, Sharpe and price basis from the manifest. Row one is “Whole period the rule could
  trade”; “Scored test periods only” uses the walk-forward portfolio and its trade count. Each row has matching comparison and drawdown figures, stored light
  for new runs. Old runs keep saved figures and a full-history disclosure. Missing period values read “not recorded”. A catalogue request distinguishes
  loading, failure and missing figures. Flags and variants precede closed setup and audit disclosures. Audit rows retain each identifier, status and detail.
  Only variants subtract Sharpe scores. Covered by `ruleTestModel.test.ts`, `rundetail/RuleTestSummary.test.tsx` and `e2e/rule-test-summary.spec.ts`.
- Rule tests and Setup Lab show a non-pass data health line under the headline; old runs read “Data health: not recorded.”
- The backtest result card is opt-in (`backtestResultCard` defaults to `false`). With malformed, legacy or failed evidence it renders as unavailable. Enforced
  by `e2e/backtest-result-card.spec.ts`.

- The RD-Agent picker shows each idea's name, recorded verdict in plain words and publication state. The run summary omits missing values or shows “This run
  stored no summary.” Ledger absence appears in technical detail. Selecting an idea reads its journey in place. Responses and disclosures belong to that run
  and idea. The header repeats the recorded exploratory label from the last fact of step seven. The seven steps keep their stored order, actor and wording.
  Each headline number uses its stored display string and a visible gloss. A step shows its PNG on a light card, or its recorded reason in muted text. The
  card sits below the text in a narrow pane. Code keeps its indentation and wraps long lines with a hanging indent. Source files, the agent's own words and
  code beyond twelve lines use closed disclosures. Missing values read “not recorded”. A missing journey shows the local build command. The browser starts no
  build. Covered by `RdAgentPanel.test.tsx`, `RdAgentJourney.test.tsx` and `e2e/rdagent-journey.spec.ts`.

- Setup Lab is Research → Setup Lab (`SetupLabPanel`, both profiles): GET routes only, each response bound to the selected find. Stored figures have value
  tables. Trade return and initial risk display as percentages beside direction and R. The timeline keeps rejected matches grey. Values round only; no curve
  or total is calculated. Unstored parts say "not recorded". Tests: `SetupLabPanel.test.tsx`, `setupLabModel.test.ts`, `e2e/setup-lab.spec.ts`.
