---
owner: project layer
sources:
  - docs/reference/project/owner-decisions.md
verified: e3b0c44298fc1c14
---

# Owner decisions log, volume 3

Continues the [owner decisions log](owner-decisions.md) and [volume 2](owner-decisions-2.md);
the rules for entries are in the first. New entries are appended at the end of this file.

## Entries

### 2026-11-15 What production grade means

- **Said:** "Production grade is having all capability's and a robust system/trading pipe line
  to reserash, build trading models, collect data, find edges in markets. Understand
  everything. Have all over fit test and any other capabilities available. All structured and
  useable so I can just promot an ai and everything works well. There's a systsem and
  structure. The ui is so I can see what is happening and use that to understand and oriccced
  foward. All communication with the ai can be via Claude or ChatGPT in app or terminal. Thomas
  skinner has a product called quant pad. Serash it online. I expect my system to work similar
  fi that. Mine is just much more agentic and autonmussm and has much more features."
- **Context:** answers an agent's proposal of a 34-item checklist. The owner prompts an AI, the
  AI drives the pipeline, and the interface is for seeing and understanding, not for chatting.
- **Governs:** the whole project; the [overview](overview.md).

### 2026-11-15 No daily-only rule; fewer strict rules

- **Said:** "There's no daily data only rule. I can test for anything and it propise any trading
  idea and rub it though the pipe line. The rules need to be less strict". And: "daily only
  data makes no sense. Stop making strict rules."
- **Context:** any idea at any bar timeframe goes through the pipeline. The earlier rule against
  high-frequency trading still stands. Prefer defaults, labels and warnings to refusals.
- **Governs:** the [data layer](components/data-layer.md); the whole project.

### 2026-11-15 Always slimmer

- **Said:** "Make slimed always try refactor and thin out Bloat and mess".
- **Context:** answers whether to restore the removed agent benchmark tool or replace it later
  with something slimmer: replace it with something slimmer.
- **Governs:** [delivery and agent tooling](components/delivery-and-agent-tooling.md).

### 2026-11-15 The swing-trading research is inspiration, not a rulebook

- **Said:** "Showing you all the swing trading ideas and reserash are ti help you think if
  features and actions and structure we can build to make using the product steer in the right
  direction whej using it".
- **Context:** the research the owner supplied shapes features, actions and structure. It is
  not a list of studies to run or rules to enforce.
- **Governs:** the whole project; the [overview](overview.md).

### 2026-11-15 The AI must be a research partner, not an instruction follower

- **Said:** "the ai also needs to know what to suggest. How to interpret data along the way,
  suggest tests to run, suggest data to look at." And: "It needs to be a partner in the process
  not just follow word for word instructions." And: "Think and plan what we can do so in any
  and all situations the ai is smart and understands and always learns and evolves".
- **Context:** the owner gave two examples and said they are only examples: a sharp drawdown
  should prompt a check of the one asset against the whole market and the macro data of that
  time; an edge that appears only in some periods should prompt regime detection. The project
  must teach a method and supply diagnostics, tools, context data and memory, not a script.
- **Governs:** the whole project; [AI assistants](components/ai-assistants.md).

### 2026-11-15 Adopt everything RD-Agent has, memory first

- **Said:** "Yes adopt and utilise everything rd agents has especially memory of the past".
- **Context:** answers an agent's question whether to use all of RD-Agent's own abilities
  instead of rebuilding them in ALPHA. RD-Agent stays an engine the AI partner calls.
- **Governs:** [RD-Agent](components/rd-agent.md).

### 2026-11-15 Build the thin spine clean, then switch over

- **Said:** "Clean spine."
- **Context:** answers an agent's question: keep carving the old code down piece by piece, or
  write the small new core fresh in this repository, point the screens at it, and delete the
  old lanes as each is replaced. The owner chose the second. The owner also agreed to set up
  private remote access to the Dell so the screens can be opened from a phone.
- **Governs:** the whole project; the [overview](overview.md#the-target-shape).

### 2026-11-15 The file system is always kept up to date

- **Said:** "Ensure file systsem is always being updated and accounted for".
- **Context:** said while approving the clean spine. Every change of direction, new part and
  removed part is written into the project layer in the same piece of work, not afterwards.
- **Governs:** [delivery and agent tooling](components/delivery-and-agent-tooling.md).

### 2026-11-15 Documents can never be stale: enforced by the system, not by an AI's memory

- **Said:** "if the file system is working, we should not have any stale documents"; "take out
  the AI parts where possible"; "we shouldn't ever really have stale files. That's the point of
  the file system."
- **Context:** until now a stale document was only listed, and keeping one current relied on an
  AI remembering. Now each document records a fingerprint of the files it describes. When an AI
  edits a file it is told at once which documents describe it; the check and the pull request
  fail while any document's fingerprint is out of date; one command re-stamps a document after
  it has been re-read. A machine can prove a document is out of date and refuse the work; an AI
  still has to re-read and correct it. The research paper has no staleness rule: this is ours.
- **Governs:** [delivery and agent tooling](components/delivery-and-agent-tooling.md); the rule
  is in [documentation invariants](../invariants/documentation.md#front-matter).
