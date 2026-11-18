"""Produce a daily health sidecar and check every input byte before displaying a saved verdict."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import typer

from alpha_cli._runner import _calendar_for, combine_source_fingerprints
from alpha_cli.spine.setup_costs import EQUITY_PROVIDERS
from alpha_cli.spine.stores import _stores, resolve_asset
from alpha_core import DataError, UniverseMembership
from alpha_core.atomic import write_text
from alpha_data.health import GROUPS, LIMITATION, HealthReport, health_report, worst
from alpha_data.store import ParquetStore
from alpha_data.timeframe import DAILY, store_dir
from alpha_data.universe import parse_universe_csv


class StoredHealthReport(HealthReport):
    source_fingerprint: str
    universe_file: Path | None
    leaver_symbols: tuple[str, ...]
    peer_symbols: tuple[str, ...] | None = None


def _memberships(raw: bytes, path: Path) -> list[UniverseMembership]:
    if path.suffix.lower() == ".json":
        items = json.loads(raw)
        if not isinstance(items, list):
            raise DataError("universe JSON must contain a list of membership intervals")
        return [UniverseMembership.model_validate(item) for item in items]
    text = raw.decode("utf-8-sig")
    if csv.DictReader(io.StringIO(text)).fieldnames == ["symbol"]:
        return []  # A current symbol list supplies no membership history.
    return parse_universe_csv(text)


def _digest(path: Path) -> str | None:
    try:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except FileNotFoundError:
        # Absence is an input: later addition of actions or leaver bars invalidates the report.
        return None


def _peer_paths(store: ParquetStore, peer: str) -> dict[str, Path]:
    return {
        f"peer/{peer}/bars": store._bars_path(peer),
        f"peer/{peer}/provenance": store._provenance_path(peer),
    }


def _hashes(paths: dict[str, Path]) -> dict[str, str]:
    return {key: digest for key, path in paths.items() if (digest := _digest(path)) is not None}


def _inputs(
    store: ParquetStore,
    symbol: str,
    universe: Path | None,
    leavers: tuple[str, ...],
    peers: tuple[str, ...] = (),
) -> dict[str, str]:
    paths = {
        "bars": store._bars_path(symbol),
        "actions": store._actions_path(symbol),
        "provenance": store._provenance_path(symbol),
    }
    if universe is not None:
        paths["universe"] = universe
    for leaver in leavers:
        paths[f"leaver/{leaver}"] = store._bars_path(leaver)
    for peer in peers:
        paths.update(_peer_paths(store, peer))
    if any(store.promotion_pending(name) for name in (symbol, *leavers, *peers)):
        raise DataError("canonical data has a pending promotion")
    return _hashes(paths)


def _label(status: str) -> str:
    return status.replace("-", " ")


def _render(report: StoredHealthReport, json_out: bool) -> None:
    if json_out:
        typer.echo(report.model_dump_json())
        return
    typer.echo(f"Data health of {report.symbol}, checked {report.report_time:%Y-%m-%d %H:%M} UTC")
    for group in GROUPS:
        checks = [item for item in report.checks if item.group == group]
        typer.echo(f"\n{group.capitalize()}: {_label(worst(checks))}")
        for item in checks:
            dates = ", ".join(day.isoformat() for day in item.example_dates)
            shown = f" First dates: {dates}." if dates and item.status in {"warn", "fail"} else ""
            typer.echo(f"  {_label(item.status)}: {item.finding}{shown}")
    if report.peer_symbols is not None:
        count = len(report.peer_symbols)
        typer.echo(f"{count} stock {'peer' if count == 1 else 'peers'} used.")
    typer.echo(f"\nVerdict: {_label(report.verdict)}")
    typer.echo(f"What this cannot tell you: {LIMITATION}")


def _read_saved(data_dir: Path, asset: str, universe: Path | None, json_out: bool) -> None:
    # Resolve by file presence so even deleted or unreadable source bytes invalidate a sidecar.
    symbol, separator, requested = asset.partition("@")
    stores = _stores(data_dir)
    if separator and requested not in stores:
        raise DataError(f"unknown store {requested!r}")
    for directory in [stores[requested]] if separator else stores.values():
        store = ParquetStore(store_dir(directory, DAILY))
        provenance = store._provenance_path(symbol)
        path = store.root / "health" / f"{symbol}.json"
        if path.is_file() or provenance.is_file():
            break
    else:
        raise DataError(f"no stored health report for {asset!r}")
    saved = read_report(store, symbol)
    if saved is None:
        raise DataError(f"no stored health report for {asset!r}")
    if (universe is not None and universe != saved.universe_file) or (
        saved.source_fingerprint != current_fingerprint(store, symbol, saved)
    ):
        typer.echo(
            json.dumps({"symbol": symbol, "status": "out of date"}) if json_out else "out of date"
        )
        return
    _render(saved, json_out)


def run_health(
    data_dir: Path, asset: str, universe: Path | None, stored: bool, json_out: bool
) -> None:
    if universe is not None:
        universe = universe.resolve()
    if stored:
        _read_saved(data_dir, asset, universe, json_out)
        return
    resolved = resolve_asset(asset, data_dir=data_dir)
    store = resolved.daily_store()
    symbol = resolved.symbol
    saved = compute_report(store, symbol, universe, datetime.now(UTC))
    _render(saved, json_out)


def read_report(store: ParquetStore, symbol: str) -> StoredHealthReport | None:
    path = store.root / "health" / f"{symbol}.json"
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    saved = StoredHealthReport.model_validate_json(raw)
    if saved.symbol != symbol:
        raise DataError(f"health sidecar at {path} names a different symbol")
    return saved


def current_fingerprint(store: ParquetStore, symbol: str, saved: StoredHealthReport | None) -> str:
    if saved is None:
        return combine_source_fingerprints(_inputs(store, symbol, None, ()))
    return combine_source_fingerprints(
        _inputs(store, symbol, saved.universe_file, saved.leaver_symbols, saved.peer_symbols or ())
    )


def _stock_calendar(symbol: str, provenance: dict[str, object] | None) -> str | None:
    if provenance is None:
        return None
    dataset = provenance.get("dataset")
    if isinstance(dataset, dict) and dataset["asset_class"] not in {"stock", "etf"}:
        return None
    if dataset is None and not EQUITY_PROVIDERS.intersection(
        str(provenance["source"]).lower().split(":")
    ):
        return None
    return _calendar_for(symbol, provenance)


def _dates(frame: pl.DataFrame, cutoff: datetime) -> set[date]:
    return {
        ts.astimezone(UTC).date()
        for ts in frame["ts"]
        if isinstance(ts, datetime) and ts.utcoffset() is not None and ts <= cutoff
    }


def _stock_peers(
    store: ParquetStore, symbol: str, calendar: str, bars: pl.DataFrame, cutoff: datetime
) -> tuple[dict[str, pl.DataFrame], dict[str, str]]:
    dates = _dates(bars, cutoff)
    frames: dict[str, pl.DataFrame] = {}
    digests: dict[str, str] = {}
    for name in store.list_symbols():
        if name == symbol:
            continue
        paths = _peer_paths(store, name)
        provenance = f"peer/{name}/provenance"
        before = _hashes({provenance: paths[provenance]})
        if _stock_calendar(name, store.read_provenance(name)) != calendar:
            continue
        price = f"peer/{name}/bars"
        before.update(_hashes({price: paths[price]}))
        frame = store.read_bars(name)
        if dates.isdisjoint(_dates(frame, cutoff)):
            continue
        frames[name] = frame
        digests.update(before)
        if len(frames) == 20:
            break
    return frames, digests


def compute_report(
    store: ParquetStore,
    symbol: str,
    universe: Path | None,
    cutoff: datetime,
    *,
    use_peers: bool = False,
) -> StoredHealthReport:
    path = store.root / "health" / f"{symbol}.json"
    raw = universe.read_bytes() if universe is not None else b""
    history = _memberships(raw, universe) if universe is not None else None
    leavers = tuple(
        sorted(
            {
                row.symbol
                for row in history or ()
                if row.effective_to is not None and row.effective_to <= cutoff.date()
            }
        )
    )
    before = _inputs(store, symbol, universe, leavers)
    bars = store.read_bars(symbol)
    if universe is not None and _digest(universe) != hashlib.sha256(raw).hexdigest():
        raise DataError("membership history changed during the health check")
    provenance = store.read_provenance(symbol)
    dataset = provenance.get("dataset") if provenance else None
    if isinstance(dataset, dict) and dataset["asset_class"] not in {"stock", "etf", "crypto"}:
        raise DataError("daily health supports stocks, ETFs and crypto")
    frames = {name: store.read_bars(name) for name in leavers if store._bars_path(name).exists()}
    calendar = _stock_calendar(symbol, provenance) if use_peers else None
    peers: dict[str, pl.DataFrame] = {}
    if calendar:
        peers, hashes = _stock_peers(store, symbol, calendar, bars, cutoff)
        before.update(hashes)
    report = health_report(
        bars,
        peers=list(peers.values()),
        symbol=symbol,
        calendar=_calendar_for(symbol, provenance),
        report_time=cutoff,
        actions=store.read_actions(symbol),
        memberships=history,
        universe_bars=None if universe is None else frames,
    )
    if before != _inputs(store, symbol, universe, leavers, tuple(peers)):
        raise DataError("source changed during the health check")
    saved = StoredHealthReport(
        **report.model_dump(),
        source_fingerprint=combine_source_fingerprints(before),
        peer_symbols=tuple(peers) if calendar else None,
        universe_file=universe,
        leaver_symbols=leavers,
    )
    write_text(path, saved.model_dump_json(indent=2) + "\n")
    return saved
