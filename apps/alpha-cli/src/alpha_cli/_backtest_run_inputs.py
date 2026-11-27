"""The inputs of one ``alpha backtest run``.

They are its timeframes, its bars and dividends, and its bars per year.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from alpha_cli import _runner
from alpha_core import Bar, CorporateAction, DataError
from alpha_data.timeframe import BarTimeframe, parse_timeframe

# monkeypatchable load seams (mirror data_cmds._ADAPTERS); tests point them at fixture stores
_load_bars = _runner.load_bars
_load_dividends = _runner.load_dividends

# Suite-injected when a governed project's research gate was owner-overridden (spec §15,
# ADR-0026). Safe on the public CLI: it only ever downgrades the run's presentation (adds the
# EXPLORATORY watermark and forks run identity), never upgrades or grants authority.
_RESEARCH_GATE_OVERRIDE_HELP = (
    "watermark this run EXPLORATORY / RESEARCH GATE NOT COMPLETED "
    "(launched under an owner research-gate override)"
)


def _load_run_bars(
    symbol: str,
    *,
    data_dir: Path,
    snapshot: str | None,
    as_of: datetime | None,
    target: BarTimeframe,
    stored: BarTimeframe,
    session: str | None,
    manifest_id: str | None,
    resampled: bool,
) -> tuple[str, list[Bar], str | None, list[CorporateAction], dict[str, str | None]]:
    """Bars, dividends and the extra identity fields of one ``backtest run`` read.

    A daily run from the store or a snapshot returns no extra fields, so its identity inputs and
    manifest keys are unchanged; any other read names its timeframe, source timeframe, session and
    archive manifest.
    """
    scope: str
    if manifest_id is not None:
        from alpha_cli._archive_bars import load_archive_bars
        from alpha_cli.crypto_data_cmds import _bulk_store
        from alpha_data.sessions import check_session

        scope = session or "continuous"
        check_session(scope, None)
        bars = load_archive_bars(
            _bulk_store(),
            manifest_id,
            symbol=symbol,
            timeframe=target,
            source_timeframe=stored,
            as_of=as_of,
        )
        if len(bars) < 2:
            raise DataError(f"need >= 2 bars for {symbol!r}, got {len(bars)}")
        symbol, snapshot_id, dividends = bars[0].symbol, None, []
    else:
        bars, snapshot_id = _load_bars(
            symbol,
            data_dir=data_dir,
            snapshot_id=snapshot,
            as_of=as_of,
            timeframe=target.canonical,
            source_timeframe=stored.canonical,
            session=session,
        )
        dividends = _load_dividends(
            symbol,
            data_dir=data_dir,
            snapshot_id=snapshot,
            as_of=as_of,
            timeframe=target.canonical,
            source_timeframe=stored.canonical,
            session=session,
        )
    if target.is_daily and manifest_id is None and not resampled:
        return symbol, bars, snapshot_id, dividends, {}
    if manifest_id is None:
        _, _, scope = _runner._bar_store(
            symbol, data_dir=data_dir, snapshot_id=snapshot, stored=stored, session=session
        )
    fields: dict[str, str | None] = {
        "timeframe": target.canonical,
        "source_timeframe": stored.canonical,
        "session": scope,
        "manifest_id": manifest_id,
    }
    return symbol, bars, snapshot_id, dividends, fields


def _annualised(
    spec: _runner.RunSpec,
    bars: list[Bar],
    target: BarTimeframe,
    fields: dict[str, str | None],
    override: int | None,
) -> _runner.RunSpec:
    """Set bars per year from the bar size and session (daily: 252) unless the owner gave it."""
    ppy = _runner.resolve_periods_per_year(
        bars, timeframe=target, session=fields.get("session"), override=override
    )
    return replace(spec, periods_per_year=ppy)


def _run_timeframes(
    timeframe: str, from_timeframe: str | None, manifest_id: str | None, snapshot: str | None
) -> tuple[BarTimeframe, BarTimeframe]:
    """The run's bar timeframe and the stored one it is read (and maybe resampled) from."""
    if manifest_id is not None and snapshot is not None:
        raise DataError("--manifest-id and --snapshot are mutually exclusive")
    return parse_timeframe(timeframe), parse_timeframe(from_timeframe or timeframe)
