# Brief: remove the research-case MCP tools and `alpha suite`

Two steps of the ordered removal plan for the old research-case machinery. The owner approved it on 2026-11-23.

1. Step 4: delete the research, project, evidence and suite tools from `apps/alpha-mcp`, and `test_research_mcp.py`.
2. Step 5: delete `alpha suite` (`suite_cmds`, `_suite`, `_suite_actions`, `_suite_types`, `suite_catalog`) and its tests.

Kept: data tools, job tools, `cancel_development_suite`, spine and front-door tools.
The full brief is on branch `work/m102-briefs` at this same path. Proofs and line counts are in `report.md`.
