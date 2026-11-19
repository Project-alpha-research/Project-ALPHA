---
owner: project layer
sources:
  - workers/rdagent/CONTEXT.md
  - workers/rdagent/README.md
  - workers/rdagent/CHANGE-NOTES.md
  - apps/alpha-cli/src/alpha_cli/_rdagent_checks.py
verified: e90f700e6a3bf954
---

# RD-Agent

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
- A separate worker program with its own install, started and supervised only by the [command line](command-line.md).
  No ALPHA package imports it. One fixed upstream version (commit `484776c`), never copied into ALPHA or edited.
- RD-Agent proposes; ALPHA judges. RD-Agent supplies the loop engine and its records. ALPHA supplies the budget, the data, the backtests,
  the statistics, the approvals, cancellation and recovery. There is no second scheduler or trial ledger.
- A factor that passes everything is only a CANDIDATE: a lead for one owner-approved check on reserved data, never evidence.
  2024 onward stays locked away from the loop ([ADR-0049](../../../adr/0049-alpha-judges-rdagent-factors.md)).
- Every try counts, failures included, and the proposer is shown what failed so it stops repeating it.
- An AI model proposes the hypotheses. The owner prefers strong models through the ChatGPT subscription, with a cheap model on an API key as the
  fallback, without losing quality ([owner decisions](../owner-decisions.md#2026-11-14-rd-agents-ai-models)).

Gateway, resume and memory rules: [worker invariants](../../invariants/rdagent.md).
Data rules: [worker page](../../../../workers/rdagent/README.md#what-the-loop-does-today). Later: RD-Agent drives the Qlib worker and composes
studies. [Walk-through](../../../roadmap/rd-agent-in-alpha.md).

## What is real today

See the capabilities below on [STATUS.md](../../../../STATUS.md), and
[what is real today](../../../roadmap/rd-agent-in-alpha.md#what-is-real-today) and
[what is still made-up](../../../roadmap/rd-agent-in-alpha.md#what-is-still-made-up).
Being uninstalled somewhere, or having skipped tests, means work is left, not that it should go.

## Where it lives

- **Workspaces:** `workers/rdagent`
- **Capabilities:** `ai-stock-research`, `native-job-result`, `daily-rule-study`, `ai-research-team`, `rdagent-run-viewer`,
  `rdagent-workstation-panel`, `rdagent-idea-journey`
- Code: [worker](../../../../workers/rdagent/README.md); `apps/alpha-cli/src/alpha_cli/native_supervisor.py`; `scripts/setup_rdagent.sh`.
- Tests: `tests/smoke/test_rdagent_smoke.py`, `tests/unit/test_native_loop_conformance.py`, `tests/unit/test_rdagent_*.py`.
- How to change it: [workers/rdagent/CONTEXT.md](../../../../workers/rdagent/CONTEXT.md).
- **Plan:** [stage 9](../../../roadmap/production-scope-2.md#9-rd-agent-and-qlib-engines).

## Decisions and open questions
- 2026-11-14: KEEP, owner ([log](../owner-decisions.md#2026-11-14-rd-agent-is-a-key-component)).
- 2026-11-14: Codex route first; an API key is the fallback, capped near 50 US dollars a month
  ([log](../owner-decisions.md#2026-11-14-api-spending-limit-for-rd-agents-models)).
- 2026-11-14: accept losing the "temperature" setting on the Codex route
  ([log](../owner-decisions-2.md#2026-11-14-accept-losing-temperature-on-the-codex-route-for-now)).
- 2026-11-14: DeepSeek through OpenRouter allowed, caps unchanged ([details](../../../../workers/rdagent/README.md#moved-from-the-project-page)).
- 2026-11-14: first goal is one real loop through Codex ([log](../owner-decisions-2.md#2026-11-14-first-goal-one-real-rd-agent-loop)).
- 2026-11-14: long studies use the Dell's disk ([log](../owner-decisions.md#2026-11-14-use-the-dells-disk-for-studies-for-now)).
- 2026-11-14: the autonomous research team builds around RD-Agent ([log](../owner-decisions.md#2026-11-14-the-autonomous-research-team)).
- 2026-11-16: 66 factors judged, no candidate; the spread check rejects most replay passes
  ([measured](../../../../workers/rdagent/README.md#moved-from-the-project-page)).
- 2026-11-17: free local embeddings are exempt from call caps
  ([measured](../../../../workers/rdagent/README.md#moved-from-the-project-page)).
- 2026-11-18: RD-Agent is a collaborator, never a black box
  ([log](../owner-decisions-5.md#2026-11-18-the-agent-is-a-collaborator-never-a-black-box)). Built: the optional proposal pause on the command
  line. Not built: the pause on the Workstation screen, overriding an automatic refusal, honesty checks as labels.
- 2026-11-18: the run view uses the approved journey layout ([log](../owner-decisions-5.md#2026-11-18-the-idea-journey-layout-is-approved)).
  Panel fields: [run detail rules](../../invariants/web-run-detail.md#workstation-recorded-fields).
- 2026-11-18: while ideas are throwaway tests a labelled stand-in user may answer pauses, never approvals
  ([log](../owner-decisions-5.md#2026-11-18-stand-in-user-while-ideas-are-throwaway-tests)).
- 2026-11-18: shown replays get the fixed [toolbox checks](toolbox.md) after the verdict; agent choice of checks is only a recommendation
  ([log](../owner-decisions-5.md#2026-11-18-rd-agent-may-choose-tests-but-not-write-them-recommendation-not-yet-confirmed)). Kronos, [Monte
  Carlo](monte-carlo.md), lookalike and pattern tools await wiring.
- Open: [the seven blockers](../../../roadmap/rd-agent-in-alpha.md#what-stands-between-today-and-rd-agent-researching-real-ideas);
  a backtest that sees the ideas; a decision record for its role.

## Never

- Never recommend shelving, removing or replacing it without citing this file and the
  [owner decisions log](../owner-decisions.md).
- Never copy, patch or re-implement RD-Agent inside ALPHA; use the pinned upstream version.
- Never let its output count as evidence or approval.
- Never connect it to a model except through the gateway, and never let the gateway switch to the
  paid route by itself.
- The worker rules: [RD-Agent worker](../../invariants/rdagent.md) and
  [command line native](../../invariants/cli-native.md).
