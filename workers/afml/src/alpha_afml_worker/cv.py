"""Wave 1 item 3: purged k-fold and combinatorial purged CV that respect label end times.

Observations are rows in time order; row ``i`` is a label running from bar ``starts[i]`` to bar
``ends[i]`` (both inclusive). A training row is *purged* when its interval overlaps any test row's
interval, and *embargoed* when it is among the first ``embargo`` rows that start after the end of a
contiguous test block's labels. ALPHA's brute-force reference below states that rule directly.

RiskLabAI's combinatorial splitter gives the splits, with one test group for k-fold (its own
``PurgedKFold`` ends each test window at the last test label, so labels of varying length would
under-purge). Every split must pass :func:`leaks` (no overlap, embargo respected).
Both libraries are also compared with the reference; each may drop *more* rows than the reference
(conservative), never fewer. The numbers of extra rows are reported, not hidden:

* quantowl maps a label's end bar to the first *row* starting at or after it, so with sparse
  events (not one row per bar) it purges a row whose label ends between two event starts.
* RiskLabAI anchors the embargo at the first row starting at or after the label end and keeps
  that row in the embargo, so with sparse events it embargoes one row more.

With one row per bar the three agree exactly (quantowl also needs ``n % n_groups == 0``: it folds
the remainder into the last group, RiskLabAI and ALPHA spread it over the first groups).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from quantowl.cv import CombinatorialPurgedCV as QCPCV
from quantowl.cv import PurgedKFold as QPurgedKFold
from RiskLabAI.backtest.validation.combinatorial_purged import CombinatorialPurged

from alpha_afml_worker.contract import AgreementError, ContractError, require_int_at_least

Split = tuple[np.ndarray, np.ndarray]


def _check_spans(starts: np.ndarray, ends: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    raw_s, raw_e = np.asarray(starts), np.asarray(ends)
    if raw_s.dtype.kind not in "iu" or raw_e.dtype.kind not in "iu":
        # A float end of 1.9 cast to 1 would shorten the label and under-purge.
        raise ContractError("label starts and ends must be integer bar positions")
    s = raw_s.astype(np.int64)
    e = raw_e.astype(np.int64)
    if s.ndim != 1 or s.shape != e.shape or s.size < 2:
        raise ContractError("starts and ends must be equal-length 1-D arrays of at least 2 rows")
    if bool(np.any(np.diff(s) <= 0)):
        raise ContractError("label starts must be strictly increasing (one row per start bar)")
    if bool(np.any(e < s)):
        raise ContractError("a label ends before it starts")
    return s, e


def groups(n: int, n_groups: int) -> list[np.ndarray]:
    """Contiguous near-equal groups, remainder over the first (ALPHA cpcv.py, RiskLabAI)."""
    return [g.astype(np.int64) for g in np.array_split(np.arange(n), n_groups)]


def _blocks(test: np.ndarray) -> list[tuple[int, int]]:
    """Maximal runs of consecutive test rows, as inclusive (first, last) row pairs."""
    cuts = np.flatnonzero(np.diff(test) > 1)
    firsts = np.r_[test[0], test[cuts + 1]]
    lasts = np.r_[test[cuts], test[-1]]
    return [(int(a), int(b)) for a, b in zip(firsts, lasts, strict=True)]


def reference_train(
    starts: np.ndarray, ends: np.ndarray, test: np.ndarray, embargo: int
) -> np.ndarray:
    """ALPHA's brute-force rule: every row not in test, not overlapping, not embargoed."""
    n = starts.size
    keep = np.ones(n, dtype=bool)
    keep[test] = False
    for i in range(n):
        if keep[i] and bool(np.any((starts[i] <= ends[test]) & (ends[i] >= starts[test]))):
            keep[i] = False
    for first, last in _blocks(np.sort(test)):
        label_end = int(ends[first : last + 1].max())
        after = np.flatnonzero(starts > label_end)[:embargo]
        keep[after] = False
    return np.flatnonzero(keep)


def leaks(starts: np.ndarray, ends: np.ndarray, train: np.ndarray, test: np.ndarray,
          embargo: int) -> list[str]:  # fmt: skip
    """Brute-force leak checker: every train/test interval pair, and every embargo zone."""
    problems = []
    for i in train.tolist():
        hit = (starts[i] <= ends[test]) & (ends[i] >= starts[test])
        if bool(np.any(hit)):
            problems.append(f"train row {i} overlaps test row {int(test[np.argmax(hit)])}")
    for first, last in _blocks(np.sort(test)):
        label_end = int(ends[first : last + 1].max())
        zone = set(np.flatnonzero(starts > label_end)[:embargo].tolist())
        bad = zone.intersection(train.tolist())
        if bad:
            problems.append(f"train rows {sorted(bad)[:3]} sit in the embargo after row {last}")
    return problems


@dataclass(frozen=True)
class Splits:
    """RiskLabAI's splits, checked; how many rows each library dropped beyond the reference."""

    splits: list[Split]
    test_groups: list[tuple[int, ...]]
    extra_dropped_risklabai: int
    extra_dropped_quantowl: int | None  # None when quantowl's grouping differs (n % N != 0)
    n_paths: int
    path_folds: np.ndarray  # (n_groups, n_paths): simulation feeding each group on each path


def _embargo_fraction(n: int, embargo: int) -> float:
    """A fraction both libraries turn back into exactly ``embargo`` rows (else refuse)."""
    if embargo == 0:
        return 0.0
    for fraction in (embargo / n, (embargo + 1e-12) / n, (embargo + 1e-10) / n):
        if int(n * fraction) == embargo and math.ceil(round(fraction * n, 9)) == embargo:
            return fraction
    raise ContractError(f"no embargo fraction gives exactly {embargo} rows of {n}")


def _extra(train: np.ndarray, ref: np.ndarray) -> int:
    lib, want = set(train.tolist()), set(ref.tolist())
    if lib - want:
        raise AgreementError(f"a library kept {len(lib - want)} rows the reference drops")
    return len(want - lib)


def purged_splits(
    starts: np.ndarray,
    ends: np.ndarray,
    n_groups: int,
    n_test_groups: int = 1,
    embargo: int = 0,
) -> Splits:
    """Purged k-fold (``n_test_groups=1``) or combinatorial purged CV with backtest paths."""
    s, e = _check_spans(starts, ends)
    n = s.size
    require_int_at_least(n_groups, "n_groups", 2)
    require_int_at_least(embargo, "embargo", 0)
    if not 1 <= n_test_groups < n_groups or n < n_groups:
        raise ContractError("need 1 <= n_test_groups < n_groups <= rows")
    if embargo >= n:
        raise ContractError(f"embargo ({embargo} rows) must be shorter than the sample ({n} rows)")
    fraction = _embargo_fraction(n, embargo)
    data = pd.DataFrame(index=pd.Index(s))
    times = pd.Series(e, index=pd.Index(s))
    # RiskLabAI's PurgedKFold ends each test window at the LAST test label, not the latest one,
    # so labels of varying length under-purge; its combinatorial splitter with one test group
    # takes the latest end of each block and is used for k-fold too (review finding).
    r_iter = CombinatorialPurged(n_groups, n_test_groups, times, fraction).split(data)
    q_cv: QPurgedKFold | QCPCV
    if n_test_groups == 1:
        q_cv = QPurgedKFold(n_groups, embargo_pct=fraction)
    else:
        q_cv = QCPCV(n_groups, n_test_groups, embargo_pct=fraction, min_train_size=0)
    r_splits = [(np.sort(np.asarray(tr, dtype=np.int64)), np.asarray(te, dtype=np.int64))
                for tr, te in r_iter]  # fmt: skip
    combos = list(itertools.combinations(range(n_groups), n_test_groups))
    parts = groups(n, n_groups)
    extra_r = 0
    for (train, test), combo in zip(r_splits, combos, strict=True):
        if not np.array_equal(test, np.concatenate([parts[g] for g in combo])):
            raise AgreementError(f"RiskLabAI's test rows for groups {combo} are not the groups")
        if train.size == 0:
            raise ContractError(
                f"folds testing groups {combo} keep no training rows after purge and embargo; "
                "use fewer test groups, a shorter embargo or more labels"
            )
        found = leaks(s, e, train, test, embargo)
        if found:
            raise AgreementError("RiskLabAI split leaks: " + "; ".join(found[:3]))
        extra_r += _extra(train, reference_train(s, e, test, embargo))
    extra_q: int | None = None
    if n % n_groups == 0:
        # quantowl maps each end bar to the first row starting at or after it (its own lookup).
        x = pd.DataFrame(index=pd.Index(s))
        t1 = pd.Series(e, index=pd.Index(s))
        extra_q = 0
        for (_train, test), (q_train, q_test) in zip(r_splits, q_cv.split(x, t1=t1), strict=True):
            if not np.array_equal(test, np.asarray(q_test)):
                raise AgreementError("quantowl's test rows differ from RiskLabAI's")
            q_train = np.asarray(q_train, dtype=np.int64)
            if leaks(s, e, q_train, test, embargo):
                raise AgreementError("quantowl split leaks")
            extra_q += _extra(q_train, reference_train(s, e, test, embargo))
    path_folds, n_paths = _paths(n_groups, n_test_groups, combos)
    return Splits(r_splits, combos, extra_r, extra_q, n_paths, path_folds)


def _paths(n_groups: int, k: int, combos: list[tuple[int, ...]]) -> tuple[np.ndarray, int]:
    """quantowl's path map, checked against RiskLabAI's and the count C(N, k) k / N."""
    n_paths = math.comb(n_groups, k) * k // n_groups
    x = pd.DataFrame(index=pd.RangeIndex(n_groups * 2))
    if k == 1:
        return np.arange(n_groups).reshape(n_groups, 1), 1
    q = QCPCV(n_groups, k).build_paths(x)
    if q.n_paths != n_paths:
        raise AgreementError(f"quantowl counts {q.n_paths} paths, expected {n_paths}")
    locations = CombinatorialPurged._path_locations(n_groups, combos)
    r = np.full((n_groups, n_paths), -1, dtype=np.int64)
    for path_id, cells in locations.items():
        for group, sim in cells:
            r[group, path_id - 1] = sim
    if not np.array_equal(r, q.path_folds):
        raise AgreementError("RiskLabAI and quantowl stitch backtest paths differently")
    for p in range(n_paths):
        for g in range(n_groups):
            if g not in combos[int(r[g, p])]:
                raise AgreementError(f"path {p} takes group {g} from a fold that does not test it")
    return r, n_paths
