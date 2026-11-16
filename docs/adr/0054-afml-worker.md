# ADR-0054: A pinned AFML worker runs two independent López de Prado libraries side by side

**Status:** Accepted
**Date:** 2026-11-16
**Deciders:** AI build agents, under the owner's decision that the methods of *Advances in
Financial Machine Learning* are added through the community implementations, and the
orchestrator's owner-level ruling of 2026-11-16 on the barrier convention (below)

## Context

ALPHA lacks sample uniqueness and time-decay weights, the sequential bootstrap, a CUSUM event
filter, a triple-barrier label generator and meta-labels (searched in `packages/` on 2026-11-16;
`alpha_validation/barrier.py` scores one trade but generates no labels). The study of candidate
sources (`owner/repo-study/mlfinlab-replications-2026-11.md`, outside git) recommends RiskLabAI
3.2.0 as the primary implementation and quantowl 0.1.6 as an independent second opinion, with the
mlfinlab 0.12.3 public archive as an answer key only.

Facts read from the installed packages on this machine (CPython 3.12.3), not from memory:

- RiskLabAI 3.2.0 requires `statsmodels<0.15`; ALPHA's root lock covers newer Pythons and newer
  statsmodels. quantowl brings numba 0.68.1, which ALPHA's root lock does not have. Both resolve
  together with ALPHA's own numpy 2.4.6, pandas 2.3.3, polars 1.41.2 and SciPy 1.17.1.
- quantowl is not on PyPI; tag `v0.1.6` is commit `37a17de8f519e7c2dae3d609a3e078c4c83de22e`.
- Both libraries read **closes** for the barrier race. RiskLabAI compares log returns
  (`RiskLabAI/data/labeling/labeling.py:triple_barrier`), quantowl simple returns
  (`quantowl/labeling.py:_scan_first_touch`), so they disagree only when a close lies between the
  two barrier conventions. RiskLabAI's scan cannot take time-zone-aware times.
- Both libraries' volatility (Snippet 3.1) includes the event bar's own close and looks back one
  calendar day, which on daily bars skips a bar.
- With the same seed, both sequential bootstraps draw the same labels: each takes one numpy
  `default_rng` uniform per draw and inverts the same cumulative probabilities (checked over
  2,200 seeds, and held by a test against hand-worked probabilities).

## Decision

1. **One new worker, `workers/afml`**, its own `pyproject.toml` and `uv.lock`, CPython 3.12,
   strict mypy, CI job `afml-worker` on changes to `workers/afml/` (glue rule 5). RiskLabAI and
   statsmodels are pinned from PyPI with checksums; quantowl by commit. `[tool.uv] exclude-newer`
   keeps every locked release at least two weeks old (rule 4). Neither library is edited (rule 3)
   or added to the root lock.
2. **One thin adapter** (`alpha_afml_worker`): Polars in, Polars and Parquet out, a checked input
   contract, and the command `alpha-afml-worker` (rule 6).
3. **Two libraries, one answer.** Where both implement a value, it leaves the worker only when
   they agree to 1e-10, or exactly for draws and event lists; otherwise `AgreementError`. A value
   only one of them implements is not offered until a hand parity test covers it.
4. **ALPHA's barrier convention is the default and the headline**, by the orchestrator's
   owner-level ruling of 2026-11-16: a barrier is touched when the bar's high or low reaches it;
   the trade is decided at the event bar's close and entered at the next open; a gap through a
   barrier exits at the open; a bar reaching both barriers is ambiguous, scored stop-first, with
   the optimistic reading reported beside it. This matches `alpha_validation/barrier.py`. It is
   written in the adapter because neither library reads highs and lows. The libraries' close
   convention stays available as `basis="close"`, for parity only.
5. **Causal inputs written by ALPHA.** Barrier widths and CUSUM thresholds use an EWM volatility
   of one-bar log returns from closes strictly before the event bar; nothing is fitted on the
   sample; the vertical barrier is a bar count; an unfinished label is open, never guessed.
6. **ALPHA stays the judge and the record (rule 7).** The worker writes files and a summary;
   nothing it returns is a verdict or reaches the ledger without ALPHA code reading it.

## Options considered

| Option | Verdict |
|---|---|
| Add RiskLabAI to the root install | Rejected: its statsmodels and Python ceilings would bind all of ALPHA |
| One library only | Rejected: young code; a second implementation catches its mistakes |
| Copy the mlfinlab archive's code | Rejected: rule 3, and it does not run on pandas 2 |
| Use the libraries' close convention as the headline | Rejected by the owner-level ruling: stops trigger inside the bar |
| **A worker with both libraries and a parity rule** | **Chosen** |

## Consequences

- Wave 1 items 1 and 2 exist as worker functions with parity and truncation tests, called by
  `alpha labels barrier|weights` (glue rule 6's smoke test: `tests/smoke/test_afml_labels_smoke.py`).
- ALPHA's `barrier.py` and the worker's high/low labels are two writings of one convention. On the
  same entries they agreed on all 506 SPY and 557 BTC daily events (2026-11-16), ambiguous bars and
  the optimistic reading included. One designed difference remains: the worker reads each bar's
  open, so a bar that opens beyond a barrier decides it; `barrier_outcome` has no opens and would
  call that bar ambiguous (stop-first). It occurred on neither series; the smoke test counts it.
- Negative time-decay weights (book: forget the oldest labels) are refused: RiskLabAI does not
  implement them.
- The truncation tests live in `workers/afml/tests/test_labels.py`, mirrored as the future-poison
  guard `tests/bias_guards/test_afml_labels_future_poison.py` (with a leaky twin it must reject);
  both need the installed worker, so they run in the `afml-worker` job and skip elsewhere.
- Update, same pull request (2026-11-16): wave 1 items 3 to 6 followed in this pull request,
  each with its parity test: purged CV (`cv.py`, with ALPHA's brute-force leak checker), fractional
  differencing (`fracdiff.py`, d fitted on training data only), importance (`importance.py`, quantowl
  on the checked folds; RiskLabAI's unpurged MDA and SFI never used) and statistics (`stats.py`,
  compared with ALPHA's PSR, DSR and PBO in `tests/integration/test_afml_stats_parity.py`).

## Implementation anchors

- `workers/afml/pyproject.toml`, `workers/afml/uv.lock`.
- `workers/afml/src/alpha_afml_worker/uniqueness.py:average_uniqueness`, `time_decay`,
  `sequential_bootstrap`; `labels.py:prior_volatility`, `find_events`, `barrier_labels`.
- `workers/afml/tests/test_uniqueness.py`, `test_labels.py`, `test_cli.py`.
- `scripts/gate_components.py` (`afml`), `.github/workflows/ci.yml` (`afml-worker`).
- The register: [outside projects](../reference/project/outside-projects.md).
