# Report: remove `alpha suite`

## Removed
- Source: `suite_cmds.py`, `_suite.py`, `_suite_actions.py`, `_suite_types.py`, `suite_catalog.py` (2,742 lines); `suite` mount in `main.py`; `suite` in `_OWNER_ONLY_ROOTS`.
- Tests: five suite unit files, `tests/integration/test_suite_cli.py`, `tests/fixtures/suite_plan_golden.json`. In `test_v3_release_coverage.py` the suite-only tests and helpers are gone; the control-store and project CLI tests stay. `test_cli_entry_lazy_groups.py` no longer expects `suite`.
- Docs: Suites section of `cli-runs.md`; `alpha suite run` line in the Monte Carlo guide; `strategy-development` card in `capabilities.toml` and its mention in `strategies-and-signals.md`. No triage row existed. `commands.md` and `STATUS.md` regenerated.
- `pyproject.toml`: five module names removed from the forbidden list.

## Decisions
- `tests/unit/test_filesystem_contract.py`: the cram ceiling for `cli-runs.md` lowered 47 to 45, as the test demanded.
- Kept (per brief): `ControlStore` suite methods, `cancel_development_suite`, `project job-*`, job kind `validation_suite`.
- Left alone: ADRs, archive, other tasks' work folders, `docs/governance` risk register, `docs/roadmap/refactors`, `owner-decisions-6.md` (history).

## Proof
The brief's `rg` returns only `cancel_development_suite` (MCP tool) and `validation_suite` (job kind) names and test strings for them. `uv run alpha --help` lists no `suite`.
`lint-imports`: 14 kept, 0 broken. `gate.py check --base origin/main`: all passed.
Note: `tests/smoke` shows 44 setup errors in this container; they also occur on unchanged main.
Fail-first: deletion change, so no new behaviour; the removed `suite` expectation in the lazy-groups test would fail against the old mount.
