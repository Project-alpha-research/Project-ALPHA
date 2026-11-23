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

## Step 5: `alpha suite` — KEPT, not deleted
- The no-caller proof fails on main. `rg -n "_suite|suite_cmds|suite_catalog|\"suite\"" apps scripts workers --glob '!*.md'` also finds:
  - `apps/alpha-web/src/alpha_web/_development.py:493,512` (runs `alpha suite plan` and `alpha suite reserve`);
  - `apps/alpha-web/src/alpha_web/api/development.py:212` (runs `alpha suite run`);
  - `apps/alpha-web/src/alpha_web/api/models/projects.py:9` (imports `alpha_cli.suite_catalog`; deleting it breaks web import).
- The web removal is the other builder's branch `chore/m141-remove-research-case-screens-and-routes`. It is not merged.
- The brief says to stay out of `apps/alpha-web` and to KEEP a file with another caller. So no suite file, test or card was removed:
  `suite_cmds.py`, `_suite*.py`, `suite_catalog.py`, the 6 suite test files, `main.py:40`, `catalog.py:43`, card `strategy-development`.
- Next: redo step 5 after m141 merges. Then the proof should return only deleted files.
- Note: `_control.py` in `alpha_mcp` no longer imports `suite_catalog`, so MCP is already clear of it.
