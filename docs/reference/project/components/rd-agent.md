---
owner: project layer
sources:
  - workers/rdagent/CONTEXT.md
  - workers/rdagent/README.md
verified: 6b0960fc5a0d180e
---

# RD-Agent

On this page: [Why it exists](#why-it-exists), [Its job in the research loop](#its-job-in-the-research-loop), [Intended design](#intended-design),
[What is real today](#what-is-real-today), [Where it lives](#where-it-lives), [Decisions and open questions](#decisions-and-open-questions), [Never](#never).

RD-Agent is Microsoft's open-source AI research agent. In ALPHA it is the research loop: it
proposes an idea, turns it into an experiment, runs it, judges the result, remembers it and
repeats. It is a core engine; the owner has said so in plain words.

## Why it exists
ALPHA's purpose is to test many market ideas carefully. Doing that by hand is slow, and building
a research agent from scratch would duplicate a mature open-source one. So ALPHA uses RD-Agent to
drive the loop, and keeps for itself everything that must be exact and owner-controlled.
The owner: "Rd agents is one of the key components"
([owner decisions](../owner-decisions.md#2026-11-14-rd-agent-is-a-key-component)).

## Its job in the research loop

Steps 3 to 6 of the [research loop](../overview.md#the-research-loop): propose a hypothesis, have
the experiment built (a [Qlib](qlib.md) model or a [trading rule](strategies-and-signals.md)),
have it backtested by [Nautilus](nautilus.md), take the verdict of the
[statistical checks](validation-and-evidence.md) as feedback, and go round again. It never decides
what counts as evidence; [the owner does](research-cases-and-approval.md).

## Intended design
- One fixed upstream version (commit `484776c`), checked file by file; never copied into ALPHA or edited.
- It runs as a separate worker program with its own install, started and supervised by the
  [command line](command-line.md). No ALPHA package imports it.
- RD-Agent supplies the loop engine, its records (hypothesis, experiment, trace, feedback) and its
  checkpoints. ALPHA supplies the budget, the data, the backtests, the statistics, the approvals,
  cancellation and recovery. There is no second scheduler or trial ledger.
- An AI model proposes the hypotheses. The owner prefers strong models through the ChatGPT
  subscription, with a cheap model on an API key as the fallback, without losing quality
  ([owner decisions](../owner-decisions.md#2026-11-14-rd-agents-ai-models)).
- RD-Agent reaches every model through ALPHA's local model gateway
  (`workers/rdagent/model_gateway.py`, [ADR-0044](../../../adr/0044-rdagent-model-gateway.md)):
  chat through the signed-in Codex program; embeddings through local Ollama by default, or a
  configured paid provider model with explicit pricing. The gateway holds ALPHA's call and dollar budget, refuses or records
  every setting it cannot honour, and logs each call without its text. Cache and serving-provider
  facts reach the receipt; API calls use a run-only router session, with a comparison-run opt-out.
  Recording details: [worker README](../../../../workers/rdagent/README.md#model-gateway-2026-11-14).
- ALPHA, not RD-Agent's built-in Qlib backtest, judges the factor loop: a cheap rank screen first, then a
  cost-aware replay only for factors that pass, with 2024 onward locked away from the loop
  ([ADR-0049](../../../adr/0049-alpha-judges-rdagent-factors.md), [ADR-0055](../../../adr/0055-spread-check-family-brief-and-universe-file.md)).
  A factor that passes everything is only a CANDIDATE: a lead for one owner-approved check on reserved data,
  never evidence. Every try counts, failures included, and the proposer is shown what failed so it stops repeating it.
- The data is a frozen universe file; missing days and delisted names are allowed with explicit disclosure,
  the data is not survivorship-free, and renamed or split tickers need an owner-supplied break list.
- Runs resume from completed rounds; an unfinished round is recorded as abandoned, never invented as a trial.
  The wrapper refuses proposals from idea families that have already failed repeatedly and asks again.
  Counts, caps and spend are always explicit. The technical rules of each of these are change notes in the
  [worker README](../../../../workers/rdagent/README.md#change-notes-moved-from-the-project-page-2026-11-18).
- RD-Agent remembers across runs; what it keeps and its limits are in the worker README's
  [research memory](../../../../workers/rdagent/README.md#research-memory-2026-11-15).
- Human-authored rule families (written by a person, frozen and hash-checked before the run) are
  backtested on [Nautilus](nautilus.md) without any 2024 data and go into the same trial ledger,
  so they count toward how many ideas were tried, but never mix into RD-Agent's factor statistics
  or the summary it proposes from (`alpha_cli.rdagent_rule_family`).
- Later: RD-Agent drives the Qlib worker, and composes studies across all research families.
- The plain-English walk-through is [RD-Agent in ALPHA](../../../roadmap/rd-agent-in-alpha.md).

## What is real today

See the capabilities below on [STATUS.md](../../../../STATUS.md), and
[what is real today](../../../roadmap/rd-agent-in-alpha.md#what-is-real-today) and
[what is still made-up](../../../roadmap/rd-agent-in-alpha.md#what-is-still-made-up).
Being uninstalled somewhere, or having skipped tests, means work is left, not that it should go.

## Where it lives

- **Workspaces:** `workers/rdagent`
- **Capabilities:** `ai-stock-research`, `native-job-result`, `daily-rule-study`, `ai-research-team`,
  `rdagent-run-viewer`, `rdagent-workstation-panel`, `rdagent-idea-journey`
- Code: [`workers/rdagent/`](../../../../workers/rdagent/README.md) (the model gateway is
  `workers/rdagent/model_gateway.py`); the job supervisor in
  `apps/alpha-cli/src/alpha_cli/native_supervisor.py`. Setup: `scripts/setup_rdagent.sh`.
- Tests: `tests/smoke/test_rdagent_smoke.py`, `tests/unit/test_native_loop_conformance.py`,
  `tests/unit/test_rdagent_foundation_contract.py`; the gateway's
  `tests/unit/test_rdagent_model_gateway.py` and `tests/smoke/test_rdagent_model_gateway_smoke.py`.
- How to change it: [workers/rdagent/CONTEXT.md](../../../../workers/rdagent/CONTEXT.md).
- Plans: the `plans` of each capability above in `docs/roadmap/capabilities.toml`.
- Backlog: [autonomous research and restart](../../../roadmap/backlog/rdagent-autonomous-research.md),
  [factor loop under the job supervisor](../../../roadmap/backlog/rdagent-factor-loop-supervision.md),
  [candidate to research case](../../../roadmap/backlog/rdagent-candidate-to-research-case.md),
  [gate coverage](../../../roadmap/backlog/gate-coverage-rdagent.md).
- Decision records: [ADR-0044](../../../adr/0044-rdagent-model-gateway.md) (how it reaches its
  models), [ADR-0049](../../../adr/0049-alpha-judges-rdagent-factors.md) (ALPHA judges its factors),
  [ADR-0050](../../../adr/0050-swing-clocks-in-the-factor-judge.md) (at swing holding periods),
  [ADR-0055](../../../adr/0055-spread-check-family-brief-and-universe-file.md) (spread check, families).
  Related: [ADR-0011](../../../adr/0011-evidence-gated-external-integrations.md),
  [ADR-0035](../../../adr/0035-generic-study-composition-and-external-capability-adapters.md).
- Glued under [ADR-0051](../../../adr/0051-glue-rules-for-outside-projects.md) (the glue rules).
- **Plan:** [stage 9](../../../roadmap/production-scope-2.md#9-rd-agent-and-qlib-engines) of the
  checklist and [RD-Agent in ALPHA](../../../roadmap/rd-agent-in-alpha.md).

### Workstation recorded fields

View → RD-Agent and the command palette open the read-only panel in either market profile. Runs are direct
child folders of `<data dir>/../runs` (override: `ALPHA_RDAGENT_RUNS_DIR`); the ledger is
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

New rows show declared choices, cutoff/counts, diagnostic p/q, deflation, twins and expected chance passes.
The funnel adds "shortlisted (passed all but the many-tries correction)" before the deflation stage.
Shortlisted is not a pass, not a candidate, and not evidence of profit; missing flags mean "not recorded".
Lineage R², regressor count and convention are recorded diagnostics; suspects say "looks like a blend of earlier tries".
The [shortlist policy](../../../../workers/rdagent/README.md#shortlist-bookkeeping) leaves every gate and count unchanged.
Old failed-deflation candidates read DEFLATION_FAIL (derived); stored deflation is labelled "old rule (fewer looks counted)".
Absent facts stay null. Counts come from recorded rows, never candidate status; step minutes need two timestamps.
New factor rows store family and critic status. Older rows can lack both. The panel was opened headless on real runs; owner acceptance remains pending.

## Decisions and open questions

- KEEP, owner, 2026-11-14 ([log](../owner-decisions.md#2026-11-14-rd-agent-is-a-key-component)).
- What is next, in order, with what each needs from the owner: [the seven
  blockers](../../../roadmap/rd-agent-in-alpha.md#what-stands-between-today-and-rd-agent-researching-real-ideas).
- Decided: the Codex route comes first; an API key is the fallback, capped at about 50 US dollars a month
  ([log](../owner-decisions.md#2026-11-14-api-spending-limit-for-rd-agents-models)). Built as the model gateway
  ([ADR-0044](../../../adr/0044-rdagent-model-gateway.md)); measured quality and how far a real step got are in the [task's verification][gateway-verify].
- Decided, for now: accept losing RD-Agent's "temperature" setting on the Codex route; launch the gateway with `--accept-unhonoured temperature`
  ([log](../owner-decisions-2.md#2026-11-14-accept-losing-temperature-on-the-codex-route-for-now)).
- Decided 2026-11-14: RD-Agent may use DeepSeek through OpenRouter (temperature honoured), caps unchanged. Built: `--chat-route api --api-openrouter` on the
  gateway and the factor-loop launcher, model `deepseek/deepseek-v4.1-flash-1017` at USD 0.038 / 0.50 per million input / output tokens (OpenRouter's list,
  read 2026-11-14). Codex stays the default and the fallback; how to choose: [worker
  README](../../../../workers/rdagent/README.md#alpha-judged-factor-loop-2026-11-14). First run 2026-11-14 (3 rounds, 54 calls of 60, about USD 0.04): nine
  factors tried, no candidate; one run per route is not a quality comparison (numbers in the worker README).
- Measured 2026-11-16 (system tests, about USD 0.66): 66 factors, no candidate; 15 of 18 replayed swing screen passes lost money before costs (15 coins). Runs
  sharing a gateway can start together; feedback explains losses. Owner charts: `owner/rdagent-status/` beside the checkout, outside git.
- Measured 2026-11-16 with the spread check (ADR-0055): offline it rejects 16 of those 18 trials; two fresh runs (about USD 0.22) judged 11 factors, moved to
  new idea families, found no candidate. Embeddings were 21 of 60 and 16 of 47 counted calls in those runs. Decided by the owner 2026-11-17: free local
  embeddings are exempt, with their own 2,000-attempt guard; the other caps keep their values. Historical counts stay as recorded. The stores then held 15
  coins and 9 single stocks. Long memory embeddings are chunked, never truncated.
- Decided: the first goal after the clean-up is one real RD-Agent loop, connected to a model through Codex
  ([log](../owner-decisions-2.md#2026-11-14-first-goal-one-real-rd-agent-loop)). First run, 2026-11-14: every step ran on real crypto bars, but RD-Agent's
  built-in Qlib backtest learned nothing on 15 coins, so the loop is not yet meaningful ([verification][loop-verify]).
- Open, for the owner: how RD-Agent's ideas get a backtest that can see them (a wider universe, ALPHA's own Nautilus and statistical checks, or a calibration
  run on Qlib's public data) ([roadmap item 2b](../../../roadmap/rd-agent-in-alpha.md#what-stands-between-today-and-rd-agent-researching-real-ideas)).
- Decided: long studies use the Dell's disk for now ([log](../owner-decisions.md#2026-11-14-use-the-dells-disk-for-studies-for-now)).
- Decided: the autonomous research team is a broader ALPHA capability built around and using RD-Agent, started small; it reuses RD-Agent's native abilities
  and never bypasses ALPHA's controls ([log](../owner-decisions.md#2026-11-14-the-autonomous-research-team)).
- Plan, 2026-11-18 (not built yet): RD-Agent becomes a collaborator, not a black box: every automatic refusal is shown with its reason and can be
  overridden, a "propose and discuss" mode shows ideas and reasoning before anything is spent, and honesty checks appear as labels
  ([plan](../owner-decisions-4.md#2026-11-18-orchestrators-plan-the-paths-are-ways-of-working-and-rd-agent-becomes-discussable),
  [owner](../owner-decisions-5.md#2026-11-18-the-agent-is-a-collaborator-never-a-black-box)).
- Decided 2026-11-18: the run view uses the approved journey layout ([log](../owner-decisions-5.md#2026-11-18-the-idea-journey-layout-is-approved)); while
  ideas are throwaway tests a labelled stand-in user may answer its pauses (the pause mode is not built yet), never for approvals
  ([log](../owner-decisions-5.md#2026-11-18-stand-in-user-while-ideas-are-throwaway-tests);
  [owner authority](../../invariants/research-integrity.md#owner-authority)).
- Later: RD-Agent chooses tests from the [toolbox](toolbox.md) but does not write them (recommended, not confirmed); Kronos, [Monte Carlo](monte-carlo.md),
  lookalike and pattern tools are its tools to be wired in.
- Open: no decision record states RD-Agent's role; write one once the owner confirms the summary in the [overview](../overview.md#the-research-loop).

## Never

- Never recommend shelving, removing or replacing it without citing this file and the
  [owner decisions log](../owner-decisions.md).
- Never copy, patch or re-implement RD-Agent inside ALPHA; use the pinned upstream version.
- Never let its output count as evidence or approval.
- Never connect it to a model except through the gateway, and never let the gateway switch to the
  paid route by itself.
- The worker rules: [RD-Agent worker](../../invariants/workers.md#rd-agent-worker) and
  [command line native](../../invariants/cli-native.md).

[gateway-verify]:
  https://github.com/tradingsystem1880-eng/Project-ALPHA/blob/pre-thin-2026-11-14/docs/work/archive/2026-11/2026-11-14-rdagent-model-gateway/04-verify.md
[loop-verify]:
  https://github.com/tradingsystem1880-eng/Project-ALPHA/blob/pre-thin-2026-11-14/docs/work/archive/2026-11/2026-11-14-rdagent-first-real-loop/04-verify.md
