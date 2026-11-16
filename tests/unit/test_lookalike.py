"""Known-answer, validation and parity tests for the STUMPY adapter (`alpha_patterns.lookalike`)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from alpha_core import DataError
from alpha_patterns.lookalike import (
    MIN_MATCHES_FOR_SUMMARY,
    correlation_for_distance,
    describe_outcomes,
    distance_for_correlation,
    find_lookalikes,
    novelty_score,
)
from alpha_patterns.series import OHLCV

DAY_MS = 86_400_000.0
MOTIF = np.sin(np.linspace(0.0, 3.0 * np.pi, 30)) * 0.08
PLANTED = (100, 300, 500)
QUERY = 740


def _series(close: np.ndarray) -> OHLCV:
    return OHLCV(
        ts=np.arange(close.size, dtype=np.float64) * DAY_MS,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=np.ones(close.size),
    )


def _walk(n: int = 800, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.asarray(100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n))))


def _planted(n: int = 800) -> OHLCV:
    close = _walk(n)
    for start in (*PLANTED, QUERY):
        close[start : start + 30] = close[start] * np.exp(MOTIF)
    return _series(close)


def test_a_planted_repeated_motif_is_found() -> None:
    bars = _planted()
    result = find_lookalikes(
        bars, bars.ts[QUERY], 30, top_k=10, exclusion=30, max_distance=2.0, horizons=(5, 10)
    )
    assert sorted(match.start_index for match in result.matches) == sorted(PLANTED)
    assert all(match.correlation > 0.999 for match in result.matches)
    assert result.labels[0] == "N=3 matches"
    assert "descriptive, not a forecast" in result.labels
    assert result.max_distance == 2.0


@pytest.mark.parametrize("seed", range(6))
def test_nothing_at_or_after_the_query_start_is_ever_returned(seed: int) -> None:
    rng = np.random.default_rng(seed)
    bars = _series(_walk(600, seed))
    for start in rng.integers(100, 560, size=4):
        window = int(rng.integers(5, 40))
        if start + window > len(bars):
            continue
        result = find_lookalikes(
            bars, bars.ts[start], window, top_k=50, exclusion=window, max_distance=1e6
        )
        assert result.matches, "a huge threshold must return matches"
        assert all(match.end_index < start for match in result.matches)
        starts = sorted(match.start_index for match in result.matches)
        assert all(right - left >= window for left, right in zip(starts, starts[1:], strict=False))


def test_outcomes_stop_at_the_query_end_and_are_labelled() -> None:
    bars = _planted()
    result = find_lookalikes(
        bars, bars.ts[QUERY], 30, top_k=10, exclusion=30, max_distance=2.0, horizons=(5, 400)
    )
    match = next(m for m in result.matches if m.start_index == 500)
    near, far = match.what_happened_next
    assert near.value == pytest.approx(bars.close[match.end_index + 5] / bars.close[529] - 1)
    assert far.value is None and far.reason is not None and "not known yet" in far.reason
    # The path after the match ends at the query's last bar, never later.
    assert len(match.path_after) == QUERY + 29 - match.end_index + 1


def test_the_summary_is_withheld_below_the_minimum() -> None:
    bars = _planted()
    result = find_lookalikes(
        bars, bars.ts[QUERY], 30, top_k=10, exclusion=30, max_distance=2.0, horizons=(5,)
    )
    (summary,) = describe_outcomes(result)
    assert summary.count == 3 < MIN_MATCHES_FOR_SUMMARY
    assert summary.median is None and summary.mean is None and summary.share_up is None
    assert summary.reason is not None and "too few" in summary.reason
    wide = find_lookalikes(
        bars, bars.ts[QUERY], 30, top_k=20, exclusion=30, max_distance=1e6, horizons=(5,)
    )
    (shown,) = describe_outcomes(wide)
    assert shown.count >= MIN_MATCHES_FOR_SUMMARY and shown.median is not None


def test_top_k_caps_and_reports_the_full_count() -> None:
    bars = _series(_walk(600, 1))
    result = find_lookalikes(bars, bars.ts[500], 20, top_k=3, exclusion=20, max_distance=1e6)
    assert len(result.matches) == 3 < result.matches_within_threshold
    distances = [match.distance for match in result.matches]
    assert distances == sorted(distances)


def test_the_stumpy_default_threshold_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    import stumpy

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("stumpy.match derives its default threshold from the whole series")

    monkeypatch.setattr(stumpy, "match", forbidden)
    bars = _planted()
    find_lookalikes(bars, bars.ts[QUERY], 30, top_k=5, exclusion=30, max_distance=2.0)
    for bad in (None, 0.0, -1.0, math.inf, math.nan, True):
        with pytest.raises(DataError, match="max_distance"):
            find_lookalikes(bars, bars.ts[QUERY], 30, top_k=5, exclusion=30, max_distance=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"window": 4}, "window"),
        ({"top_k": 0}, "top_k"),
        ({"exclusion": 29}, "exclusion"),
        ({"horizons": (0,)}, "horizons"),
        ({"horizons": (5, 5)}, "distinct"),
        ({"start": 790}, "only 10 exist"),
        ({"start": 50}, "before the query"),
        ({"start_ts": 123.0}, "not a bar timestamp"),
    ],
)
def test_bad_lookalike_inputs_fail_loud(kwargs: dict[str, object], message: str) -> None:
    bars = _planted()
    start = int(kwargs.pop("start", QUERY))  # type: ignore[call-overload]
    args: dict[str, object] = {
        "top_k": 5,
        "exclusion": 30,
        "max_distance": 2.0,
        "horizons": (5,),
    }
    window = int(kwargs.pop("window", 30))  # type: ignore[call-overload]
    start_ts = float(kwargs.pop("start_ts", bars.ts[start]))  # type: ignore[arg-type]
    args.update(kwargs)
    with pytest.raises(DataError, match=message):
        find_lookalikes(bars, start_ts, window, **args)  # type: ignore[arg-type]


def test_a_constant_query_or_flat_candidates_are_handled_loudly() -> None:
    close = _walk()
    close[740:770] = 50.0
    bars = _series(close)
    with pytest.raises(DataError, match="constant"):
        find_lookalikes(bars, bars.ts[740], 30, top_k=5, exclusion=30, max_distance=2.0)
    close = _planted().close.copy()
    close[200:260] = 75.0
    flat = _series(close)
    result = find_lookalikes(flat, flat.ts[QUERY], 30, top_k=10, exclusion=30, max_distance=1e6)
    assert result.constant_candidates_skipped == 31
    assert all(not 200 <= m.start_index <= 230 for m in result.matches)


def test_disordered_or_missing_bars_fail_loud() -> None:
    close = _walk(100)
    with pytest.raises(DataError, match="strictly increasing"):
        OHLCV(
            ts=np.r_[np.arange(99.0), 50.0] * DAY_MS,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=np.ones(100),
        )
    holed = close.copy()
    holed[10] = np.nan
    with pytest.raises(DataError, match="non-finite"):
        _series(holed)


def test_distance_and_correlation_are_inverse() -> None:
    for corr in (-0.5, 0.0, 0.8, 0.95, 1.0):
        assert correlation_for_distance(distance_for_correlation(corr, 30), 30) == pytest.approx(
            corr
        )
    with pytest.raises(DataError):
        distance_for_correlation(1.5, 30)


def test_a_planted_novel_window_scores_as_unusual() -> None:
    close = _walk(900, 5)
    close[-30:] = close[-31] * np.exp(0.02 * (-1.0) ** np.arange(30))  # a perfect zigzag
    bars = _series(close)
    result = novelty_score(bars, 30, as_of=bars.ts[-1])
    assert result.percentile is not None and result.percentile > 95.0
    assert result.earlier_scores == len(bars) - 30 + 1 - result.warmup - 1
    assert result.scores[: result.warmup] == (None,) * result.warmup
    assert result.exclusion_zone == 8
    assert result.labels[0].startswith("N=")


def test_left_profile_matches_stumpys_incremental_api() -> None:
    """Parity: the batch left profile equals stumpy.stumpi's left_P_ (ADR-0051, rule 7)."""
    import stumpy

    close = _walk(500, 9)
    bars = _series(close)
    result = novelty_score(bars, 20, as_of=bars.ts[-1], warmup=20)
    stream = stumpy.stumpi(close[:120], 20, egress=False)
    for value in close[120:]:
        stream.update(value)
    ours = np.array([np.nan if v is None else v for v in result.scores])
    compared = np.isfinite(ours)
    assert compared.sum() > 400
    np.testing.assert_allclose(ours[compared], stream.left_P_[compared], atol=1e-5)


def test_bad_novelty_inputs_fail_loud() -> None:
    bars = _series(_walk(300))
    with pytest.raises(DataError, match="warmup"):
        novelty_score(bars, 30, as_of=bars.ts[-1], warmup=10)
    with pytest.raises(DataError, match="need at least"):
        novelty_score(bars, 30, as_of=bars.ts[100])
    with pytest.raises(DataError, match="not a bar timestamp"):
        novelty_score(bars, 30, as_of=1.5)
    close = _walk(300)
    close[-30:] = 80.0
    flat = _series(close)
    with pytest.raises(DataError, match="constant"):
        novelty_score(flat, 30, as_of=flat.ts[-1])
