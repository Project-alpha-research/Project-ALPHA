# Brief: three known defects in rule tests and the toolbox

**Build class:** hard

## Task

Three defects were found in review and left open. Fix each at its cause, with a test that
fails first. No statistic's definition changes; results for inputs that worked before stay
the same to within floating-point tolerance (say so with a comparison).

## Read first

| Read | Section | When |
|---|---|---|
| `apps/alpha-cli/CONTEXT.md` | whole | always |
| `docs/reference/project/components/toolbox.md`, `monte-carlo.md` | honesty rules, entries | always |
| `apps/alpha-cli/src/alpha_cli/_runner.py` | `source_fingerprint` and how corporate actions are ordered | defect 1 |
| `apps/alpha-cli/src/alpha_cli/toolbox/families/resampling.py`, `runner.py`, `inputs.py` | `resampling.drawdown_distribution` | defect 2 |
| `apps/alpha-cli/src/alpha_cli/toolbox/families/market.py`, `inputs.py` | the market-exposure entry and its benchmark series | defect 3 |
| the public functions these call in `packages/alpha-validation/src` (read only) | signatures, memory behaviour | defects 2, 3 |
| `tests/fixtures/toolbox_results.json` and the toolbox tests | how results are compared (tolerance, never hashes) | always |

## Decision already made

1. **Crash: two dividends on one ex-date, one without a pay date.** `source_fingerprint` (or the
   ordering it relies on) sorts corporate actions with a key that compares `None` with a date
   and raises `TypeError`. Make the order total and deterministic without changing the
   fingerprint of any series that sorted successfully before: keep the existing key order and
   make a missing date sort in one fixed place (before any date), compared by presence first.
   Tests: the crashing case now returns a fingerprint; the fingerprint is the same whatever
   order the two actions are supplied in; a set of series that worked before gives byte-equal
   fingerprints before and after (pin from `origin/main` behaviour in the test by constructing
   the expected value through the old key on inputs with no missing dates). Search the
   repository for the same pattern (sorting actions or events by an optional date) under
   `apps/alpha-cli/src` and `packages/alpha-data/src`; fix each real case in `apps/alpha-cli`;
   for one in `packages/alpha-data`, fix it too if the file is not hash-bound; list them.
2. **Memory: `resampling.drawdown_distribution` used about 3.7 GB and 32 s on a 30-year daily
   run.** Find where the memory goes (probably all paths materialised at once as a
   paths × bars array, or copies). Bound it: process paths in chunks and keep only what the
   reported percentiles need, calling the same public validated function per chunk with a
   seeding scheme that makes the result independent of chunk size (same paths as one call
   with the same seed, or — if the public function cannot give that — a documented per-chunk
   seed sequence derived from the run seed; then say results differ from before and by how
   much, and update the fixture with the reason). Do not write a new statistic; do not edit
   `packages/alpha-validation/src`. Target: peak extra memory under 500 MB for 7,500 bars ×
   2,000 paths, measured with `tracemalloc` or `resource` in a test marked slow if it takes
   over 10 s (state the measured peak and time before and after in the report). If the target
   cannot be met without changing the validated package, stop at the best safe bound and
   report what the package would need.
3. **Market exposure regresses on the wrong basis.** The market-exposure entry regresses
   strategy returns on benchmark returns built from price-only opens, while the rule test's
   buy-and-hold (since PR #280) includes dividends. Use the same benchmark return basis the
   rule test reports (dividend-inclusive, same bars, same alignment and the same period
   definition) through the shared input helper, so one run cannot show two different
   "markets". State the size of the change on the fixture run (beta and alpha before and
   after) and update the fixture value with the reason in the test. If the entry's card or
   the toolbox page states the basis, correct it.

For all three: results compared with `pytest.approx(rel=1e-9, abs=1e-12)` against the JSON
fixture; never hash floats. Update the tool cards (≤ 40 lines) and `toolbox.md` (≤ 200 lines)
only where a sentence becomes untrue; when work lands, a page that listed it as a known defect
is updated in the same change (search `docs/` and `research/` for these three defects).

## Files

Edited:
- `apps/alpha-cli/src/alpha_cli/_runner.py`
- `apps/alpha-cli/src/alpha_cli/toolbox/families/resampling.py`
- `apps/alpha-cli/src/alpha_cli/toolbox/families/market.py`
- `apps/alpha-cli/src/alpha_cli/toolbox/inputs.py`
- `tests/fixtures/toolbox_results.json`
- `docs/reference/project/components/toolbox.md`

New:
- `tests/unit/test_source_fingerprint_ordering.py`

This decision overrides the standing rule for: existing toolbox test files under `tests/unit/`
(add cases there rather than new files where one exists); other modules under
`apps/alpha-cli/src/alpha_cli/toolbox/`; a non-hash-bound file under `packages/alpha-data/src`
for defect 1's same-pattern search only; tool cards under `research/tools/`; any living
document `scripts/fs.py stale` reports because of your edits (verify with a real text change or
`--reason`). If a named file does not exist, use the real one. List each in the report; do not
stop to ask; where a rule is open choose the more cautious reading and state it.

## Do not touch

`packages/alpha-research/src`, `packages/alpha-validation/src`, `workers/**`,
`tests/bias_guards`, `tests/oracles`, golden files, `.semgrep/`, `.github/`, `.claude/`,
`.agents/`, `scripts/`, `uv.lock`, `apps/alpha-web/**`. Statistic definitions, cost rules,
the reserved date. No pandas inside `toolbox/`. No `nosemgrep`, `noqa`, `type: ignore`,
`vars(`, `__doc__`, `inspect`, `.__dict__`. Functions ≤ 150 lines, files ≤ 1,500 lines; tests
fully type-annotated; no test file named `*fixups*` or ending `_<N>.py`.

## Checks

- `uv run pytest -q tests/unit/test_source_fingerprint_ordering.py`
- `uv run pytest -q tests/unit -k "toolbox or fingerprint or runner or spine or code_size or filesystem or docs_links"`
- `uv run pytest -q tests/bias_guards`
- `uv run python scripts/fs.py stale`
- `uv run python scripts/gate.py check --base origin/main`

## Report

Per defect: the cause (file and line), the fix, the test, and the before/after numbers
(fingerprint equality; peak memory and time; beta and alpha). Same-pattern cases found.
Fixture values changed and why. Every file outside the list. Open readings chosen. What is
unverified.
