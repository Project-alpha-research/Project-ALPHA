---
owner: project layer
sources:
  - apps/alpha-mcp/CONTEXT.md
  - docs/reference/invariants/cli-assistant.md
  - research/PLAYBOOK.md
  - .agents/skills/*/SKILL.md
verified: 7696bf156a08a889
---

# AI assistants

How an AI works with ALPHA on research (as opposed to building it). The main way is the research
partner: Claude or ChatGPT, in an app or a terminal, following a one-page playbook and calling the
`alpha` commands. Two older ways remain: an in-product assistant that can explain a recorded run,
and a tool server (MCP, the Model Context Protocol) that lets an AI client call a bounded set of
`alpha` commands.

## Why it exists

The owner works with AI agents. They need a safe way to read ALPHA's results and run allowed
commands, and the owner benefits from plain explanations of evidence, without any of it turning
into a decision ([ADR-0022](../../../adr/0022-codex-collaboration-surface.md)). The owner also wants
more than an instruction follower: an AI that knows what to suggest, how to read results along the
way and which test to run next, and that learns
([owner decision](../owner-decisions-3.md#2026-11-15-the-ai-must-be-a-research-partner-not-an-instruction-follower)).

## Its job in the research loop

The partner drives the toolbox for any idea: it runs the test, reads the flags and audit,
investigates surprises and reports in plain English. ALPHA computes every number; the partner
computes none and decides nothing that is the owner's. The in-product assistant and the tool
server stay advisory: they explain and suggest, and never admit evidence or approve anything.

## Intended design

The partner's instructions are four small sets of files, each with one job:

| What | Where | Why |
|---|---|---|
| Playbook | `research/PLAYBOOK.md` | One page: the method, the numbers rule, how labels are reported; not a script |
| Tool cards | `research/tools/` | One card per tool that runs today, found by symptom; also lists what is not built yet |
| Six skills | `.agents/skills/<name>/` | Test an idea, review a result, investigate a surprise, report, answer from records, record a lesson |
| Lessons | `research/lessons/` | What was learned, about ten lines each, with run ids; suggestions, never rules |

- Numbers in an answer come only from executed runs, quoted with the run id through
  `alpha results cite`. Until ALPHA is production grade, a report says what the run showed about
  the system before it gives the result.
- `tests/unit/test_research_playbook.py` checks every command, option, metric, flag and audit
  name in those files against the program, so the instructions cannot drift from the tool.
- The tool server calls the [command line](command-line.md) as a separate process.
- Assistant and investigation output is labelled advisory and kept apart from evidence.

## What is real today

The playbook, eleven tool cards, the six skills and the lessons folder are written, and the check
above passes. They are unproven as behaviour: no test yet shows that an AI following them stays
honest. The report and answer skills now require `alpha results check` before an answer is sent. The
checker checks tagged numbers, labels and flag contradictions; `alpha partner selftest` exercises 25
planted answers without a model. Its installed smoke check passes, and no lesson has been recorded.
The research-case protocol library (`.agents/skills/alpha-research-protocols/`) is still loaded
by the program and the tool server. For the rest see the capabilities below on
[STATUS.md](../../../../STATUS.md).

## Where it lives

- **Workspaces:** `apps/alpha-mcp`
- **Capabilities:** `ai-investigations`, `ai-tools-connection`, `honesty-selftest`
- Partner instructions: `research/PLAYBOOK.md`, `research/tools/`, `research/lessons/`,
  `.agents/skills/`; routed from [research/CONTEXT.md](../../../../research/CONTEXT.md).
- Code: `apps/alpha-mcp/src/`; the `alpha assistant` and `alpha research investigations` commands
  in `apps/alpha-cli/`.
- How to change it: [apps/alpha-mcp/CONTEXT.md](../../../../apps/alpha-mcp/CONTEXT.md).
- Runbook: [Codex investigations](../../../operations/codex-investigations.md).
- Decision records: [ADR-0022](../../../adr/0022-codex-collaboration-surface.md),
  [ADR-0015](../../../adr/0015-evidence-ledger-not-agent-memory.md).

## Decisions and open questions

- 2026-11-15: the AI must be a research partner, taught a method and not a script
  ([log](../owner-decisions-3.md#2026-11-15-the-ai-must-be-a-research-partner-not-an-instruction-follower));
  all communication with the AI is through Claude or ChatGPT
  ([log](../owner-decisions-3.md#2026-11-15-what-production-grade-means)). Earlier entries are in
  the [owner decisions log](../owner-decisions.md).
- 2026-11-15: the in-product assistant panel is removed once the investigation trail screen
  exists ([log](../owner-decisions-3.md#2026-11-15-five-scope-answers), answer 3).

## Never

- Never state a number that no run computed, and never promise or imply a profit.
- Never let the tool server approve or decide research, use the one-shot confirmation, reveal the
  holdout or place orders.
- The rules: [MCP invariants](../../invariants/mcp.md) and
  [command line assistant](../../invariants/cli-assistant.md).
