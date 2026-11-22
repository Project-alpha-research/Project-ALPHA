"""The two figures of `alpha lookalike` and `alpha unusual`, in the house figure grammar.

Builders only arrange numbers already computed by `alpha_patterns.lookalike`; the renderer in
`alpha_research.figures` draws them. The count, the labels and the caveat are printed on the
figure itself, so a copied picture still carries them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from alpha_patterns.lookalike import LookalikeResult, NoveltyResult, OutcomeSummary
    from alpha_patterns.series import OHLCV
    from alpha_research.figures import FigureSpec, LineMark, Mark


def _pct(value: float) -> str:
    return f"{value * 100:+.1f}%"


def _day(epoch_ms: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(epoch_ms / 1000.0, tz=UTC).strftime("%Y-%m-%d")


def _stamp(epoch_ms: float, intraday: bool) -> str:
    from datetime import UTC, datetime

    moment = datetime.fromtimestamp(epoch_ms / 1000.0, tz=UTC)
    return moment.strftime("%Y-%m-%d %H:%M") if intraday else moment.strftime("%Y-%m-%d")


def _room(values: list[float], below: float, above: float) -> tuple[float, float]:
    """Axis limits with fixed headroom, so the legend and the note never sit on the data."""
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    return low - below * span, high + above * span


def _bars_word(timeframe: str) -> str:
    return "daily" if timeframe == "1D" else timeframe


def _shape_and_path_marks(
    bars: OHLCV, result: LookalikeResult, intraday: bool
) -> tuple[list[LineMark], list[LineMark]]:
    """The rescaled outline of every match plus the query, and each match's path afterwards."""
    from alpha_patterns.lookalike import znorm
    from alpha_research.figures import LineMark

    shape_x = tuple(float(step) for step in range(-(result.window - 1), 1))
    close = bars.close
    shapes = []
    paths = []
    for match in result.matches:
        values = znorm(close[match.start_index : match.end_index + 1])
        shapes.append(
            LineMark(x=shape_x, y=tuple(float(v) for v in values), role="substrate", alpha=0.55)
        )
        if len(match.path_after) > 1:
            paths.append(
                LineMark(
                    x=tuple(float(step) for step in range(len(match.path_after))),
                    y=tuple(value * 100.0 for value in match.path_after),
                    role="substrate",
                    alpha=0.6,
                )
            )
    query = znorm(close[result.query_start_index : result.query_end_index + 1])
    shapes.append(
        LineMark(
            x=shape_x,
            y=tuple(float(v) for v in query),
            role="subject",
            width=2.4,
            label=f"Now: {_stamp(result.query_start_ts, intraday)} to "
            f"{_stamp(result.query_end_ts, intraday)}",
        )
    )
    if shapes[:-1]:
        shapes[0] = LineMark(
            x=shapes[0].x,
            y=shapes[0].y,
            role="substrate",
            alpha=0.55,
            label=f"{len(result.matches)} past lookalikes",
        )
    return shapes, paths


def _lookalike_answer(result: LookalikeResult, summaries: tuple[OutcomeSummary, ...]) -> str:
    count = len(result.matches)
    shown = [summary for summary in summaries if summary.median is not None]
    if count == 0:
        return (
            f"No earlier {result.window}-bar stretch was within the declared threshold "
            f"(shape correlation {result.max_distance_correlation:.2f} or more)."
        )
    if not shown:
        return (
            f"{count} earlier stretch{'es' if count != 1 else ''} looked like this; "
            f"fewer than 5 with a known outcome, so no summary is given (too few to say anything)."
        )
    parts = "; ".join(
        f"after {s.horizon} bars median {_pct(s.median or 0.0)}, "
        f"{(s.share_up or 0.0) * 100:.0f}% rose (of {s.count})"
        for s in shown
    )
    return f"What followed the {count} past lookalikes: {parts}."


def _median_marks(result: LookalikeResult) -> list[Mark]:
    """The median path of the lookalikes, only while enough of them have a known outcome."""
    import numpy as np

    from alpha_patterns.lookalike import MIN_MATCHES_FOR_SUMMARY
    from alpha_research.figures import LineMark, ValueLabel

    median: list[Mark] = []
    if len(result.matches) >= MIN_MATCHES_FOR_SUMMARY:
        steps = []
        for step in range(max(result.horizons, default=0) + 1):
            known = [m.path_after[step] for m in result.matches if len(m.path_after) > step]
            if len(known) < MIN_MATCHES_FOR_SUMMARY:
                break
            steps.append(float(np.median(known)) * 100.0)
        if len(steps) > 1:
            median.append(
                LineMark(
                    x=tuple(float(step) for step in range(len(steps))),
                    y=tuple(steps),
                    role="neutral",
                    width=2.0,
                    label="Median of the lookalikes",
                    end_label=ValueLabel(text=f"{steps[-1]:+.1f}%"),
                )
            )
    return median


def lookalike_figure(
    bars: OHLCV,
    result: LookalikeResult,
    summaries: tuple[OutcomeSummary, ...],
    *,
    asset: str,
    timeframe: str,
    result_id: str,
    looks: int,
    boundary: str = "",
) -> FigureSpec:
    from alpha_research.figures import FigureSpec, Panel, RuleMark

    window = result.window
    shapes, paths = _shape_and_path_marks(bars, result, timeframe != "1D")
    count = len(result.matches)
    longest = max(result.horizons, default=0)
    answer = _lookalike_answer(result, summaries)
    rules: list[Mark] = [
        RuleMark(orientation="vertical", position=0.0, role="reference", dashed=True, width=0.8)
    ]
    median = _median_marks(result)
    shape_values = [value for mark in shapes for value in mark.y]
    path_values = [value for mark in paths for value in mark.y] + [0.0]
    next_marks: tuple[Mark, ...] = (
        *paths,
        *median,
        *rules,
        RuleMark(
            orientation="horizontal",
            position=0.0,
            role="reference",
            dashed=True,
            width=0.8,
        ),
    )
    panels = [
        Panel(
            panel_id="shape",
            y_label="Shape (rescaled)",
            y_unit="z_score",
            marks=(*shapes, *rules),
            height_ratio=1.4,
            y_limits=_room(shape_values, 0.35, 0.3),
            note="Each stretch is rescaled to mean 0 and spread 1, so a 2% dip and a 20% "
            "fall with the same outline look alike.",
        )
    ]
    if paths:
        panels.append(
            Panel(
                panel_id="next",
                y_label="Change after (%)",
                y_unit="percent",
                marks=next_marks,
                height_ratio=1.4,
                legend=bool(median),
                y_limits=_room(path_values, 0.3, 0.3),
                note="What happened next to each past lookalike. Descriptive, not a forecast: "
                "it does not say what happens now.",
            )
        )
    return FigureSpec(
        figure_id="lookalike",
        title=f"Has {asset} looked like this before?  N = {count} lookalike"
        f"{'s' if count != 1 else ''}",
        subtitle=(
            (f"{boundary} · " if boundary else "")
            + f"Last {window} {_bars_word(timeframe)} bars vs every earlier stretch · threshold "
            f"set first: shape correlation {result.max_distance_correlation:.2f}+ · descriptive, "
            f"not a forecast · look {looks} in the ledger (more looks, more chance finds)"
        ),
        x_label="Bars, counted from the last bar of each stretch (0 = the bar it was complete)",
        x_kind="numeric",
        x_limits=(float(-(window - 1)), float(max(longest, 1))),
        panels=tuple(panels),
        question="Has price action shaped like the latest window happened before, and what "
        "followed it?",
        plain_language_answer=answer,
        truncation_note=(
            f"the closest {count} of {result.matches_within_threshold} within the threshold"
            if result.matches_within_threshold > count
            else None
        ),
        uncertainty=f"N = {count}; summaries withheld below 5 matches.",
        caveat="Past lookalikes describe history; they do not predict the future.",
        caption=f"lookalike {result_id} · STUMPY matrix profile · price only, no costs · UTC",
        source_artifacts=("result.json",),
    )


def unusual_figure(
    bars: OHLCV, result: NoveltyResult, *, asset: str, timeframe: str, result_id: str
) -> FigureSpec:
    import numpy as np

    from alpha_research.figures import (
        FigureSpec,
        LineMark,
        Panel,
        RuleMark,
        ScatterMark,
        ValueLabel,
        ZoneMark,
    )

    end = result.as_of_index + 1
    times = tuple(float(value) / 1000.0 for value in bars.ts[:end])
    price = tuple(float(value) for value in bars.close[:end])
    pairs = [
        (ts / 1000.0, score)
        for ts, score in zip(result.window_end_ts, result.scores, strict=True)
        if score is not None
    ]
    earlier = [score for score in result.scores[:-1] if score is not None]
    rules: list[Mark] = [
        RuleMark(
            orientation="horizontal",
            position=result.score,
            role="reference",
            width=0.8,
            annotate=ValueLabel(text="now"),
        )
    ]
    if earlier:
        top = float(np.percentile(earlier, 95.0))
        rules.append(
            RuleMark(
                orientation="horizontal",
                position=top,
                role="reference",
                width=0.8,
                annotate=ValueLabel(text="top 5%"),
            )
        )
    scored = [pair[1] for pair in pairs]
    # Log only when price moved tenfold or more; otherwise the log ticks print as powers of
    # ten and say less than a plain price axis.
    log_price = max(price) >= 10.0 * min(price)
    zone_start = float(bars.ts[result.as_of_index - result.window + 1]) / 1000.0
    percentile = result.percentile
    rank = (
        f"higher than {percentile:.0f}% of the {result.earlier_scores} earlier windows"
        if percentile is not None
        else (result.percentile_reason or "no earlier windows to rank against")
    )
    answer = (
        f"The latest {result.window} bars score {result.score:.2f} "
        f"(closest earlier shape correlation {result.correlation:.2f}); {rank}."
    )
    return FigureSpec(
        figure_id="unusual",
        title=f"How unusual is {asset} right now?",
        subtitle=(
            f"Each point: how far that {result.window}-bar stretch is from its closest earlier "
            f"stretch · {_bars_word(timeframe)} bars · only earlier bars used · "
            f"N = {result.earlier_scores} earlier windows · descriptive, not a forecast"
        ),
        x_label="Date (UTC)",
        x_kind="time",
        panels=(
            Panel(
                panel_id="price",
                y_label="Price (log)" if log_price else "Price",
                y_unit="price",
                y_scale="log" if log_price else "linear",
                marks=(
                    LineMark(x=times, y=price, role="substrate", label="Close"),
                    ZoneMark(
                        x0=zone_start,
                        x1=times[-1],
                        role="feature",
                        alpha=0.25,
                        label=f"Latest {result.window} bars",
                    ),
                ),
                height_ratio=1.3,
            ),
            Panel(
                panel_id="novelty",
                y_label="Unusualness",
                y_unit="index",
                marks=(
                    LineMark(
                        x=tuple(pair[0] for pair in pairs),
                        y=tuple(pair[1] for pair in pairs),
                        role="subject",
                        width=1.0,
                        label="Distance to closest earlier stretch",
                    ),
                    ScatterMark(
                        x=(pairs[-1][0],),
                        y=(result.score,),
                        role="feature",
                        size=40.0,
                        label=f"Now: {result.score:.2f}",
                    ),
                    *rules,
                ),
                height_ratio=1.0,
                y_limits=_room(scored, 0.3, 0.3),
                note="Higher = less like anything before. It says unusual, not up or down. "
                f"The first {result.warmup} bars are a warm-up and are not scored.",
            ),
        ),
        question="How unlike every earlier stretch is the latest window?",
        plain_language_answer=answer,
        uncertainty=f"Ranked against {result.earlier_scores} earlier windows.",
        caveat="Unusual is not a signal; a very quiet stretch can score as high as a crash.",
        caption=f"unusual {result_id} · STUMPY left matrix profile · as of "
        f"{_day(result.as_of_ts)} · UTC",
        source_artifacts=("result.json",),
    )
