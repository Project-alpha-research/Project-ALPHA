---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/test_cmds.py
  - apps/alpha-cli/src/alpha_cli/results_cmds.py
verified: d9553640074a1138
---

# Research: skills by trigger

Which skill to use for what the owner says. The routing page is [CONTEXT.md](CONTEXT.md).

New here? Run `uv run alpha next`. It shows what data and records exist and three ways to start. It writes nothing.

## Skills by trigger

| The owner says | Skill (`.agents/skills/<name>/SKILL.md`) |
|---|---|
| an idea, a rule, "does X work" | `test-idea` |
| "is this real", or a result is about to be reported | `review-result` |
| "why did it...", or a flag fires | `investigate-surprise` |
| anything answered with a result | `report-to-owner` |
| "what was...", "did we test..." | `answer-from-records` |
| "remember this", or an idea is closed | `record-lesson` |
