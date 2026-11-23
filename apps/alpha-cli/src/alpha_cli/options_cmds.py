"""`alpha options derived`: daily series computed from stored option chains, as plain readings.

Reads only through the capped research read of the options store (rows on or after the reserved
day are never used). Realized volatility: close-to-close log returns of the stored daily bars over
RV_WINDOW sessions, annualised by `alpha_validation.metrics.annualized_volatility` (ddof=1, 252).
No network, no writes.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated

import polars as pl
import typer

from alpha_cli._cli_json import emit
from alpha_cli.spine.reserve import CUTOFF
from alpha_core import DataError
from alpha_core.config import AlphaSettings
from alpha_data.options.derived import DerivedPoint, RealizedPoint, derive
from alpha_data.options.derived_params import (
    REASON_WORDS,
    RV_WINDOW,
    SERIES,
    SurfaceConfig,
)
from alpha_data.options.store import OptionsStore
from alpha_data.pit import PointInTimeReader
from alpha_data.store import ParquetStore
from alpha_data.timeframe import DAILY, store_dir
from alpha_validation.metrics import annualized_volatility

options_app = typer.Typer(help="Stored option chains: derived volatility series (readings only).")
HINTS = {
    "iv30": "iv30: at-the-money implied volatility for a constant 30 days ahead (a yearly rate).",
    "iv_rank_252": "iv_rank_252: where iv30 sits between its 252-session low (0) and high (1).",
    "iv_percentile_252": "iv_percentile_252: share of the last 252 sessions with iv30 below today.",
    "skew_25d": "skew_25d: 25-delta put volatility minus 25-delta call volatility at 30 days.",
    "term_slope": "term_slope: volatility at about 90 days minus iv30; above 0 is an upward term.",
    "iv_minus_rv": "iv_minus_rv: iv30 minus 21-session realized volatility (both yearly rates).",
}
READING = "Readings of stored data, not verdicts or advice; a null is a gap, never zero."


def _provider(root: Path, underlying: str, wanted: str | None) -> str:
    found = sorted(p.parent.name for p in (root / "options").glob(f"*/{underlying}") if p.is_dir())
    if wanted is not None:
        return wanted
    if len(found) == 1:
        return found[0]
    if found:
        raise DataError(f"several providers: {found}")
    if not any((root / "options").glob("*/*")):
        raise DataError(
            "No options data is stored yet, for any name. This feature needs a stored "
            "option-chain history from a data provider; ALPHA has none until one is imported."
        )
    raise DataError(f"no stored options for {underlying!r}")


def _realized(underlying: str, data_dir: Path) -> dict[date, RealizedPoint]:
    """Realized vol on each stored bar day from the last RV_WINDOW log returns; empty if no bars."""
    store = ParquetStore(store_dir(data_dir, DAILY))
    try:
        reader = PointInTimeReader(store, {underlying: store.read_actions(underlying)})
        bars = reader.as_of(underlying, CUTOFF)
    except DataError:
        return {}
    ts: list[datetime] = bars["ts"].to_list()
    closes: list[float] = bars["close"].to_list()
    out: dict[date, RealizedPoint] = {}
    for i in range(RV_WINDOW, len(closes)):
        day = ts[i].date()
        known = datetime.combine(day + timedelta(days=1), time.min, UTC)  # end of the bar's day
        window = closes[i - RV_WINDOW : i + 1]
        logs = [math.log(b / a) for a, b in zip(window, window[1:], strict=False)]
        out[day] = RealizedPoint(annualized_volatility(logs), known)
    return out


def _cell(p: DerivedPoint) -> str:
    if p.value is not None:
        return f"{p.value:.6g}"
    return f"null ({REASON_WORDS.get(p.reason or '', p.reason or 'unknown')})"


def _counts(points: tuple[DerivedPoint, ...]) -> dict[str, object]:
    reasons = Counter(p.reason or "unknown" for p in points if p.value is None)
    got = [p.day for p in points if p.value is not None]
    return dict(
        sessions=len(points),
        with_value=len(got),
        first=got[0].isoformat() if got else None,
        last=got[-1].isoformat() if got else None,
        null_by_reason=dict(sorted(reasons.items())),
    )


def _coverage(name: str, cov: dict[str, object], held: int) -> str:
    span = f"{cov['first']} to {cov['last']}" if cov["first"] else "none"
    nulls = cov["null_by_reason"]
    why = ", ".join(f"{r} {n}" for r, n in nulls.items()) if isinstance(nulls, dict) else ""
    return (
        f"Coverage {name}: {cov['with_value']} of {cov['sessions']} sessions have a value "
        f"({span}); nulls: {why or 'none'}; {held} snapshot(s) held back in the reserved period."
    )


@options_app.command("derived")
def derived(
    underlying: Annotated[str, typer.Argument(help="Underlying id of the stored chains.")],
    series: Annotated[
        list[str] | None, typer.Option("--series", help=f"One of {', '.join(SERIES)}; repeat.")
    ] = None,
    rows: Annotated[int, typer.Option("--rows", help="Newest sessions to show; 0 shows all.")] = 10,
    provider: Annotated[
        str | None, typer.Option(help="Provider folder; found if only one.")
    ] = None,
    rate: Annotated[float, typer.Option(help="Risk-free rate (the store has none).")] = 0.0,
    dividend_yield: Annotated[
        float, typer.Option(help="Dividend yield, used where no parity forward exists.")
    ] = 0.0,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show iv30, IV rank and percentile, 25-delta skew, term slope and IV minus realized vol."""
    chosen = tuple(series or SERIES)
    root = AlphaSettings().data_dir
    try:
        cfg = SurfaceConfig(rate=rate, dividend_yield=dividend_yield)
        name = _provider(root, underlying, provider)
        read = OptionsStore(root).snapshots_as_of(name, underlying, datetime.now(UTC))
        realized = _realized(underlying, root) if "iv_minus_rv" in chosen else {}
        result = derive(read, cfg, series=chosen, realized=realized)
    except (DataError, OSError, pl.exceptions.PolarsError) as exc:
        said = str(exc).rstrip(".")
        if said.startswith("No options data is stored yet"):
            typer.echo(f"{said}.", err=True)
        else:
            typer.echo(f"{said}. Next: check the underlying and --series.", err=True)
        raise typer.Exit(2) from None
    shown = {n: (pts[-rows:] if rows > 0 else pts) for n, pts in result.series.items()}
    coverage = {n: _counts(pts) for n, pts in result.series.items()}
    payload = dict(
        underlying=underlying,
        provider=name,
        sessions=result.sessions,
        held_back=result.held_back,
        reading=READING,
        rate=rate,
        dividend_yield=dividend_yield,
        coverage=coverage,
        series={
            n: [
                dict(
                    date=p.day.isoformat(),
                    value=p.value,
                    known_from=p.known_from.isoformat(),
                    reason=p.reason,
                    label=p.label,
                )
                for p in pts
            ]
            for n, pts in shown.items()
        },
    )
    lines: list[str] = []
    for n, pts in shown.items():
        lines.append(f"{n}  {HINTS.get(n, '')}".rstrip())
        lines.append(f"{'date':<12}{'value':<46}known_from")
        lines += [f"{p.day!s:<12}{_cell(p):<46}{p.known_from:%Y-%m-%d %H:%M}Z" for p in pts]
        lines.append(_coverage(n, coverage[n], result.held_back))
    lines.append(f"Rate {rate:g}, dividend yield {dividend_yield:g} (the store records neither).")
    lines.append(READING)
    emit(payload, json_out=json_out, fallback="\n".join(lines))
