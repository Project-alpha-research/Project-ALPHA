# Brief: the reserved date has one home in code

**Build class:** standard

## Task

The date that starts the reserved period (2024-01-01) is defined in more than one place:
`apps/alpha-cli/src/alpha_cli/toolbox/reserve.py` (`RESERVED_DAY`, `RESERVED_START`),
`packages/alpha-data/src/alpha_data/context/daily_funding.py` (its own `RESERVED_DAY`), and
`workers/rdagent/alpha_factor_data.py` (the date hard-coded as text in two checks; also named
in prompt wording in `workers/rdagent/alpha_factor_judge.py`). If one is changed and the others
are not, parts of the system disagree about which data is held back, and nothing notices. Give
the date one home and make every other use read it or be proven equal to it.

## Read first

| Read | Section | When |
|---|---|---|
| `docs/reference/project/reserved-period.md` | whole | always |
| `docs/reference/invariants/engineering.md` | Import layers; Subprocess boundary | always |
| the four files named above | every use of the date | always |
| `workers/rdagent/CONTEXT.md` | what the worker may import and why it cannot import `alpha_cli` | always |
| `.importlinter` or the import-contract config (`uv run lint-imports`) | which package may import which | always |

## Decision already made

1. **One home, at the lowest layer that every user may import.** Put `RESERVED_DAY` (a date)
   and `RESERVED_START` (its ISO text) in `packages/alpha-core/src/alpha_core/` (a small module
   such as `reserve.py`), with a one-line docstring-free comment saying what it is and that
   changing it needs the owner. `alpha_data.context.daily_funding` and `alpha_cli.toolbox.reserve`
   import it from there (keep `alpha_cli.toolbox.reserve` as a thin re-export so existing
   imports keep working; do not duplicate the value).
2. **The RD-Agent worker** runs in its own environment. If the worker can import `alpha_core`
   (check how its environment is built and what it already imports), it imports the constant.
   If it cannot, the worker keeps ONE named constant in one worker module (no literal date
   anywhere else in `workers/rdagent/`), and a test in the root environment reads the worker
   file as text and proves its value equals `alpha_core`'s. Prompt wording that mentions the
   date is built from the constant, not typed.
3. **A guard test**: a repository scan that fails if the literal `2024-01-01` (or
   `date(2024, 1, 1)` / `2024, 1, 1`) appears in source under `packages/*/src`, `apps/*/src` or
   `workers/` anywhere except the one home (and the worker's one constant, if case 2 applies).
   Tests, fixtures, docs and data files are excluded. Put it in an ordinary unit-test file
   (not under `tests/bias_guards`).
4. **No behaviour change.** Same date, same comparisons (`<` versus `<=` exactly as today —
   list each comparison and confirm it is unchanged), same error texts. Hash-bound packages
   (`packages/alpha-research/src`, `packages/alpha-validation/src`) are not edited; if either
   contains the literal date, do not touch it: report the file and line, and let the guard
   test exclude that exact path with a comment saying why.
5. Update `docs/reference/project/reserved-period.md` (the "more than one home" defect is
   fixed: say where the one home is and how the worker is kept equal), `toolbox.md` if it
   mentions the home, and the workspace `CONTEXT.md` files only if a sentence becomes untrue.
   When work lands, a page that listed it as a known defect is updated in the same change.
   The duplicate definitions are deleted: say how many lines.

## Files

Edited:
- `apps/alpha-cli/src/alpha_cli/toolbox/reserve.py`
- `packages/alpha-data/src/alpha_data/context/daily_funding.py`
- `workers/rdagent/alpha_factor_data.py`
- `workers/rdagent/alpha_factor_judge.py`
- `docs/reference/project/reserved-period.md`

New:
- `packages/alpha-core/src/alpha_core/reserve.py`
- `tests/unit/test_reserved_date_one_home.py`

This decision overrides the standing rule for: any other source file under `packages/alpha-core`,
`packages/alpha-data`, `apps/alpha-cli` or `workers/rdagent` that the scan finds holding the
literal date (replace it with the import; list it); `packages/alpha-core/CONTEXT.md`; any living
document `scripts/fs.py stale` reports because of your edits (verify with a real text change or
`--reason`). If a named file does not exist, use the real one. List each in the report; do not
stop to ask; where a rule is open choose the more cautious reading and state it.

## Do not touch

`packages/alpha-research/src`, `packages/alpha-validation/src`, `tests/bias_guards`,
`tests/oracles`, `.semgrep/`, `.github/`, `.claude/`, `.agents/`, `scripts/`, `uv.lock`,
`workers/rdagent/loop_guard.py`, `workers/rdagent/model_gateway.py`. The date itself. Any
comparison operator. No `nosemgrep`, `noqa`, `type: ignore`, `vars(`, `__doc__`, `inspect`,
`.__dict__`. Tests fully type-annotated; no test file named `*fixups*` or ending `_<N>.py`.

## Checks

- `uv run pytest -q tests/unit/test_reserved_date_one_home.py`
- `uv run lint-imports`
- `uv run pytest -q tests/unit -k "reserve or reserved or funding or rdagent or toolbox or code_size or filesystem or docs_links or import"`
- `uv run pytest -q tests/bias_guards`
- `uv run python scripts/fs.py stale`
- `uv run python scripts/gate.py check --base origin/main`

## Report

Every place the date was found (file, line, comparison). The one home. How the worker is kept
equal (import or proven-equal constant) and why. The guard test's scan rule and exclusions.
Lines deleted. Anything in a hash-bound package. Every file outside the list. What is unverified.
