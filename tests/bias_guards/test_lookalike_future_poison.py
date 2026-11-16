"""Future-poison guards for the STUMPY adapter (`alpha_patterns.lookalike`).

Shape search is one of the easiest places to read the future by accident: a search over the
whole series finds "matches" after the query, a threshold taken from the whole distance profile
lets later bars decide which earlier stretches count, and a nearest-neighbour profile that looks
both ways scores today against tomorrow. The method here is the house one: replace every bar
after the as-of bar with violent garbage, or cut it off, and require the outputs at or before
the as-of bar to be identical. A deliberately leaky twin proves the guard is not vacuous.
"""

from __future__ import annotations

import numpy as np
import pytest

from alpha_core import DataError
from alpha_patterns.lookalike import find_lookalikes, novelty_score
from alpha_patterns.series import OHLCV

pytestmark = pytest.mark.bias_guard

DAY_MS = 86_400_000.0
WINDOW = 30
QUERY = 500


def _series(close: np.ndarray) -> OHLCV:
    return OHLCV(
        ts=np.arange(close.size, dtype=np.float64) * DAY_MS,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=np.ones(close.size),
    )


def _clean(seed: int = 11, n: int = 900) -> np.ndarray:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))
    motif = np.sin(np.linspace(0.0, 3.0 * np.pi, WINDOW)) * 0.08
    for start in (150, 300, QUERY, 650, 800):  # two copies sit after the query on purpose
        close[start : start + WINDOW] = close[start] * np.exp(motif)
    return np.asarray(close)


def _poison(close: np.ndarray, cut: int) -> np.ndarray:
    """Bars at or before ``cut`` are copied byte for byte; everything after is garbage."""
    rng = np.random.default_rng(999)
    out = close.copy()
    tail = close.size - cut - 1
    out[cut + 1 :] = close[cut] * 10.0 * np.exp(rng.normal(0.0, 0.2, tail))
    return out


def _lookalike_view(bars: OHLCV) -> tuple[object, ...]:
    result = find_lookalikes(
        bars,
        bars.ts[QUERY],
        WINDOW,
        top_k=20,
        exclusion=WINDOW,
        max_distance=4.0,
        horizons=(5, 20, 60),
    )
    return (
        result.matches,
        result.matches_within_threshold,
        result.candidates_searched,
        result.overlapping_outcomes,
    )


def _leaky_twin(bars: OHLCV) -> list[int]:
    """The classic mistake: search the whole series and only skip the query itself."""
    import stumpy

    query = bars.close[QUERY : QUERY + WINDOW]
    distances = np.asarray(stumpy.mass(query, bars.close), dtype=np.float64)
    distances[QUERY - WINDOW + 1 : QUERY + WINDOW] = np.inf
    chosen: list[int] = []
    for index in np.argsort(distances, kind="stable"):
        if distances[index] > 4.0:
            break
        if all(abs(int(index) - other) >= WINDOW for other in chosen):
            chosen.append(int(index))
    return sorted(chosen)


def test_lookalikes_ignore_every_bar_after_the_query_end() -> None:
    close = _clean()
    as_of = QUERY + WINDOW - 1
    baseline = _lookalike_view(_series(close))
    assert baseline[0], "the guard needs matches to compare"
    assert baseline == _lookalike_view(_series(_poison(close, as_of)))
    assert baseline == _lookalike_view(_series(close[: as_of + 1]))


def test_lookalikes_do_not_depend_on_bars_after_the_query_start_except_the_query() -> None:
    """With the query's own bars fixed, the bars after it cannot move a match or its distance."""
    close = _clean()
    poisoned = _poison(close, QUERY + WINDOW - 1)
    poisoned[QUERY : QUERY + WINDOW] = close[QUERY : QUERY + WINDOW]
    clean_bars, dirty_bars = _series(close), _series(poisoned)
    clean = find_lookalikes(
        clean_bars, clean_bars.ts[QUERY], WINDOW, top_k=20, exclusion=WINDOW, max_distance=4.0
    )
    dirty = find_lookalikes(
        dirty_bars, dirty_bars.ts[QUERY], WINDOW, top_k=20, exclusion=WINDOW, max_distance=4.0
    )
    assert [(m.start_index, m.distance) for m in clean.matches] == [
        (m.start_index, m.distance) for m in dirty.matches
    ]
    assert all(m.end_index < QUERY for m in clean.matches)


def test_the_guard_catches_a_leaky_whole_series_search() -> None:
    close = _clean()
    as_of = QUERY + WINDOW - 1
    leaky = _leaky_twin(_series(close))
    assert any(start > QUERY for start in leaky), "the leaky twin finds the planted future copies"
    assert leaky != _leaky_twin(_series(_poison(close, as_of)))


@pytest.mark.parametrize("as_of", [400, 620, 899])
def test_novelty_ignores_every_bar_after_as_of(as_of: int) -> None:
    close = _clean()
    clean = novelty_score(_series(close), WINDOW, as_of=_series(close).ts[as_of])
    for other in (_series(_poison(close, as_of)), _series(close[: as_of + 1])):
        dirty = novelty_score(other, WINDOW, as_of=other.ts[as_of])
        assert dirty.score == clean.score
        assert dirty.percentile == clean.percentile
        assert dirty.scores == clean.scores


def test_each_novelty_score_uses_only_bars_up_to_its_own_window_end() -> None:
    """Score j from a later run equals the score computed with as_of at j's own last bar."""
    close = _clean()
    bars = _series(close)
    full = novelty_score(bars, WINDOW, as_of=bars.ts[-1])
    for end in (300, 480, 529, 700):
        alone = novelty_score(bars, WINDOW, as_of=bars.ts[end])
        later = full.scores[end - WINDOW + 1]
        assert later is not None
        assert later == pytest.approx(alone.score, abs=1e-9)


def test_the_guard_catches_a_two_sided_profile() -> None:
    """The leaky novelty twin: nearest neighbour anywhere (STUMPY's P_), not only earlier."""
    import stumpy

    close = _clean()
    as_of = 620
    clean = stumpy.stump(close, WINDOW).P_[as_of - WINDOW + 1]
    dirty = stumpy.stump(_poison(close, as_of), WINDOW).P_[as_of - WINDOW + 1]
    honest = novelty_score(_series(close), WINDOW, as_of=_series(close).ts[as_of]).score
    assert clean != pytest.approx(dirty)
    assert (
        honest
        == novelty_score(
            _series(_poison(close, as_of)), WINDOW, as_of=_series(close).ts[as_of]
        ).score
    )


def test_the_poison_is_seen_after_the_cut() -> None:
    """Non-vacuous: the same poison changes a later query's matches and a later novelty score."""
    close = _clean()
    as_of = QUERY + WINDOW - 1
    clean, dirty = _series(close), _series(_poison(close, as_of))
    later = 800
    assert (
        find_lookalikes(
            clean, clean.ts[later], WINDOW, top_k=20, exclusion=WINDOW, max_distance=4.0
        ).matches
        != find_lookalikes(
            dirty, dirty.ts[later], WINDOW, top_k=20, exclusion=WINDOW, max_distance=4.0
        ).matches
    )
    assert (
        novelty_score(clean, WINDOW, as_of=clean.ts[-1]).score
        != novelty_score(dirty, WINDOW, as_of=dirty.ts[-1]).score
    )


def test_non_finite_poison_fails_loud() -> None:
    close = _clean()
    close[QUERY + WINDOW + 5] = np.nan
    with pytest.raises(DataError, match="non-finite"):
        _series(close)
