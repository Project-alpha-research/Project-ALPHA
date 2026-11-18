# Build report: m19-three-known-defects

## Changed files

- [apps/alpha-cli/src/alpha_cli/_runner.py](apps/alpha-cli/src/alpha_cli/_runner.py:679) — Fixed the `None` versus date comparison. Missing fields sort first, and the serialized fingerprint rows retain their original bytes.
- [apps/alpha-cli/src/alpha_cli/toolbox/families/resampling.py](apps/alpha-cli/src/alpha_cli/toolbox/families/resampling.py:136) — Replaced the full paths-by-bars allocation with bounded chunks from one seeded stream. At 7,500 returns × 2,000 paths, peak traced memory fell from **480.13 MB to 128.02 MB** and runtime from **2.16 s to 0.90 s**. Observed, median and 95th-percentile drawdowns matched exactly.
- [apps/alpha-cli/src/alpha_cli/toolbox/inputs.py](apps/alpha-cli/src/alpha_cli/toolbox/inputs.py:309) — Uses the rule test’s full-history buy-and-hold calculation for attribution. External benchmarks start at the first shared open and include point-in-time dividends in their cache identity.
- [apps/alpha-cli/src/alpha_cli/toolbox/families/market.py](apps/alpha-cli/src/alpha_cli/toolbox/families/market.py:29) — Switched attribution from raw opens to dividend-inclusive benchmark returns. Version 2 prevents reuse of cached price-only results.
- `tests/unit/test_source_fingerprint_ordering.py` — Reproduced the crash for announce, record and pay dates. Both input orders now give the expected fingerprint. Three previously sortable series matched the `origin/main` encoding byte for byte.
- `tests/unit/test_toolbox_resampling_checks.py` — Added the peak-memory test and compared chunk sizes of 1, 7 and 31 paths against one validated draw.
- `tests/unit/test_toolbox_runner.py` — Checked dividend entitlement, delayed payment, shared-bar alignment and cache invalidation against hand-built benchmark levels.
- `tests/unit/test_spine_tools.py` — Updated the attribution version assertion and the cross-asset fixture to compare equivalent opens at engine precision.
- `tests/fixtures/toolbox_results.json` — Added the dividend case. On the same strategy, beta moved from **0.487243613 to 0.497129678** and annual alpha from **−10.1512% to −11.0194%**. The earlier no-dividend fixture and drawdown references still pass at `rel=1e-9, abs=1e-12`.
- `docs/reference/project/components/toolbox.md` — Identifies the full-history dividend basis for market exposure.
- `research/tools/attribution-regimes-changepoints.md` — Corrected the benchmark description and payment timing.
- `docs/reference/invariants/cli-investigation-tools.md` — Documented the benchmark period and external-dividend cache inputs.
- `apps/alpha-cli/CONTEXT.md` — Reverified CLI routing and package boundaries.
- `docs/reference/invariants/cli-runs.md` — Reverified the run-identity rules.
- `docs/reference/project/reserved-period.md` — Reverified the reserved-period labeling rule.
- `research/tools/resampling-checks.md` — Reverified parity with the classical IID simulation.
- `docs/verified-reasons.txt` — Recorded the reasons for the four verification-only updates.

## Checks

| Command | Status | Exit code |
|---|---|---:|
| `uv run pytest -q tests/unit/test_source_fingerprint_ordering.py` | PASS · 6 passed | 0 |
| Targeted toolbox runner, spine tools and resampling tests | PASS · 65 passed | 0 |
| `uv run pytest -q tests/unit -k "toolbox or fingerprint or runner or spine or code_size or filesystem or docs_links"` | UNVERIFIED in full | — |
| Same unit selection with the three sandbox-dependent cases deselected | PASS · 558 passed, 1 skipped | 0 |
| `uv run pytest -q tests/bias_guards` | PASS · 207 passed, 4 skipped | 0 |
| `uv run python scripts/fs.py stale` | PASS · 120 checked, 0 stale | 0 |
| `uv run python scripts/gate.py check --base origin/main` | UNVERIFIED in full | — |
| Same gate with `test_c04_web_metric_basis.py` deselected | PASS | 0 |
| `uv run ruff check` on all eight changed Python files | PASS | 0 |
| `uv run ruff format --check` on the same files | PASS | 0 |
| `uv run mypy` on all four changed source files | PASS | 0 |

## UNVERIFIED

- The broad unit selection includes a web-figure traversal test that uses FastAPI `TestClient`. Two native-supervisor tests reached a Unix-socket bind and received `PermissionError`. The sandbox-safe rerun excluded those three cases.
- The unfiltered gate includes `tests/integration/test_c04_web_metric_basis.py`, which uses `TestClient`. Smoke and browser checks were outside the sandbox run.
- Four bias guards skipped because the AFML worker is absent. One unit test skipped because the pinned RD-Agent source is unconfigured.

## Deviations

The same-pattern search found one unsafe sort, in `_runner.py`. The CLI’s dividend control and diagnostic sorts already resolve missing pay dates. The alpha-data pipeline and Alpaca, Tiingo and yfinance adapters sort by required ex-date and action type.

The existing market fixture contained no dividends, so the corrected values were added as a separate case to preserve the original comparison. The earlier M14 and M19 build reports are dated records outside the editable file list. Current behavior is documented in the living references. All changes are uncommitted.

## Questions

None.
