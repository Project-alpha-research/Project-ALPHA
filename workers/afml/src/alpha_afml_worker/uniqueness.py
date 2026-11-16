"""Wave 1 item 1: sample uniqueness, time-decay weights and the sequential bootstrap (AFML ch. 4).

RiskLabAI is the primary answer and quantowl the independent second opinion. Every number this
module returns has been computed by both and checked equal to ``TOLERANCE``; a disagreement
raises :class:`AgreementError` instead of picking one. Labels are given as finished spans of
bar positions, so the libraries work on a plain integer bar grid (no time zones involved).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import polars as pl
from quantowl import weights as qw
from RiskLabAI.data import weights as rw

from alpha_afml_worker.contract import (
    AgreementError,
    ContractError,
    require_int_at_least,
    validate_label_spans,
)

TOLERANCE = 1e-10


def _check_agree(name: str, primary: np.ndarray, second: np.ndarray) -> float:
    a = np.asarray(primary, dtype=np.float64)
    b = np.asarray(second, dtype=np.float64)
    if a.shape != b.shape or not bool(np.all(np.isfinite(a))) or not bool(np.all(np.isfinite(b))):
        raise AgreementError(f"{name}: RiskLabAI and quantowl returned different or bad shapes")
    gap = float(np.max(np.abs(a - b))) if a.size else 0.0
    if gap > TOLERANCE:
        raise AgreementError(f"{name}: RiskLabAI and quantowl differ by {gap:.3e} > {TOLERANCE}")
    return gap


def _spans_series(starts: np.ndarray, ends: np.ndarray) -> pd.Series:
    return pd.Series(ends, index=pd.Index(starts))


@dataclass(frozen=True)
class Uniqueness:
    """Per-label average uniqueness and per-bar concurrency, both libraries agreeing."""

    labels: pl.DataFrame  # start, end, bars, avg_uniqueness
    concurrency: pl.DataFrame  # ts, concurrency
    indicator: np.ndarray  # bars x labels, 0/1 (the book's 1_{t,i})
    max_gap: float


def indicator_matrix(n_bars: int, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """The bar-by-label 0/1 matrix, from quantowl (checked against a direct build)."""
    built = qw.indicator_matrix(pd.RangeIndex(n_bars), _spans_series(starts, ends))
    matrix = np.asarray(built.to_numpy(dtype=np.float64))
    direct = np.zeros((n_bars, starts.size))
    for j, (s, e) in enumerate(zip(starts.tolist(), ends.tolist(), strict=True)):
        direct[s : e + 1, j] = 1.0
    if not np.array_equal(matrix, direct):
        raise AgreementError("quantowl's indicator matrix differs from the span definition")
    return matrix


def average_uniqueness(bar_ts: pl.Series, spans: pl.DataFrame) -> Uniqueness:
    """Average uniqueness of each finished label (mean of 1/c_t over its own bars)."""
    starts, ends = validate_label_spans(spans, bar_ts)
    n_bars = bar_ts.len()
    matrix = indicator_matrix(n_bars, starts, ends)
    primary = rw.calculate_average_uniqueness(pd.DataFrame(matrix)).to_numpy(dtype=np.float64)
    grid = pd.RangeIndex(n_bars)
    t1 = _spans_series(starts, ends)
    co = qw.num_co_events(grid, t1)
    second = qw.average_uniqueness(grid, t1, co).to_numpy(dtype=np.float64)
    gap = _check_agree("average uniqueness", primary, second)
    concurrency = co.to_numpy(dtype=np.int64)
    if not np.array_equal(concurrency, matrix.sum(axis=1).astype(np.int64)):
        raise AgreementError("label concurrency differs between the two constructions")
    if bool(np.any(primary <= 0.0)) or bool(np.any(primary > 1.0 + TOLERANCE)):
        raise AgreementError("average uniqueness left (0, 1]")
    labels = spans.select("start", "end").with_columns(
        bars=pl.Series((ends - starts + 1).astype(np.int64)),
        avg_uniqueness=pl.Series(primary),
    )
    conc = pl.DataFrame({"ts": bar_ts, "concurrency": concurrency})
    return Uniqueness(labels=labels, concurrency=conc, indicator=matrix, max_gap=gap)


def time_decay(avg_uniqueness: np.ndarray, last_weight: float) -> np.ndarray:
    """Linear decay over cumulative uniqueness (Snippet 4.11); newest label gets 1.

    ``avg_uniqueness`` must already be in label-start order. Only ``last_weight`` in [0, 1] is
    offered: RiskLabAI refuses negative values, so a negative one would have no second opinion.
    Caveat (quantowl's own note): the total uses every label passed in, so build the weights on
    the training labels alone.
    """
    if not 0.0 <= float(last_weight) <= 1.0:
        raise ContractError(f"last_weight must be in [0, 1], got {last_weight!r}")
    values = np.asarray(avg_uniqueness, dtype=np.float64)
    if values.ndim != 1 or values.size == 0 or not bool(np.all(np.isfinite(values))):
        raise ContractError("time decay needs a non-empty finite 1-D weight vector")
    if bool(np.any(values < 0.0)) or not float(values.sum()) > 0.0:
        raise ContractError("time decay needs non-negative weights with a positive sum")
    order = pd.RangeIndex(values.size)
    primary = rw.calculate_time_decay(pd.Series(values, index=order), float(last_weight))
    second = np.asarray(qw.time_decay(pd.Series(values, index=order), float(last_weight)))
    _check_agree("time decay", primary.to_numpy(), second)
    return np.asarray(primary.to_numpy(dtype=np.float64))


@dataclass(frozen=True)
class Bootstrap:
    """Sequential-bootstrap draws (label positions) and the sample's average uniqueness."""

    draws: np.ndarray
    sample_avg_uniqueness: float
    standard_avg_uniqueness: float  # same seed, plain bootstrap with replacement, for contrast


def sequential_bootstrap(indicator: np.ndarray, n_draws: int, seed: int) -> Bootstrap:
    """Draw labels so overlapping ones are less likely to be drawn together (Snippet 4.5).

    Both libraries draw from numpy's ``default_rng(seed)`` one uniform per draw, so with the
    same seed they must return the very same draws; anything else raises.
    """
    require_int_at_least(n_draws, "n_draws", 1)
    require_int_at_least(seed, "seed", 0)
    primary = np.asarray(rw.sequential_bootstrap(indicator, n_draws, random_state=seed))
    second = np.asarray(qw.sequential_bootstrap(indicator, n_samples=n_draws, seed=seed))
    if not np.array_equal(primary.astype(np.int64), second.astype(np.int64)):
        raise AgreementError("sequential bootstrap draws differ between the libraries")
    plain = np.random.default_rng(seed).integers(0, indicator.shape[1], n_draws)
    return Bootstrap(
        draws=primary.astype(np.int64),
        sample_avg_uniqueness=float(qw.sample_average_uniqueness(indicator, primary)),
        standard_avg_uniqueness=float(qw.sample_average_uniqueness(indicator, plain)),
    )
