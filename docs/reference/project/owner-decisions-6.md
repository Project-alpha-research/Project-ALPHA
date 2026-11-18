---
owner: project layer
sources:
  - docs/reference/project/owner-decisions-5.md
verified: d3dd64079e042b98
---

# Owner decisions log, volume 6

Continues the [owner decisions log](owner-decisions.md) and volumes [2](owner-decisions-2.md),
[3](owner-decisions-3.md), [4](owner-decisions-4.md) and [5](owner-decisions-5.md); the rules for
entries are in the first. New entries are appended at the end of this file.

## Entries

### 2026-11-19 Never reduce RD-Agent's capability to save tokens or cost

- **Said:** exact words not recorded; relayed by the orchestrating AI agent, not verbatim. Never reduce
  RD-Agent's capability to save tokens or cost.
- **Decided:** the research loop (prompts, reflections, feedback, memory, history) keeps its full context.
  Token cuts apply to development overhead only. A change that removes information from the research
  loop needs the owner's explicit yes.
- **Context:** a discussion change had withheld RD-Agent's own written feedback from later prompts after
  a round with a dropped idea. The owner had it restored.
- **Governs:** `workers/rdagent`; the [RD-Agent component page](components/rd-agent.md);
  [model routing](../model-routing.md).
