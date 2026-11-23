# Report

## Step 4: MCP tools
- Removed from `apps/alpha-mcp`: 37 tools in `server.py`, 33 helpers in `_control.py`, the unused classes and aliases in `_types.py`.
- Source lines: `server.py` 1425 to about 710, `_control.py` 1081 to 205, `_types.py` 841 to about 450.
- Deleted `tests/integration/test_research_mcp.py` (423 lines). Edited `test_mcp_server.py` and `test_v3_surface_coverage.py`.
- Proof: `rg -n "research_capture|research_get|create_strategy_project|search_evidence|plan_development_suite|launch_ml_experiment" apps/alpha-mcp` is empty.
- Kept: data tools, job tools, `cancel_development_suite`, `reconcile_development_jobs`.
- Docs: `mcp.md`, `cli-research.md`. Card `ai-tools-connection`: dropped the research MCP proof. Capability matrix regenerated.
- Decision: the commit trailer names no model, because the repository rule is to name none in pushed text.
- Decision: the deleted test pinned the forbidden-verb tool names. The `mcp.md` rule stays; no test pins it now.
