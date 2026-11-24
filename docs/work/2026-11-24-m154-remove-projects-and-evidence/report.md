# Report: remove projects and evidence commands (step 6)

## Removed
- Source: `project_cmds.py` lines 1-702 (about 700), `project_workspace.py` 878, `evidence_cmds.py` 176: about 1,750 lines.
- Kept: the `job-*` commands, now `jobs_cmds.py` (still `alpha project job-*`; used by web `_ml.py`, `_invoke.py` and MCP `_invoke.py`).
- Tests: `tests/unit/test_project_workspace.py` deleted (623). `test_control_cli.py` cut to the job cases. Four tests of the
  removed agent brief or project create deleted from `test_control_store.py`, `test_v3_release_coverage.py`, `test_cli_entry_lazy_groups.py`
  (the lazy-groups list also drops `evidence`).
- Config and docs: forbidden list in `pyproject.toml` loses `project_cmds`, `project_workspace`, `evidence_cmds`; baseline entry
  `project_workspace.py::_authority_indexes` removed; card `research-cases` loses `cli: alpha evidence add`; `commands.md` regenerated;
  text fixed in `cli-control-store.md`, `cli-research.md`, `testing.md`, `reserved-period.md`.

## No-caller proofs
- `rg -n "project_workspace|evidence_cmds|project_cmds" apps workers scripts packages pyproject.toml` (not `.md`, not built static):
  only `scripts/gate_test_durations.json` (protected, timing data for deleted tests; harmless).
- `rg -n '"project", "(create|show|version|experiment|link-run|attempt|decide|workspace)' apps`: empty.
- `agent.brief|override-research-gate|reveal-holdout` in code: `ControlStore.get_agent_brief_context` stays (ControlStore goes in step 11).
- Tests searched for the command words and module names; each hit fixed or deleted. `tests/fixtures/retained_coverage_web_fixture.py`
  lists `("project","list")` as an allowed fake command; it is a stub list, left as is. `test_mcp_invoke.py` uses `project list`
  only as sample argv with a mocked run; left as is.

## Expected failure
- `tests/bias_guards/test_agent_brief_future_poison.py` fails to import (`alpha_cli.project_cmds` is gone). Protected; the
  orchestrator deletes it at review.

## Decisions
- Pull request opened ready (not draft), as the schedule said. Commit trailer follows the session attribution.
- `.claude/settings.json` deny entries for `project reveal-holdout` and `override-research-gate` left (dead, harmless; protected).

## Checks
- Run: the plan tests, smoke, code-size, capabilities, status, commands-reference, filesystem contract, `lint-imports`.

What the file system got wrong: nothing
