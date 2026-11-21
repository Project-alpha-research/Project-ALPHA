"""Eight descriptive series derived from stored CFTC and FINRA rows (recipe context-derived-v1).

Every function works on one native timeline (weekly COT reports or daily FINRA rows), sorted by
period, with trailing windows that include the current row. A derived row carries `known_eff`:
the running maximum of `known_from` over the stored rows up to and including it, so a value is
never known before its newest input. A COT `known_from` that comes from the release rule alone
(no system stamp) is first moved one day later (`RULE_MARGIN`). Nothing here joins to bars;
`attach.py` does that. Windows are fixed in the recipe; a change is a new recipe version.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Final

import polars as pl

from alpha_core import DataError
from alpha_data.context.events import TIME

RECIPE: Final = "context-derived-v1"
COT_SERIES: Final = (
    "cot_nc_net_oi",
    "cot_nc_net_pct_156w",
    "cot_comm_nc_gap_pct_156w",
    "cot_nc_net_chg_4w",
)
FINRA_SERIES: Final = ("sv_ratio", "sv_ratio_5d", "sv_ratio_z_60d", "sv_breadth_z1")
STALE_DAYS: Final = {"cot": 17, "finra": 5}
COT_PCT_WINDOW: Final = 156
COT_CHANGE_LAG: Final = 4
SV_MEAN_WINDOW: Final = 5
SV_Z_WINDOW: Final = 60
BREADTH_LEVEL: Final = 1.0
UNVERIFIED: Final = "cot-delayed-release-unverified"
# Report dates (inclusive) of US government shutdowns whose delayed COT releases the stored
# rule-only `known_from` cannot place. The exact catch-up dates were NOT verified, so these
# windows are deliberately wide. Only rows with known_basis "rule-only-era" are affected; later
# rows carry the system stamp. Closure days themselves are handled in cftc_cot.py.
SHUTDOWN_WINDOWS: Final = (
    (date(2018, 12, 18), date(2019, 3, 5)),
    (date(2013, 10, 1), date(2013, 10, 29)),
)
# A COT time from the release rule alone (known_basis "rule" or "rule-only-era") cannot see a late
# release. Stamped rows show them: in normal weeks of 2022-09 to 2026 some reports came out after
# the 16:00 US Eastern close (up to about two hours late). One day later is always safe.
RULE_MARGIN: Final = timedelta(days=1)
SCHEMA: Final[Mapping[str, pl.DataType | type[pl.DataType]]] = dict(
    period=pl.Date, known_eff=TIME, value=pl.Float64, reason=pl.String
)


def series_source(series: str) -> str:
    if series in COT_SERIES:
        return "cot"
    if series in FINRA_SERIES:
        return "finra"
    raise DataError(f"unknown context series {series!r}; known: {[*COT_SERIES, *FINRA_SERIES]}")


def breadth_label(count: int) -> str:
    return f"{count} stored names, not market-wide"


def in_shutdown_window(period: date) -> bool:
    return any(start <= period <= end for start, end in SHUTDOWN_WINDOWS)


def _running_max(stamps: Sequence[datetime]) -> list[datetime]:
    out: list[datetime] = []
    for stamp in stamps:
        out.append(stamp if not out or stamp > out[-1] else out[-1])
    return out


def _frame(
    periods: Sequence[date],
    known: Sequence[datetime],
    value: Sequence[float | None],
    reason: Sequence[str | None] | None = None,
) -> pl.DataFrame:
    return pl.DataFrame(
        dict(
            period=list(periods),
            known_eff=_running_max(known),
            value=list(value),
            reason=list(reason) if reason is not None else [None] * len(periods),
        ),
        schema=SCHEMA,
    )


def _ratio(numerator: float, denominator: float, field: str) -> float:
    if not (math.isfinite(numerator) and math.isfinite(denominator)) or denominator <= 0:
        raise DataError(f"{field} must be finite and positive to form a ratio")
    return numerator / denominator


def rolling_pct(values: Sequence[float | None], window: int) -> list[float | None]:
    """Fraction in [0, 1] of the newest value among the last `window` positions (average rank).

    Position counts include unknown (None) values, so warm-up is `window` reports; the rank is
    taken over the available values only. Fewer than two available values gives None.
    """
    out: list[float | None] = []
    for index, current in enumerate(values):
        if index + 1 < window or current is None:
            out.append(None)
            continue
        available = [v for v in values[index + 1 - window : index + 1] if v is not None]
        if len(available) < 2:
            out.append(None)
            continue
        less = sum(v < current for v in available)
        equal = sum(v == current for v in available)
        rank = less + (equal + 1) / 2
        out.append((rank - 1) / (len(available) - 1))
    return out


def _change(values: Sequence[float | None], lag: int) -> list[float | None]:
    out: list[float | None] = []
    for index, current in enumerate(values):
        earlier = values[index - lag] if index >= lag else None
        out.append(None if current is None or earlier is None else current - earlier)
    return out


def derive_cot(rows: pl.DataFrame, series: str) -> pl.DataFrame:
    """One COT series over one market's rows. Rows in a shutdown window are unknown (None)."""
    if series not in COT_SERIES:
        raise DataError(f"{series!r} is not a COT series")
    ordered = rows.sort("report_date")
    periods: list[date] = ordered["report_date"].to_list()
    unknown = [
        in_shutdown_window(p) and basis == "rule-only-era"
        for p, basis in zip(periods, ordered["known_basis"].to_list(), strict=True)
    ]
    oi = ordered["open_interest"].to_list()
    nc = [a - b for a, b in zip(ordered["noncomm_long"], ordered["noncomm_short"], strict=True)]
    comm = [a - b for a, b in zip(ordered["comm_long"], ordered["comm_short"], strict=True)]

    def scaled(net: Sequence[int]) -> list[float | None]:
        return [
            None if bad else _ratio(float(n), float(d), "open_interest")
            for n, d, bad in zip(net, oi, unknown, strict=True)
        ]

    nc_oi = scaled(nc)
    if series == "cot_nc_net_oi":
        value = nc_oi
    elif series == "cot_nc_net_pct_156w":
        value = rolling_pct(nc_oi, COT_PCT_WINDOW)
    elif series == "cot_comm_nc_gap_pct_156w":
        comm_oi = scaled(comm)
        gap = [
            None if a is None or b is None else a - b for a, b in zip(comm_oi, nc_oi, strict=True)
        ]
        value = rolling_pct(gap, COT_PCT_WINDOW)
    else:
        value = _change(nc_oi, COT_CHANGE_LAG)
    reason = [UNVERIFIED if bad else None for bad in unknown]
    known = [
        stamp if basis == "stamp" else stamp + RULE_MARGIN
        for stamp, basis in zip(ordered["known_from"], ordered["known_basis"], strict=True)
    ]
    return _frame(periods, known, value, reason)


def _finite(values: Sequence[float], field: str) -> None:
    if not all(math.isfinite(v) for v in values):
        raise DataError(f"{field} must be finite")


def _window_mean(values: Sequence[float], window: int) -> list[float | None]:
    return [
        sum(values[i + 1 - window : i + 1]) / window if i + 1 >= window else None
        for i in range(len(values))
    ]


def _window_z(values: Sequence[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    for index, current in enumerate(values):
        if index + 1 < window:
            out.append(None)
            continue
        span = values[index + 1 - window : index + 1]
        if max(span) == min(span):
            out.append(None)  # standard deviation 0: z is undefined, never filled with zero
            continue
        mean = sum(span) / window
        std = math.sqrt(sum((v - mean) ** 2 for v in span) / (window - 1))
        out.append((current - mean) / std)
    return out


def derive_sv(rows: pl.DataFrame, series: str) -> pl.DataFrame:
    """One per-symbol FINRA series (the breadth series is `derive_breadth`)."""
    if series not in ("sv_ratio", "sv_ratio_5d", "sv_ratio_z_60d"):
        raise DataError(f"{series!r} is not a per-symbol FINRA series")
    ordered = rows.sort("trade_date")
    short, total = ordered["short_volume"].to_list(), ordered["total_volume"].to_list()
    _finite(short, "short_volume")
    _finite(total, "total_volume")
    ratio = [_ratio(s, t, "total_volume") for s, t in zip(short, total, strict=True)]
    if series == "sv_ratio":
        value: list[float | None] = list(ratio)
    elif series == "sv_ratio_5d":
        value = _window_mean(ratio, SV_MEAN_WINDOW)
    else:
        value = _window_z(ratio, SV_Z_WINDOW)
    return _frame(ordered["trade_date"].to_list(), ordered["known_from"].to_list(), value)


def derive_breadth(z_by_symbol: Mapping[str, pl.DataFrame]) -> pl.DataFrame:
    """Share of names with z above 1 on each date, among names that have a z that day.

    `known_eff` is the newest `known_eff` of every name's row on that date, then a running maximum.
    """
    cells: dict[date, list[tuple[float | None, datetime]]] = {}
    for frame in z_by_symbol.values():
        for period, stamp, value in frame.select("period", "known_eff", "value").iter_rows():
            cells.setdefault(period, []).append((value, stamp))
    periods = sorted(cells)
    shares: list[float | None] = []
    for period in periods:
        usable = [v for v, _ in cells[period] if v is not None]
        shares.append(sum(v > BREADTH_LEVEL for v in usable) / len(usable) if usable else None)
    newest = [max(stamp for _, stamp in cells[p]) for p in periods]
    return _frame(periods, newest, shares)
