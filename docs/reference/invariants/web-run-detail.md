---
owner: web frontend
sources:
  - apps/alpha-web/frontend/src/panels/**
  - apps/alpha-web/frontend/e2e/**
verified: 7614f54c171788a6
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
- The rule-test Summary lists “Checks run on this test”: each stored toolbox result (plain name, stored reading, labels in words,
  time) or “could not run: <stored error code>”, from GET `/api/runs/{id}/checks`. With none it quotes
  `alpha tool run-set market-context <run_id>`. Nothing is computed in the browser. Covered by `rundetail/RuleTestChecks.test.tsx`.
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

## Workstation recorded fields

View → RD-Agent and the command palette open the read-only panel in either market profile. Runs are direct child
folders of `<data dir>/../runs` (override: `ALPHA_RDAGENT_RUNS_DIR`); the ledger is
`rdagent-trial-ledger/rdagent-factor-trials.jsonl` inside it. It cannot launch, approve, call models or read keys.

| Response fields | Recorded source (relative to the run folder unless noted) |
|---|---|
| Identity, start/end, outcome | `receipt.json`: `run_id`, `started_at`, `ended_at`, `exit_status`, `loop_reason`; folder name |
| Rounds, calls, embedding calls | Receipt: `memory.rounds_completed`, `counted_calls`, `local_embedding_calls`, `provider_embedding_calls` |
| Spend, caps, month snapshots | Receipt: `gateway_status.this_run.usd`, `.caps`, `.months`; month selected by receipt end time |
| Cache and providers | Receipt: `call_split.chat_usage`; no new rate calculation |
| Funnel and list stage totals | Receipt `funnel` if present; else ledger factors plus `rounds.jsonl` refusals and provider losses |
| Factor name, description, status | Shared ledger: `run_id` or folder name, schemas V1–V3; fixed web-owned status sentences |
| Clock figures, deflation, write-offs | Ledger: `clocks.*.screen`, `.spread`, `.replay`, `.replay.deflated_sharpe`, `.replay.deflated_sharpe_family` |
| Universe, gaps, ticker corrections | `panel/panel-receipt.json`: instruments, disclosure, gap counts, `identity_breaks`, `identity_rescales` |
| Refusals and timing | `rounds.jsonl`: refusal status and families; `steps.jsonl`: step start and end times; minutes = end minus start, labelled |
| ALPHA notes | Receipt cap/cache/memory notes, panel disclosure, `evaluations.jsonl` → `feedback_text` |

New rows show declared choices, cutoff/counts, diagnostic p/q, deflation, twins and expected chance passes. The funnel
adds "shortlisted (passed all but the many-tries correction)" before the deflation stage. Shortlisted is not a pass,
not a candidate, and not evidence of profit; missing flags mean "not recorded". Lineage R², regressor count and
convention are recorded diagnostics; suspects say "looks like a blend of earlier tries". The [shortlist
policy](../../../workers/rdagent/judge-rules.md#shortlist-bookkeeping) leaves every gate and count unchanged. Old
failed-deflation candidates read DEFLATION_FAIL (derived); stored deflation is labelled "old rule (fewer looks
counted)". Absent facts stay null. Counts come from recorded rows, never candidate status; step minutes need two
timestamps. New factor rows store family and critic status. Older rows can lack both. The panel was opened headless on
real runs; owner acceptance remains pending.
