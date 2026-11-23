"""`alpha lookalike --today`: forward use. Compare the newest bars with history before the boundary.

Research lookalike stops at the held-back boundary. This look reads the newest bars on purpose,
as `follow` does, through `follow_source.forward_bars`. It searches only bars up to the boundary
(`reserve.CUTOFF`) and before the query. It writes no run, no result folder and no try.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpha_cli.follow_source import forward_bars
from alpha_cli.spine.reserve import CUTOFF, CUTOFF_DATE
from alpha_core import DataError

LABEL = "forward use: a look at today, not a test"
DEFAULT_MIN_CORRELATION = 0.80


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts / 1000.0, tz=UTC).date().isoformat()


def _followed(close: Any, end_index: int, horizon: int, last_history: int) -> float | None:
    """The close-to-close change after a match; None when it would reach past the history."""
    if end_index + horizon > last_history:
        return None
    return float(close[end_index + horizon] / close[end_index] - 1.0)


def look_today(
    home: Path,
    asset: str,
    *,
    last: int,
    top: int,
    horizons: tuple[int, ...],
    now: datetime | None = None,
) -> dict[str, Any]:
    """The look at today as a plain dict. Nothing is written."""
    from alpha_cli.chart_cmds import to_ohlcv
    from alpha_patterns.lookalike import distance_for_correlation, find_lookalikes

    known, _ = forward_bars(home, asset, now or datetime.now(UTC))
    if len(known) < last:
        raise DataError(f"{asset}: need at least {last} bars, got {len(known)}")
    query = known[-last:]
    history = [bar for bar in known[:-last] if bar.ts <= CUTOFF]
    if not history:
        raise DataError(f"{asset}: no stored bars before the held-back boundary to compare with")
    series = to_ohlcv([*history, *query])
    threshold = distance_for_correlation(DEFAULT_MIN_CORRELATION, last)
    result = find_lookalikes(
        series,
        float(series.ts[len(history)]),
        last,
        top_k=top,
        exclusion=last,
        max_distance=threshold,
    )
    last_history = len(history) - 1
    rows: list[dict[str, Any]] = [
        {
            "start": _day(match.start_ts),
            "end": _day(match.end_ts),
            "correlation": match.correlation,
            "followed": {
                str(h): _followed(series.close, match.end_index, h, last_history) for h in horizons
            },
        }
        for match in result.matches
    ]
    summary: dict[str, dict[str, Any]] = {}
    for h in horizons:
        values = [v for row in rows if (v := row["followed"][str(h)]) is not None]
        summary[str(h)] = {
            "count": len(values),
            "median": statistics.median(values) if values else None,
            "share_up": sum(v > 0 for v in values) / len(values) if values else None,
            "reason": None if values else "no match had this many bars after it in the history",
        }
    return {
        "label": LABEL,
        "asset": asset,
        "query": {"start": _day(result.query_start_ts), "end": _day(result.query_end_ts)},
        "compared_with": f"bars up to {CUTOFF_DATE} only, before the query",
        "history_bars": len(history),
        "min_correlation": DEFAULT_MIN_CORRELATION,
        "matches": rows,
        "what_followed": summary,
        "written": "nothing: no run, no result folder, no try",
    }


def look_text(out: dict[str, Any]) -> str:
    lines = [
        f"{out['label'].capitalize()}.",
        f"{out['asset']}: the last {out['query']['start']} to {out['query']['end']} compared "
        f"with {out['compared_with']} ({out['history_bars']} bars).",
        f"Matches: {len(out['matches'])} (shape correlation {out['min_correlation']:.2f} or more)",
        "START\tEND\tCORRELATION",
        *(f"{m['start']}\t{m['end']}\t{m['correlation']:.3f}" for m in out["matches"]),
        "What followed those matches (descriptive, not a forecast):",
        *(
            f"  {h} bars: median {s['median']:+.2%}, {s['share_up']:.0%} rose, of {s['count']}"
            if s["median"] is not None
            else f"  {h} bars: {s['reason']}"
            for h, s in out["what_followed"].items()
        ),
        f"Written: {out['written']}.",
    ]
    return "\n".join(lines)
