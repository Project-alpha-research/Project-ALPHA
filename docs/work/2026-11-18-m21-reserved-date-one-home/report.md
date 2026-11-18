# Build report: m21-reserved-date-one-home

## Changed files

`alpha_core.reserve` is the canonical home for `2024-01-01`. The isolated Python 3.11 factor runtime has no ALPHA packages, so it uses one worker constant. The root test reads that assignment and checks it against core. The build has one pending test-fixture change that requires scope approval.

- `packages/alpha-core/src/alpha_core/reserve.py` defines `RESERVED_DAY` at line 4 and derives `RESERVED_START` at line 5.
- `apps/alpha-cli/src/alpha_cli/toolbox/reserve.py` re-exports both names and removes the two definitions formerly at lines 5–6.
- `packages/alpha-data/src/alpha_data/context/daily_funding.py` removes the duplicate definition at old line 23. The requested end date at line 32 and each funding row at line 55 still use `>=`.
- `workers/rdagent/alpha_factor_data.py` defines the worker constant at line 20. Funding and panel checks at old lines 84 and 101 still use `.ge()`, equivalent to `>=`, with UTC timestamps. The README wording at old line 34 derives its year from the constant.
- `workers/rdagent/alpha_factor_judge.py` renders the proposer wording at line 551 from the worker constant.
- `tests/unit/test_reserved_date_one_home.py` checks worker equality and scans Python source, stubs, and source templates under `packages/*/src`, `apps/*/src`, and `workers/` for the ISO literal and comma-separated date components. It excludes tests, fixtures, docs, data files, virtual environments, the core module, and the worker assignment value. The scan found no literal in either hash-bound package.
- `docs/reference/project/reserved-period.md` records the canonical home, worker isolation, and guard.
- `docs/reference/project/components/toolbox.md` replaces the known-defect notice with a link to the shared date.
- `apps/alpha-cli/CONTEXT.md` refreshes its verification stamp.
- `packages/alpha-core/CONTEXT.md` refreshes its verification stamp.
- `packages/alpha-data/CONTEXT.md` refreshes its verification stamp.
- `workers/rdagent/CONTEXT.md` refreshes its verification stamp.
- `docs/reference/invariants/cli-investigation-tools.md` refreshes its verification stamp.
- `docs/reference/invariants/core.md` refreshes its verification stamp.
- `docs/reference/invariants/data.md` refreshes its verification stamp.
- `docs/reference/invariants/workers.md` refreshes its verification stamp.
- `docs/verified-reasons.txt` records the eight `fs.py verify --reason` stamps.

Three local definition lines were removed. The four funding and panel cutoff checks, their error messages, and both rendered worker strings matched the originals. Existing CLI comparisons also retained their operators.

| Operator | Existing CLI locations |
|---|---|
| `>=` | `toolbox/inputs.py:52,95`, `rdagent_rule_family.py:110–111`, `rdagent_factor_eval.py:197,210,733`, `_rdagent_membership.py:88,495`, `_rdagent_judge.py:224,490,528,722,970`, `rdagent_journey.py:284–285` |
| `<` | `_rdagent_membership.py:115`, `_rdagent_judge.py:385`, `figures/rdagent_journey_figures.py:31,111` |
| `<=` | `_rdagent_membership.py:115` for the last available day |
| `!=` | `_rdagent_ledger.py:178,237` |

## Checks

| Command | Status | Exit code |
|---|---|---:|
| `uv run pytest -q tests/unit/test_reserved_date_one_home.py` before the source edits | FAIL | 1 |
| `uv run pytest -q tests/unit/test_reserved_date_one_home.py` after the source edits | PASS | 0 |
| `uv run lint-imports` | PASS | 0 |
| Requested broad unit selection | UNVERIFIED | — |
| Broad unit selection with sandbox filters, serial and parallel attempts | UNVERIFIED | 130 |
| Focused reserve and funding tests | PASS | 0 |
| Existing prompt and restored-context tests | FAIL | 1 |
| Documentation and filesystem tests with a temporary Git index | PASS | 0 |
| `uv run pytest -q tests/bias_guards` | PASS | 0 |
| `uv run python scripts/fs.py stale` | PASS | 0 |
| `uv run python scripts/gate.py check --base origin/main` | PASS | 0 |
| `uv run ruff check` on all six changed Python files | PASS | 0 |
| `uv run ruff format --check` on the same files | PASS | 0 |
| `uv run mypy` on all five changed source files | FAIL | 1 |
| `uv run mypy` on the four changed source files excluding the worker judge | PASS | 0 |

The new guard found all five original literal sites before the source edits. Four existing prompt cases now fail because their fixture strips the judge’s imports and does not inject `RESERVED_START`. All seven prompt and restored-context cases passed when I supplied the actual worker constant in memory. The fixture file still needs the one-line change. Root mypy reported the same 19 import and subclass errors on the original judge and the edited judge.

## UNVERIFIED

- The full broad unit selection requires sockets and FastAPI `TestClient`. The filtered attempts stalled in the RD-Agent web test’s async event loop and were interrupted. The parallel run also recorded gateway state-directory errors and denied socket binds in native and factor-launch cases.
- Tests that require configured RD-Agent source, factor, or stock runtime paths remain unverified because those paths were unset.
- Browser, smoke, and network checks were outside the sandbox run.

## Deviations

Scope-related documentation updates are listed above. The filesystem check used a temporary Git index because the new files are untracked. The broad test filter missed cases that open sockets through launch helpers. All changes remain uncommitted.

## Questions

May I add `RESERVED_START` to the fixture’s existing import-injection list in `tests/unit/_rdagent_support.py`? That file is outside the brief’s allowlist. The one-line change would preserve all existing assertions.

## Fix round 1

## Changed files

- `workers/rdagent/alpha_factor_data.py` renders the reserve wording through `current_universe()`, using the existing worker constant.
- `workers/rdagent/alpha_factor_judge.py` gets panel dates through that helper. The prompt text and panel-read counts are unchanged.
- `docs/reference/project/reserved-period.md` uses a core source glob that includes the canonical module and satisfies the filesystem check before staging.
- `workers/rdagent/CONTEXT.md` refreshes its verification stamp.
- `docs/reference/invariants/workers.md` refreshes its verification stamp.
- `docs/verified-reasons.txt` records both stamp updates.

## Checks

All five reported failures now pass without test edits or a temporary Git index.

| Command | Status | Exit code |
|---|---|---:|
| Focused reproduction before the fix | FAIL, 5 failures reproduced | 1 |
| Same focused check after the fix | PASS, 8 passed | 0 |
| Related unit tests | PASS, 188 passed, 4 skipped | 0 |
| `uv run pytest -q tests/unit/test_reserved_date_one_home.py` | PASS | 0 |
| `uv run lint-imports` | PASS | 0 |
| `uv run pytest -q tests/bias_guards` | PASS, 207 passed, 4 skipped | 0 |
| `uv run python scripts/fs.py stale` | PASS, 0 stale | 0 |
| `uv run python scripts/gate.py check --base origin/main` | PASS | 0 |
| Ruff lint and format checks on changed Python files | PASS | 0 |
| Standalone mypy on all changed source files | FAIL, same 19 worker import and subclass diagnostics as baseline | 1 |
| Standalone mypy on the other four source files | PASS | 0 |
| Full broad unit selection | UNVERIFIED | — |

## UNVERIFIED

The full broad selection includes socket and FastAPI `TestClient` cases that require verification outside the sandbox. Optional runtime cases skipped because the RD-Agent runtime, PyTables, or the AFML worker was unavailable.

## Deviations

None. All edits remain uncommitted.

## Questions

None.
