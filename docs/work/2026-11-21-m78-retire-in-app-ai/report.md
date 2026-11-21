# Report: retire the in-app AI (m78)

Size: 82 lines added, 10,736 lines removed (85 files; most of the added lines are regenerated OpenAPI and docs).

## Deleted (each proved unreached by kept code)
- CLI: `codex_{environment,investigation,policy,rpc,session}.py`, `investigation_{case,comparisons,lifecycle,report,workspace,workspace_cmds,workspace_contracts,workspace_data}.py`,
  and `comparison_acquisition{,_evidence,_worker}.py`. The last three only take an investigation `Case`, so they went with it.
- Commands: `alpha research investigations …`; `alpha research diagnostic investigate|investigation-tool|acquisition-plan|acquire-comparisons`.
- MCP: `investigation_server.py` (nothing else registered it; only the deleted Codex policy started it).
- Web: `api/investigations.py`, `_investigations.py`, router include, the `research investigations` env rules in `_catalog.py`; OpenAPI, `generated.ts`, governance classification and matrix regenerated.
- Frontend: CodexBench, AiConsole (Standalone Sandbox), AssistantDock, RunInvestigation, `codexBenchModel`, `api/investigations.ts`, their tabs and buttons, CSS, and the Playwright specs/harness steps for them.
- Other: `scripts/playwright_investigation_fixture.py` (only served the deleted specs), the capability `ai-investigations`, `docs/operations/codex-investigations.md`, 20 unit test files of deleted code.
- Docs text fixed: cli-assistant, mcp, web-research, web-api, ai-assistants, alpha-cli README, operations README, commands.md, STATUS.md, capability trace.

## Kept, and why
- `alpha tool …`, stored tool results, the toolbox, MCP front door, RD-Agent, `research_suggestions.suggest_investigations` (a kept research-case command).
- The assistant backend (`assistant_*.py`, `api/assistant.py`, `alpha assistant …`): the brief does not name it. It has no screen now. Retire it in a later step.
- Context-packet and note routes (`research context`, `research note`): the research-case lane still uses them. The notes screen (CodexBench) is gone; the notes stay reachable by CLI and MCP.
- "Investigate this run" opened only the deleted investigation. No kept feature lost its door.
- Archived ADRs 0022 and 0033 are history; not edited.

## Decisions
- `research_diagnostic_cmds.py`: cut four commands only; the research-case lane had no import of investigation modules.
- Removed stale exemption entries in `test_research_reads_are_cut.py`, `test_structural_digest.py`, `_tiers.py`, `test_platform_tier.py` for deleted files. No guard was weakened.
- Capability proof name in `capabilities.toml` updated to match the renamed edge-real test.
- No fail-first test: a deletion-only build adds no behaviour.

## Needs the orchestrator
- `tests/unit/test_code_size.py` stays red (protected `.claude/code-size-baseline.json`): lower `apps/alpha-cli/src/alpha_cli/research_cmds.py` to 3537; other entries listed in the test output of the last run (see the pull request).
- `scripts/gate_test_durations.json` (protected `scripts/`) still lists deleted test files.
- Two process-group tests error in this sandbox (`test_assistant_cleanup … parent_death`, `test_durable_job_lease … exited_leader`); not touched by this change.
