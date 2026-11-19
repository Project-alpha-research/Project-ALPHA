---
owner: project layer
sources:
  - workers/rdagent/README.md
  - workers/rdagent/CHANGE-NOTES.md
verified: 75f65aa0b115f01b
---

# RD-Agent: dated decisions and links

The text below was on the RD-Agent [worker page](../../../workers/rdagent/README.md) under "Moved from the project page".
The [RD-Agent component page](components/rd-agent.md) keeps one dated line for each item.

## Moved from the project page

The RD-Agent project page keeps one dated line for each of these. The reasons are in the owner decisions volumes.

- KEEP, owner, 2026-11-14
  ([log](owner-decisions.md#2026-11-14-rd-agent-is-a-key-component)).
- What is next, in order, with what each needs from the owner: [the seven
  blockers](../../roadmap/rd-agent-in-alpha.md#what-stands-between-today-and-rd-agent-researching-real-ideas).
- Decided: the Codex route comes first; an API key is the fallback, capped at about 50 US dollars a month
  ([log](owner-decisions.md#2026-11-14-api-spending-limit-for-rd-agents-models)). Built
  as the model gateway ([ADR-0044](../../adr/0044-rdagent-model-gateway.md)); measured quality and how far a real
  step got are in the [task's verification][gateway-verify].
- Decided, for now: accept losing RD-Agent's "temperature" setting on the Codex route; launch the gateway with
  `--accept-unhonoured temperature`
  ([log](owner-decisions-2.md#2026-11-14-accept-losing-temperature-on-the-codex-route-for-now)).
- Decided 2026-11-14: RD-Agent may use DeepSeek through OpenRouter (temperature honoured), caps unchanged. Built:
  `--chat-route api --api-openrouter` on the gateway and the factor-loop launcher, model
  `deepseek/deepseek-v4.1-flash-1017` at USD 0.038 / 0.50 per million input / output tokens (OpenRouter's list, read
  2026-11-14). Codex stays the default and the fallback; how to choose: [worker README](../../../workers/rdagent/README.md#how-to-launch).
  First run 2026-11-14 (3 rounds, 54 calls of 60, about USD 0.04): nine factors tried, no candidate; one run per route
  is not a quality comparison (numbers in the worker change notes).
- Measured 2026-11-16 (system tests, about USD 0.66): 66 factors, no candidate; 15 of 18 replayed swing screen passes
  lost money before costs (15 coins). Runs sharing a gateway can start together; feedback explains losses. Owner
  charts: `owner/rdagent-status/` beside the checkout, outside git.
- Measured 2026-11-16 with the spread check (ADR-0055): offline it rejects 16 of those 18 trials; two fresh runs
  (about USD 0.22) judged 11 factors, moved to new idea families, found no candidate. Embeddings were 21 of 60 and 16
  of 47 counted calls in those runs. Decided by the owner 2026-11-17: free local embeddings are exempt, with their own
  2,000-attempt guard; the other caps keep their values. Historical counts stay as recorded. The stores then held 15
  coins and 9 single stocks. Long memory embeddings are chunked, never truncated.
- Decided: the first goal after the clean-up is one real RD-Agent loop, connected to a model through Codex
  ([log](owner-decisions-2.md#2026-11-14-first-goal-one-real-rd-agent-loop)). First run,
  2026-11-14: every step ran on real crypto bars, but RD-Agent's built-in Qlib backtest learned nothing on 15 coins,
  so the loop is not yet meaningful ([verification][loop-verify]).
- Open, for the owner: how RD-Agent's ideas get a backtest that can see them (a wider universe, ALPHA's own Nautilus
  and statistical checks, or a calibration run on Qlib's public data) ([roadmap item
  2b](../../roadmap/rd-agent-in-alpha.md#what-stands-between-today-and-rd-agent-researching-real-ideas)).
- Decided: long studies use the Dell's disk for now
  ([log](owner-decisions.md#2026-11-14-use-the-dells-disk-for-studies-for-now)).
- Decided: the autonomous research team is a broader ALPHA capability built around and using RD-Agent, started small;
  it reuses RD-Agent's native abilities and never bypasses ALPHA's controls
  ([log](owner-decisions.md#2026-11-14-the-autonomous-research-team)).
- Plan, 2026-11-18: RD-Agent becomes a collaborator, not a black box
  ([plan](owner-decisions-4.md#2026-11-18-orchestrators-plan-the-paths-are-ways-of-working-and-rd-agent-becomes-discussable),
  [owner](owner-decisions-5.md#2026-11-18-the-agent-is-a-collaborator-never-a-black-box)).
  Built: the optional [proposal pause](../../../workers/rdagent/propose-and-discuss.md#propose-and-discuss) on the command line. The trader answers by
  number or name before coding. Each proposer receives the trader's choices for the run. Feedback gets the full
  round hypothesis and the names the trader dropped. Re-asks disclose their cost. The decision explains changes, choices the
  agent made for the trader, and the recorded result for each built idea. Not built: the pause on the Workstation
  screen, overriding an automatic refusal, honesty checks as labels.
- Decided 2026-11-18: the run view uses the approved journey layout
  ([log](owner-decisions-5.md#2026-11-18-the-idea-journey-layout-is-approved)); while
  ideas are throwaway tests a labelled stand-in user may answer its pauses, never for approvals
  ([log](owner-decisions-5.md#2026-11-18-stand-in-user-while-ideas-are-throwaway-tests);
  [owner authority](../invariants/research-integrity.md#owner-authority)).
- Shown trading replays get the fixed [toolbox checks](components/toolbox.md) after the
  verdict, under five honesty rules. Feedback and journey step 7 carry the readings. Agent choice remains a
  recommendation. Kronos, [Monte Carlo](components/monte-carlo.md), lookalike and pattern
  tools await wiring.
- Open: no decision record states RD-Agent's role; write one once the owner confirms the summary in the
  [overview](overview.md#the-research-loop).

Links the project page used to carry:

- Plans: the `plans` of each capability above in `docs/roadmap/capabilities.toml`.
- Backlog: [autonomous research and restart](../../roadmap/backlog/rdagent-autonomous-research.md), [factor loop
  under the job supervisor](../../roadmap/backlog/rdagent-factor-loop-supervision.md), [candidate to research
  case](../../roadmap/backlog/rdagent-candidate-to-research-case.md), [gate
  coverage](../../roadmap/backlog/gate-coverage-rdagent.md).
- Decision records: [ADR-0044](../../adr/0044-rdagent-model-gateway.md) (how it reaches its models),
  [ADR-0049](../../adr/0049-alpha-judges-rdagent-factors.md) (ALPHA judges its factors),
  [ADR-0050](../../adr/0050-swing-clocks-in-the-factor-judge.md) (at swing holding periods),
  [ADR-0055](../../adr/0055-spread-check-family-brief-and-universe-file.md) (spread check, families). Related:
  [ADR-0011](../../adr/0011-evidence-gated-external-integrations.md),
  [ADR-0035](../../adr/0035-generic-study-composition-and-external-capability-adapters.md).
- Glued under [ADR-0051](../../adr/0051-glue-rules-for-outside-projects.md) (the glue rules).
- **Plan:** [stage 9](../../roadmap/production-scope-2.md#9-rd-agent-and-qlib-engines) of the checklist and
  [RD-Agent in ALPHA](../../roadmap/rd-agent-in-alpha.md).

[gateway-verify]:
  https://github.com/tradingsystem1880-eng/Project-ALPHA/blob/pre-thin-2026-11-14/docs/work/archive/2026-11/2026-11-14-rdagent-model-gateway/04-verify.md
[loop-verify]:
  https://github.com/tradingsystem1880-eng/Project-ALPHA/blob/pre-thin-2026-11-14/docs/work/archive/2026-11/2026-11-14-rdagent-first-real-loop/04-verify.md
