---
name: start-here
description: Find out where the owner is and how to start. Use at the start of a session, or when the owner asks "where am I", "what can I do", "how do I start", "what happened last".
---

# Start here

The owner is a trader, not a coder. Answer in short plain sentences. Never promise a result.

1. Run `uv run alpha next --json`. It reads only; it starts nothing and records nothing.
2. Tell the owner, in this order: what data is here, what was done recently, what waits for
   an answer. Use the words the command gives; add no numbers of your own.
3. Something waits for the owner (an RD-Agent proposal, a decision): show it first.
4. Ask which of the three ways the owner wants, then follow that path:
   - Their own rule: the `test-idea` skill.
   - Their own chart setup: `uv run alpha setup find <spec.toml>`; the example spec is
     `research/examples/setup-find.example.toml`. Then study it, then trade it on paper only.
   - Ideas from RD-Agent: the command `alpha next` names under the third way.
5. No data is stored: give the command `alpha next` prints for getting data. Do not pick
   assets for the owner without asking.

Keep in mind:

- The method is [the playbook](../../../research/PLAYBOOK.md). A result is a research record;
  it is not advice and not an approval.
- Bars from 2024-01-01 on are held back for the owner's confirmation. Say so when a result
  carries that label.
- A command that fails or confuses you is a finding: note it for the report.
