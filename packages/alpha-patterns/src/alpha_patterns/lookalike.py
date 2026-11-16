"""Shape lookalikes and novelty over closing prices, through STUMPY's matrix profile.

This is the one ALPHA module that imports STUMPY (ADR-0051, rule 6). It answers two questions:

* :func:`find_lookalikes` -- "has price action like this happened before?" It searches for
  stretches of closing prices whose *shape* (each stretch rescaled to mean 0 and spread 1) is
  close to a query window, and only in the bars **strictly before** the query starts.
* :func:`novelty_score` -- "what is unusual right now?" It scores how far the latest window is
  from its closest **earlier** window (STUMPY's left matrix profile), and ranks that score
  against the scores of all earlier windows.

Causality is structural, not hoped for. Both functions cut the series at their as-of bar
before anything else, so a bar after it never reaches STUMPY. The search set for lookalikes
ends one bar before the query starts, so a match can overlap neither the query nor anything
after it. "What happened next" for a match uses only bars up to the query's last bar.

The match threshold is always the caller's fixed, declared ``max_distance``. STUMPY's own
default for :func:`stumpy.match` is worked out from the whole distance profile, which lets
later bars change which earlier stretches count as matches; this module never calls
``stumpy.match`` and never derives a threshold from the data.

Nothing here judges whether a match predicts anything. The outcome summary is descriptive
and is withheld below :data:`MIN_MATCHES_FOR_SUMMARY` matches.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from alpha_core import DataError
from alpha_patterns.series import OHLCV

FloatArray = npt.NDArray[np.float64]

#: The smallest window STUMPY accepts is 3; shapes shorter than 5 bars carry almost no shape.
MIN_WINDOW = 5
#: Below this many matches the outcome summary is withheld, with a reason.
MIN_MATCHES_FOR_SUMMARY = 5

LABELS = (
    "descriptive, not a forecast",
    "multiple looks: every search is one more look at the same history",
)


def distance_for_correlation(correlation: float, window: int) -> float:
    """The z-normalised distance equivalent to a Pearson correlation for this window length.

    For z-normalised windows of length ``m``, ``distance**2 == 2 * m * (1 - correlation)``.
    Used to declare a threshold in words ("correlation 0.80 or more") without looking at data.
    """
    if not -1.0 <= correlation <= 1.0:
        raise DataError(f"correlation must lie in [-1, 1], got {correlation}")
    _check_window(window)
    return math.sqrt(2.0 * window * (1.0 - correlation))


def correlation_for_distance(distance: float, window: int) -> float:
    """The Pearson correlation equivalent to a z-normalised distance (inverse of the above)."""
    return 1.0 - distance * distance / (2.0 * window)


@dataclass(frozen=True, slots=True)
class Outcome:
    """The close-to-close price change ``horizon`` bars after a match's last bar."""

    horizon: int
    value: float | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class Match:
    """One past stretch whose shape resembles the query.

    ``start_index``/``end_index`` index the input series; ``end_index`` is the bar on which the
    match is complete. ``what_happened_next`` is computed separately from the search and only
    from bars at or before the query's last bar.
    """

    start_index: int
    end_index: int
    start_ts: float
    end_ts: float
    distance: float
    correlation: float
    what_happened_next: tuple[Outcome, ...]
    path_after: tuple[float, ...]  # price change from the match's last close, bar by bar


@dataclass(frozen=True, slots=True)
class LookalikeResult:
    query_start_index: int
    query_end_index: int
    query_start_ts: float
    query_end_ts: float
    window: int
    max_distance: float
    max_distance_correlation: float
    exclusion: int
    top_k: int
    horizons: tuple[int, ...]
    candidates_searched: int
    constant_candidates_skipped: int
    matches_within_threshold: int
    matches: tuple[Match, ...]
    overlapping_outcomes: int  # pairs of matches whose longest outcome windows share bars
    labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OutcomeSummary:
    horizon: int
    count: int
    median: float | None
    mean: float | None
    share_up: float | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class NoveltyResult:
    as_of_index: int
    as_of_ts: float
    window: int
    warmup: int
    exclusion_zone: int
    score: float
    correlation: float
    percentile: float | None
    earlier_scores: int
    percentile_reason: str | None
    window_end_ts: tuple[float, ...]
    scores: tuple[float | None, ...]  # one per window, None in warm-up or for a constant window
    constant_windows: int
    labels: tuple[str, ...]


def _check_window(window: int) -> None:
    if not isinstance(window, int) or isinstance(window, bool) or window < MIN_WINDOW:
        raise DataError(f"window must be an integer >= {MIN_WINDOW} bars, got {window!r}")


def _index_of(series: OHLCV, ts: float, name: str) -> int:
    index = int(np.searchsorted(series.ts, ts))
    if index >= len(series) or series.ts[index] != ts:
        raise DataError(f"{name} {ts!r} is not a bar timestamp in the series")
    return index


def _constant(values: FloatArray, window: int) -> npt.NDArray[np.bool_]:
    """STUMPY's definition: a window whose highest and lowest value are equal."""
    view = np.lib.stride_tricks.sliding_window_view(values, window)
    return np.asarray(np.ptp(view, axis=1) == 0.0)


def _znorm_rows(values: FloatArray, window: int) -> FloatArray:
    """Each window rescaled to mean 0 and population spread 1; a constant window becomes zeros."""
    view = np.lib.stride_tricks.sliding_window_view(values, window)
    mean = view.mean(axis=1, keepdims=True)
    std = view.std(axis=1, keepdims=True)
    safe = np.where(std == 0.0, 1.0, std)
    return np.asarray(np.where(std == 0.0, 0.0, (view - mean) / safe), dtype=np.float64)


def znorm(values: Sequence[float] | FloatArray) -> FloatArray:
    """One window rescaled to mean 0 and spread 1, as the search compares it (for drawing)."""
    array = np.asarray(values, dtype=np.float64)
    std = float(array.std())
    if std == 0.0:
        raise DataError("cannot rescale a constant window")
    return np.asarray((array - array.mean()) / std, dtype=np.float64)


def find_lookalikes(
    history: OHLCV,
    query_start_ts: float,
    window: int,
    *,
    top_k: int,
    exclusion: int,
    max_distance: float,
    horizons: Sequence[int] = (),
) -> LookalikeResult:
    """Past stretches shaped like the ``window`` bars starting at ``query_start_ts``.

    The search set is ``history.close[:query_start]``: every candidate ends before the query
    starts. ``max_distance`` is the fixed, declared z-normalised distance a match may not exceed.
    ``exclusion`` is the minimum number of bars between two match starts and must be at least
    ``window``, so no two matches share a bar. ``top_k`` caps how many of the closest matches are
    returned. ``horizons`` are the bar counts after each match's last bar at which the price
    change is reported, only where that bar is at or before the query's last bar.
    """
    import stumpy

    _check_window(window)
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        raise DataError(f"top_k must be a positive integer, got {top_k!r}")
    if not isinstance(exclusion, int) or isinstance(exclusion, bool) or exclusion < window:
        raise DataError(
            f"exclusion must be an integer >= window ({window}) so matches never overlap, "
            f"got {exclusion!r}"
        )
    if not isinstance(max_distance, int | float) or isinstance(max_distance, bool):
        raise DataError("max_distance must be a declared number")
    if not math.isfinite(max_distance) or max_distance <= 0.0:
        raise DataError(f"max_distance must be a positive finite number, got {max_distance!r}")
    steps = tuple(horizons)
    if any(not isinstance(h, int) or isinstance(h, bool) or h < 1 for h in steps):
        raise DataError(f"horizons must be positive integers, got {steps!r}")
    if len(set(steps)) != len(steps):
        raise DataError(f"horizons must be distinct, got {steps!r}")
    start = _index_of(history, query_start_ts, "query start")
    end = start + window - 1
    if end >= len(history):
        raise DataError(
            f"the query needs {window} bars from its start; only {len(history) - start} exist"
        )
    # Cut at the as-of bar first: nothing after the query's last bar is ever read below.
    close = np.asarray(history.close[: end + 1], dtype=np.float64)
    query = close[start : end + 1]
    if float(np.ptp(query)) == 0.0:
        raise DataError("the query window is constant; a flat stretch has no shape to match")
    searched = close[:start]
    if searched.size < 2 * window:
        raise DataError(
            f"need at least {2 * window} bars before the query to search, got {searched.size}"
        )
    distances = np.asarray(stumpy.mass(query, searched), dtype=np.float64)
    constant = _constant(searched, window)
    distances[constant] = np.inf
    chosen: list[int] = []
    for index in np.argsort(distances, kind="stable"):
        candidate = int(index)
        if not distances[candidate] <= max_distance:
            break
        if all(abs(candidate - other) >= exclusion for other in chosen):
            chosen.append(candidate)
    longest = max(steps, default=0)
    matches = tuple(_match(history, close, i, window, distances[i], steps, longest) for i in chosen)
    kept = matches[:top_k]
    overlapping = sum(
        1
        for left in range(len(kept))
        for right in range(left + 1, len(kept))
        if abs(kept[left].end_index - kept[right].end_index) < longest
    )
    return LookalikeResult(
        query_start_index=start,
        query_end_index=end,
        query_start_ts=float(history.ts[start]),
        query_end_ts=float(history.ts[end]),
        window=window,
        max_distance=float(max_distance),
        max_distance_correlation=correlation_for_distance(float(max_distance), window),
        exclusion=exclusion,
        top_k=top_k,
        horizons=steps,
        candidates_searched=int(distances.size),
        constant_candidates_skipped=int(constant.sum()),
        matches_within_threshold=len(matches),
        matches=kept,
        overlapping_outcomes=overlapping,
        labels=(f"N={len(kept)} matches", *LABELS),
    )


def _match(
    history: OHLCV,
    close: FloatArray,
    start: int,
    window: int,
    distance: float,
    horizons: tuple[int, ...],
    longest: int,
) -> Match:
    """Describe one match; ``close`` already ends at the query's last bar."""
    end = start + window - 1
    base = float(close[end])
    outcomes = tuple(
        Outcome(h, float(close[end + h] / base - 1.0), None)
        if end + h < close.size
        else Outcome(h, None, "that bar comes after the query's last bar, so it is not known yet")
        for h in horizons
    )
    stop = min(close.size, end + longest + 1)
    path = tuple(float(value / base - 1.0) for value in close[end:stop])
    return Match(
        start_index=start,
        end_index=end,
        start_ts=float(history.ts[start]),
        end_ts=float(history.ts[end]),
        distance=float(distance),
        correlation=correlation_for_distance(float(distance), window),
        what_happened_next=outcomes,
        path_after=path,
    )


def describe_outcomes(result: LookalikeResult) -> tuple[OutcomeSummary, ...]:
    """Count, median, mean and share positive per horizon; withheld below the minimum count.

    Descriptive only: these are what followed past lookalikes, not an expectation for the query.
    """
    summaries = []
    for position, horizon in enumerate(result.horizons):
        values = [
            outcome.value
            for match in result.matches
            if (outcome := match.what_happened_next[position]).value is not None
        ]
        if len(values) < MIN_MATCHES_FOR_SUMMARY:
            summaries.append(
                OutcomeSummary(
                    horizon,
                    len(values),
                    None,
                    None,
                    None,
                    f"withheld: {len(values)} matches with a known outcome, fewer than "
                    f"{MIN_MATCHES_FOR_SUMMARY}; too few to say anything",
                )
            )
            continue
        array = np.asarray(values, dtype=np.float64)
        summaries.append(
            OutcomeSummary(
                horizon,
                len(values),
                float(np.median(array)),
                float(array.mean()),
                float((array > 0.0).mean()),
                None,
            )
        )
    return tuple(summaries)


def novelty_score(
    series: OHLCV,
    window: int,
    *,
    as_of: float,
    warmup: int | None = None,
) -> NoveltyResult:
    """How unlike every earlier window the window ending at ``as_of`` is.

    The score of a window is its z-normalised distance to the closest window that started
    earlier (STUMPY's left matrix profile, with STUMPY's exclusion zone of ``ceil(window/4)``
    bars). The series is cut at ``as_of`` before STUMPY sees it, and a left neighbour lies
    before its window by construction, so each score uses only bars up to its own last bar.
    ``percentile`` is the share of earlier scored windows (those starting at or after
    ``warmup`` bars, default ``5 * window``) whose score is below the latest one.
    """
    import stumpy

    _check_window(window)
    burn = 5 * window if warmup is None else warmup
    if not isinstance(burn, int) or isinstance(burn, bool) or burn < window:
        raise DataError(f"warmup must be an integer >= window ({window}), got {warmup!r}")
    end = _index_of(series, as_of, "as_of")
    close = np.asarray(series.close[: end + 1], dtype=np.float64)
    count = close.size - window + 1
    if count < burn + 2:
        raise DataError(
            f"need at least {burn + window + 1} bars up to as_of for a {window}-bar window "
            f"after a {burn}-bar warm-up, got {close.size}"
        )
    constant = _constant(close, window)
    if bool(constant[-1]):
        raise DataError("the latest window is constant; a flat stretch has no shape to score")
    profile = stumpy.stump(close, window)
    left = np.asarray(profile.left_I_, dtype=np.int64)
    rows = _znorm_rows(close, window)
    scores = np.full(count, np.nan)
    known = (left >= 0) & ~constant
    scores[known] = np.linalg.norm(rows[known] - rows[left[known]], axis=1)
    scores[:burn] = np.nan
    score = float(scores[-1])
    if not math.isfinite(score):
        raise DataError("the latest window has no earlier neighbour to compare with")
    earlier = scores[burn:-1]
    earlier = earlier[np.isfinite(earlier)]
    percentile: float | None = None
    reason: str | None = None
    if earlier.size == 0:
        reason = "no earlier scored windows after the warm-up"
    else:
        percentile = float((earlier < score).mean() * 100.0)
    return NoveltyResult(
        as_of_index=end,
        as_of_ts=float(series.ts[end]),
        window=window,
        warmup=burn,
        exclusion_zone=math.ceil(window / stumpy.config.STUMPY_EXCL_ZONE_DENOM),
        score=score,
        correlation=correlation_for_distance(score, window),
        percentile=percentile,
        earlier_scores=int(earlier.size),
        percentile_reason=reason,
        window_end_ts=tuple(float(value) for value in series.ts[window - 1 : end + 1]),
        scores=tuple(float(value) if math.isfinite(value) else None for value in scores),
        constant_windows=int(constant.sum()),
        labels=(f"N={int(earlier.size)} earlier windows", *LABELS),
    )
