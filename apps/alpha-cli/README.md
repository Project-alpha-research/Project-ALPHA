---
owner: command line application
sources:
  - apps/alpha-cli/src/**
  - apps/alpha-cli/pyproject.toml
---

# alpha-cli: code map and change loop

Where things are in the `alpha` command line, and how a change to it is checked. The routing page is [CONTEXT.md](CONTEXT.md).

## Code map

The `alpha` CLI composes data, strategies, the engine, validation, research and models, and owns the SQLite control store (projects, jobs, evidence, owner
receipts). It may import every package below it; nothing but the surfaces' public seams may import it, and the web app and MCP server call it as a subprocess.
It must never grant authority the owner did not give, and never route live capital.

Code: `apps/alpha-cli/src/alpha_cli/` (`_name.py` = private helper; `*_cmds.py` = command group, wired in `main.py`).
The module list is made from the code, never written here: `uv run python scripts/fs.py map apps/alpha-cli [--find WORDS]`
prints each module's path, line count and docstring line. Tests share the module's name prefix in `tests/unit/`.

- Forward follow (`follow_*`) writes only `<home>/forward/`; no research module may import it. Nightly steps run real commands in child processes.
- Idea cards live under `<home>/ideas/`; the spec link is in no identity. Published: `research/library/published/`; private notes: `<home>/library/private/`.
- The `research_*` modules (research cases) are being removed (owner decision 2026-11-23); `ml_progress` keeps its own time file.
- Rule-test reading text lives in `test_cmds`, `results_cmds`, `next_cmds` and `nightly_run`; the maths is pure, in `spine/reading` and `spine/book`.

Many integration tests in `tests/integration/` use the same prefixes. Shared helpers live once: `_cli_json` (JSON emit and
option parsing), `_research_artifact_io` (D1/D2 artifact publication and reads) and `alpha_core.atomic` (atomic file writes);
do not add a private copy.

- Check: `uv run python scripts/gate.py check`. Engine imports stay lazy; `import alpha_cli` stays light (`test_public_seams.py`).
  RD-Agent: thirds, ties, gaps `_rdagent_membership`; identity, rescaling `_rdagent_identity`; inference `_rdagent_{stats,twins}`; `_rdagent_stability`.
- [Rule-test periods](../../research/tools/rule-test.md) · [Data health](../../research/tools/data-health.md)
  · [Tools](../../docs/reference/project/components/toolbox.md): market, risk, trades, costs, intervals.
- Setup trades report percent and stop-risk returns. [RD-Agent journeys](../../research/tools/rdagent-journey.md) and proposals explain verdicts and checks.
- Tests for the changed sub-area (above); a bias guard for any new data read; an integration test through the real command for any new command.

## Change loop

- A new or changed command: the command reference is made on demand (`uv run python scripts/commands_reference.py`).
  If the web or MCP surface exposes it, also run `uv run python scripts/check_openapi_operations.py --write`.
- The owning document: the sub-area's `docs/reference/invariants/cli-*.md` file (`alpha context` includes offline Bybit import/read:
  [data layer § Context data](../../docs/reference/project/components/data-layer.md#context-data));
  no stored command page to update.

## Approvals bind structure

- Owner approvals bind code structure, not bytes ([ADR-0045](../../docs/adr/0045-approvals-bind-code-structure.md)): editing
  `research_intake.py`, `research_runtime.py`, `research_crypto_data.py` or `research_crypto_runtime.py` invalidates them only
  when behaviour changes (comments and formatting are free); every `alpha_cli` file the daily rule lane runs through
  (control store, owner auth, `research_runtime.py` and more; see the native file) feeds daily native rule approvals
  the same way, and `tests/unit/test_daily_guard_boundary.py` fails when a bound file imports an unbound one.
  `_structural_digest.py` itself is guarded: any edit invalidates every approval.

## Also read
| Read | Section | When |
|---|---|---|
| [architecture](../../docs/ARCHITECTURE.md) | Runtime data-directory layout | adding a folder under the data directory |
| [bounded discovery workflow](../../docs/operations/bounded-research-workflow.md) | — | running a bounded discovery or frozen-rule study |
| [local operations runbook](../../docs/operations/README.md) | — | daily Tiingo data |
| [toolbox](../../docs/reference/project/components/toolbox.md) | — | `alpha tool`, `toolbox/`: adding a test, its honesty rules, what is not built yet |
