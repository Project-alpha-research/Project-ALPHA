# Brief: remove `alpha suite` (plan step 5)

Branch: `chore/m148-remove-suite`. Start from `origin/main`.
Rules: `docs/work/2026-11-21-common-build-rules/brief.md` on main (read it first), and the first three paragraphs of
`docs/work/2026-11-24-m143-remove-research-case-mcp-and-suite/brief.md` on branch `work/m102-briefs` (what never to delete, the
protected paths, the import-linter list, the checks before the pull request, the short task `brief.md`, the report). They apply
here unchanged. This is a DELETION change. The web screens, web routes and MCP tools that called `alpha suite` are already gone
on main, so nothing calls it now.

## Delete

- `apps/alpha-cli/src/alpha_cli/`: `suite_cmds.py`, `_suite.py`, `_suite_actions.py`, `_suite_types.py`, `suite_catalog.py`.
- The `suite` mount in `main.py` and the `suite` entry of `_OWNER_ONLY_ROOTS` in `catalog.py`.
- Tests: `tests/unit/test_suite_planner.py`, `test_suite_executor.py`, `test_suite_plan_golden.py` (and its golden files),
  `test_suite_plan_builders.py`, `test_suite_catalog.py`; `tests/integration/test_suite_cli.py`. Edit
  `tests/unit/test_cli_entry_lazy_groups.py` so it no longer expects `suite`.
- Docs: the suite part of `docs/reference/invariants/cli-runs.md`; any other living page that tells the reader to run
  `alpha suite` (search `docs`, `research`, `workflow`, `apps/*/README.md`, `apps/*/CONTEXT.md`); leave `docs/adr`, `docs/archive`
  and other tasks' `docs/work` folders as they are.
- `docs/roadmap/capabilities.toml`: delete the card `strategy-development`, and remove deleted test files from any other card's
  proof list. If the triage sheet `docs/roadmap/triage-2026-11.md` has a row for it, delete the row.
- `pyproject.toml`: remove the deleted module names from the forbidden list of the contract "kept features stand off the old
  research-case machinery".

## Keep

- `ControlStore.create_suite_job` and the other suite methods of `control_store.py` (a later step deletes the whole file).
- The MCP tool `cancel_development_suite` and everything under `alpha project job-*` (jobs are a kept feature).
- Anything the searches below still find a caller for: keep it and say so in the report.

## Proof (put the output in `report.md`)

`rg -n "_suite\b|_suite_actions|_suite_types|suite_cmds|suite_catalog" apps packages scripts workers tests --glob '!*.md'`
must return only `control_store.py` method names and files you delete. `uv run alpha --help` must not list `suite`.

## Tests

The plan's list: `tests/unit/test_cli_entry_lazy_groups.py`, `tests/integration/test_control_cli.py`,
`tests/unit/test_commands_reference.py`, `tests/integration/test_mcp_server.py`, plus the checks named in the m143 brief.
