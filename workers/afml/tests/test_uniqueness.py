"""Parity for wave 1 item 1: uniqueness, time decay and the sequential bootstrap.

Hand values come from the book's chapter-4 worked example (six bars, three labels), worked out below
by hand; the libraries must reproduce them and agree with each other to 1e-10.
"""

from __future__ import annotations

from fractions import Fraction

import numpy as np
import polars as pl
import pytest
from quantowl import weights as qw
from RiskLabAI.data import weights as rw
from shared_fixtures import SEED, daily_ts

from alpha_afml_worker.contract import ContractError
from alpha_afml_worker.labels import LabelParams, label_events
from alpha_afml_worker.uniqueness import (
    TOLERANCE,
    average_uniqueness,
    indicator_matrix,
    sequential_bootstrap,
    time_decay,
)

# Labels [0,2], [2,3], [4,5] over bars 0..5. Bar 2 is shared by labels 0 and 1.
HAND_INDICATOR = np.array(
    [
        [1, 0, 0],
        [1, 0, 0],
        [1, 1, 0],
        [0, 1, 0],
        [0, 0, 1],
        [0, 0, 1],
    ],
    dtype=float,
)
HAND_CONCURRENCY = [1, 1, 2, 1, 1, 1]
# Label 0: (1 + 1 + 1/2) / 3; label 1: (1/2 + 1) / 2; label 2: (1 + 1) / 2.
HAND_UNIQUENESS = [Fraction(5, 6), Fraction(3, 4), Fraction(1)]


def hand_draw_probabilities(matrix: np.ndarray, drawn: list[int]) -> list[Fraction]:
    """The book's delta_j: mean of 1/(1 + c_t) over label j's bars, c_t counting earlier draws."""
    counts = [sum(int(matrix[t, d]) for d in drawn) for t in range(matrix.shape[0])]
    scores = []
    for j in range(matrix.shape[1]):
        bars = [t for t in range(matrix.shape[0]) if matrix[t, j]]
        scores.append(sum(Fraction(1, 1 + counts[t]) for t in bars) / len(bars))
    total = sum(scores)
    return [s / total for s in scores]


def reference_draws(matrix: np.ndarray, n_draws: int, seed: int) -> list[int]:
    """Inverse-CDF draws from the hand probabilities, one numpy uniform per draw."""
    uniforms = np.random.default_rng(seed).random(n_draws)
    drawn: list[int] = []
    for u in uniforms.tolist():
        cdf = np.cumsum([float(p) for p in hand_draw_probabilities(matrix, drawn)])
        drawn.append(int(np.searchsorted(cdf / cdf[-1], u, side="right")))
    return drawn


def test_chapter4_indicator_concurrency_and_uniqueness(
    chapter4: tuple[pl.Series, pl.DataFrame],
) -> None:
    ts, spans = chapter4
    result = average_uniqueness(ts, spans)
    assert np.array_equal(result.indicator, HAND_INDICATOR)
    assert result.concurrency["concurrency"].to_list() == HAND_CONCURRENCY
    got = result.labels["avg_uniqueness"].to_list()
    assert got == pytest.approx([float(f) for f in HAND_UNIQUENESS], abs=1e-15)
    assert result.max_gap <= TOLERANCE


def test_chapter4_draw_probabilities_by_hand() -> None:
    # First draw uniform. Worked by hand for both orders of the next two draws (0-based labels):
    # label 1 then label 2 (reviewer's reading of the book's order, not re-checked against the
    # text) and label 2 then label 1. Either way the third state is 5/11, 3/11, 3/11.
    assert hand_draw_probabilities(HAND_INDICATOR, []) == [Fraction(1, 3)] * 3
    assert hand_draw_probabilities(HAND_INDICATOR, [1]) == [
        Fraction(5, 14),
        Fraction(3, 14),
        Fraction(3, 7),
    ]
    assert hand_draw_probabilities(HAND_INDICATOR, [1, 2]) == [
        Fraction(5, 11),
        Fraction(3, 11),
        Fraction(3, 11),
    ]
    assert hand_draw_probabilities(HAND_INDICATOR, [2]) == [
        Fraction(2, 5),
        Fraction(2, 5),
        Fraction(1, 5),
    ]
    assert hand_draw_probabilities(HAND_INDICATOR, [2, 1]) == [
        Fraction(5, 11),
        Fraction(3, 11),
        Fraction(3, 11),
    ]


@pytest.mark.parametrize("seed", range(0, 400, 7))
def test_both_libraries_draw_the_hand_sequence(seed: int) -> None:
    expected = reference_draws(HAND_INDICATOR, 6, seed)
    assert rw.sequential_bootstrap(HAND_INDICATOR, 6, random_state=seed).tolist() == expected
    assert qw.sequential_bootstrap(HAND_INDICATOR, n_samples=6, seed=seed).tolist() == expected
    assert sequential_bootstrap(HAND_INDICATOR, 6, seed).draws.tolist() == expected


def test_no_overlap_means_uniqueness_one() -> None:
    ts = daily_ts(10)
    spans = pl.DataFrame({"start": ts.gather([0, 3, 6]), "end": ts.gather([2, 5, 9])})
    assert average_uniqueness(ts, spans).labels["avg_uniqueness"].to_list() == [1.0, 1.0, 1.0]


def test_random_overlaps_stay_in_unit_interval_and_libraries_agree() -> None:
    rng = np.random.default_rng(SEED)
    n = 400
    starts = np.sort(rng.choice(n - 30, 80, replace=False))
    ends = starts + rng.integers(0, 25, starts.size)
    ts = daily_ts(n)
    spans = pl.DataFrame({"start": ts.gather(starts), "end": ts.gather(ends)})
    result = average_uniqueness(ts, spans)
    values = result.labels["avg_uniqueness"].to_numpy()
    assert bool(np.all(values > 0.0)) and bool(np.all(values <= 1.0))
    assert result.max_gap <= TOLERANCE


def test_daily_labels_libraries_agree_to_1e10(daily_bars: pl.DataFrame) -> None:
    events = label_events(daily_bars, LabelParams())
    finished = events.filter(pl.col("end").is_not_null()).select(start="ts", end="end")
    result = average_uniqueness(daily_bars["ts"], finished)
    assert finished.height > 50
    assert result.max_gap <= TOLERANCE
    boot = sequential_bootstrap(result.indicator, finished.height, SEED)
    assert boot.draws.size == finished.height


def test_time_decay_hand_values() -> None:
    # Cumulative weights 1,2,3,4 of total 4; c = 0.5: slope 0.5/4, constant 1 - 0.5 = 0.5.
    assert time_decay(np.ones(4), 0.5).tolist() == pytest.approx([0.625, 0.75, 0.875, 1.0])
    assert time_decay(np.ones(4), 1.0).tolist() == [1.0] * 4
    assert time_decay(np.array([5 / 6, 3 / 4, 1.0]), 0.0).tolist() == pytest.approx(
        [(5 / 6) / (31 / 12), (5 / 6 + 3 / 4) / (31 / 12), 1.0]
    )


@pytest.mark.parametrize("bad", [-0.5, 1.5, float("nan")])
def test_time_decay_refuses_weights_without_a_second_opinion(bad: float) -> None:
    with pytest.raises(ContractError):
        time_decay(np.ones(3), bad)


def test_unfinished_label_is_refused(chapter4: tuple[pl.Series, pl.DataFrame]) -> None:
    ts, spans = chapter4
    open_label = spans.with_columns(
        pl.when(pl.int_range(3) == 2).then(None).otherwise(pl.col("end")).alias("end")
    )
    with pytest.raises(ContractError):
        average_uniqueness(ts, open_label)


def test_indicator_matrix_matches_hand() -> None:
    matrix = indicator_matrix(6, np.array([0, 2, 4]), np.array([2, 3, 5]))
    assert np.array_equal(matrix, HAND_INDICATOR)


def _book_random_t1(rng: np.random.Generator, n_obs: int, n_bars: int, max_h: int) -> np.ndarray:
    """Snippet 4.7 (getRndT1): ``n_obs`` labels at random starts, 1 to max_h - 1 bars long."""
    spans: dict[int, int] = {}
    for _ in range(n_obs):
        start = int(rng.integers(0, n_bars))
        spans[start] = start + int(rng.integers(1, max_h))
    ordered = sorted(spans.items())
    n = max(end for _, end in ordered) + 1
    return indicator_matrix(n, np.array([s for s, _ in ordered]), np.array([e for _, e in ordered]))


def test_book_monte_carlo_medians_to_one_decimal() -> None:
    """Study item 1(d): the book's medians, standard about 0.6 against sequential about 0.7.

    Snippets 4.7 to 4.9 with the book's sizes (10 labels, 100 bars, horizon below 5), 400
    iterations instead of the book's one million, so only one decimal is claimed.
    """
    rng = np.random.default_rng(SEED)
    standard, sequential = [], []
    for it in range(400):
        matrix = _book_random_t1(rng, 10, 100, 5)
        plain = rng.choice(matrix.shape[1], size=matrix.shape[1])
        standard.append(qw.sample_average_uniqueness(matrix, plain))
        draws = rw.sequential_bootstrap(matrix, random_state=SEED + it)
        sequential.append(qw.sample_average_uniqueness(matrix, draws))
    assert round(float(np.median(standard)), 1) == 0.6
    assert round(float(np.median(sequential)), 1) == 0.7
