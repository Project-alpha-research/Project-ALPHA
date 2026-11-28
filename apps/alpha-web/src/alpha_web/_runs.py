"""Filesystem reads over the run store for the workstation (same store the CLI + MCP server use).

``alpha`` writes a byte-stable ``manifest.json`` per run under one of a few run-type directories
(plus an ``equity_curve.parquet`` and ``tearsheet.html`` for engine runs). These helpers read them
back for the run browser and run detail — no engine, no subprocess.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import polars as pl

from alpha_cli.artifact_contract import verify_manifest_artifacts
from alpha_cli.run_store import (
    RUN_DIRS,
    find_run_dir,
    research_gate_watermark,
    run_context_projection,
)
from alpha_core import DataError
from alpha_web import _rule_test

MAX_MANIFEST_BYTES = 8 * 1024 * 1024


def _verified_manifest(rdir: Path) -> dict[str, Any]:
    """Read one bounded manifest and verify every declared v3 artifact before projection."""
    path = rdir / "manifest.json"
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise DataError(f"run manifest exceeds {MAX_MANIFEST_BYTES} bytes at {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise DataError(f"corrupt run manifest at {path}") from exc
    if not isinstance(value, dict):
        raise DataError(f"invalid run manifest at {path}: expected an object")
    verify_manifest_artifacts(rdir, value)
    return value


def _run_dir(run_id: str, *, data_dir: Path) -> Path | None:
    return find_run_dir(data_dir, run_id)


def _artifact_frame(
    run_id: str,
    filename: str,
    *,
    data_dir: Path,
    sort: tuple[str, ...] = (),
) -> pl.DataFrame | None:
    """A run's parquet artifact, sorted; None when the run is absent or the file unwritten."""
    rdir = _run_dir(run_id, data_dir=data_dir)
    if rdir is None:
        return None
    _verified_manifest(rdir)
    path = rdir / filename
    if not path.exists():
        return None
    frame = pl.read_parquet(path)
    return frame.sort(*sort) if sort else frame


# --- workstation JSON API helpers (richer indexing/series for the SPA panels) ------------------

# run_record cache keyed on manifest path — invalidated by mtime, so the index endpoint re-reads
# only changed manifests (the activity stream turns /api/runs into a per-event hot path).
_RECORD_CACHE: dict[Path, tuple[float, dict[str, Any]]] = {}
_READABLE_CACHE: dict[Path, tuple[float, bool]] = {}

_REQUIRED_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "backtest_run": (
        "equity_curve.parquet",
        "trades.parquet",
        "calendar_returns.parquet",
        "return_distribution.parquet",
        "rolling_metrics.parquet",
    ),
    "validate": (
        "equity_curve.parquet",
        "trades.parquet",
        "nulls.parquet",
        "tearsheet.html",
        "calendar_returns.parquet",
        "return_distribution.parquet",
        "rolling_metrics.parquet",
    ),
    "backtest_portfolio": (
        "equity_curve.parquet",
        "tearsheet.html",
        "calendar_returns.parquet",
        "return_distribution.parquet",
        "rolling_metrics.parquet",
    ),
    "backtest_cross_sectional": (
        "equity_curve.parquet",
        "tearsheet.html",
        "calendar_returns.parquet",
        "return_distribution.parquet",
        "rolling_metrics.parquet",
    ),
    "cross_sectional": (
        "equity_curve.parquet",
        "tearsheet.html",
        "calendar_returns.parquet",
        "return_distribution.parquet",
        "rolling_metrics.parquet",
    ),
    "optim_grid": ("trials.parquet",),
    "optim_mcpt": ("mcpt_null.parquet",),
    "propfirm_run": ("propfirm_paths.parquet",),
    "propfirm": ("propfirm_paths.parquet",),
    "forecast_run": ("paths.parquet", "quantiles.parquet", "history.parquet"),
    "forecast_eval": ("origins.parquet",),
    "monte_carlo_classical": (
        "observed_oos.parquet",
        "paths.parquet",
        "path_metrics.parquet",
        "regime_diagnostics.parquet",
        "regime_emissions.parquet",
        "report.md",
    ),
    "monte_carlo_kronos": (
        "observed_oos.parquet",
        "synthetic_bars.parquet",
        "paths.parquet",
        "path_metrics.parquet",
        "model_diagnostics.json",
        "calibration_origins.parquet",
        "report.md",
    ),
}
_V3_TRACE_ARTIFACTS = (
    "decision_trace.parquet",
    "orders.parquet",
    "fills.parquet",
    "execution_trace.parquet",
    "indicator_series.parquet",
    "chart_annotations.parquet",
)


def _v3_artifacts_verified(rdir: Path, manifest: dict[str, Any]) -> bool:
    if manifest.get("run_identity_version") != 3 or manifest.get("artifact_contract_version") != 3:
        return False
    try:
        verify_manifest_artifacts(rdir, manifest)
    except DataError:
        return False
    return True


def run_artifacts_readable(kind: str, run_id: str, *, data_dir: Path) -> bool:
    """Whether a published manifest's required artifact set exists and can be opened."""
    rdir = data_dir / kind / run_id
    manifest_path = rdir / "manifest.json"
    try:
        mtime = manifest_path.stat().st_mtime
    except OSError:
        return False
    cached = _READABLE_CACHE.get(manifest_path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Pre-hardening/third-party manifests remain discoverable; current writers identify their
        # schema and are held to the full command-specific artifact contract.
        required = _REQUIRED_ARTIFACTS.get(str(manifest.get("command")), ())
        if manifest.get("schema_version") == 3 and manifest.get("command") in {
            "backtest_run",
            "validate",
        }:
            required = (*required, *_V3_TRACE_ARTIFACTS)
        if manifest.get("schema_version") == 3 and not _v3_artifacts_verified(rdir, manifest):
            return False
        if "schema_version" in manifest:
            for filename in required:
                path = rdir / filename
                if (
                    filename == "propfirm_paths.parquet"
                    and not path.exists()
                    and str(manifest.get("command")) == "propfirm_run"
                ):
                    path = rdir / "paths.parquet"  # complete pre-hardening prop-firm run
                if filename.endswith(".parquet"):
                    pl.read_parquet_schema(path)
                else:
                    path.read_text(encoding="utf-8")
        readable = True
    except (json.JSONDecodeError, OSError, pl.exceptions.PolarsError, UnicodeDecodeError):
        readable = False
    _READABLE_CACHE[manifest_path] = (mtime, readable)
    return readable


def _curve_period(rdir: Path) -> str | None:
    """Curve bounds, including UTC times whenever a day contains multiple samples."""
    path = rdir / "equity_curve.parquet"
    if not path.exists():
        return None
    bounds = (
        pl.scan_parquet(path)
        .select(
            pl.col("ts").min().alias("first"),
            pl.col("ts").max().alias("last"),
            (pl.col("ts").dt.convert_time_zone("UTC").dt.date().n_unique() < pl.len()).alias(
                "intraday"
            ),
        )
        .collect()
    )
    first, last, intraday = bounds.row(0)
    pattern = "%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d"
    return f"{first.strftime(pattern)} → {last.strftime(pattern)}"


def _manifest_identity_value(manifest: Mapping[str, Any], key: str) -> Any:
    """Resolve display identity, preserving even null or empty top-level values."""
    if key in manifest:
        return manifest[key]
    metadata = manifest.get("metadata")
    return metadata.get(key) if isinstance(metadata, Mapping) else None


def display_name(kind: str, run_id: str, manifest: dict[str, Any], rdir: Path) -> str:
    """The run's name as a trader reads it (spec 2026-09-01 §4.4):
    `<strategy> <timeframe> — <symbol> · <venue> · <start> → <end> · run <8 hex>`;
    legacy manifests default to D1; parts the manifest does not carry are omitted.
    A rule test (`alpha test`) is named `rule test <spec name>` in the strategy slot."""
    params = manifest.get("params")
    spine = _rule_test.spine_of(manifest)
    strategy = (
        (f"rule test {spine['name']}" if spine and spine.get("name") else None)
        or (params.get("strategy_name") if isinstance(params, dict) else None)
        or (manifest.get("command") or kind)
    )
    symbols = _manifest_identity_value(manifest, "symbols")
    symbol = _manifest_identity_value(manifest, "symbol") or (
        ", ".join(symbols) if symbols else None
    )
    parts = [part for part in (symbol, manifest.get("source"), _curve_period(rdir)) if part]
    raw_timeframe = manifest.get("timeframe")
    timeframe = raw_timeframe if isinstance(raw_timeframe, str) and raw_timeframe else "1D"
    label = timeframe[-1].upper() + timeframe[:-1]
    return f"{strategy} {label} — {' · '.join([*parts, f'run {run_id[:8]}'])}"


_CRYPTO_SOURCES = ("ccxt", "binance", "bybit", "coinbase")
_EQUITY_SOURCES = ("tiingo", "yfinance", "stooq", "quantpad", "alpaca")


def market_of(manifest: dict[str, Any]) -> str:
    """Which market a run belongs to (spec 2026-09-01 §4.1): decided server-side from the
    manifest's ``source`` first, then the ``BASE/QUOTE`` pair convention, else ``unknown`` —
    never guessed, never derived in the browser."""
    source = str(manifest.get("source") or "").lower()
    if source.startswith(_CRYPTO_SOURCES):
        return "crypto"
    if source.startswith(_EQUITY_SOURCES):
        return "equities"
    symbols = _manifest_identity_value(manifest, "symbols")
    candidates = [
        _manifest_identity_value(manifest, "symbol"),
        *(symbols if isinstance(symbols, list) else []),
    ]
    if any(isinstance(symbol, str) and "/" in symbol for symbol in candidates):
        return "crypto"
    return "unknown"


def _stored_evidence(reading: Any) -> str | None:
    """The evidence word a new run stored in its reading, or ``fault`` as the ledger writes it.

    Relayed, never worked out: a run without a stored reading gives ``None``.
    """
    if not isinstance(reading, dict):
        return None
    evidence = reading.get("evidence")
    word = evidence.get("word") if isinstance(evidence, dict) else None
    if isinstance(word, str):
        return word
    checks = reading.get("checks")
    faulted = isinstance(checks, list) and any(
        isinstance(c, dict) and c.get("state") == "fault" for c in checks
    )
    return "fault" if faulted else None


def run_record(kind: str, run_id: str, *, data_dir: Path) -> dict[str, Any]:
    """One run's browser record — THE shared shape of ``/api/runs`` index items and the activity
    stream's ``run_added``/``run_updated`` payloads (the SPA consumes both as ``RunListItem``).

    ``mtime`` is the ``manifest.json`` filesystem timestamp — deliberately NOT a manifest field,
    so time-ordering the browser never touches the byte-stable, wall-clock-free manifests.
    Raises ``OSError``/``json.JSONDecodeError`` on a vanished or mid-write manifest.
    """
    mpath = data_dir / kind / run_id / "manifest.json"
    mtime = mpath.stat().st_mtime
    # Artifact bytes can be tampered without touching the manifest mtime, so verification must
    # precede the metadata cache hit.
    manifest = _verified_manifest(mpath.parent)
    cached = _RECORD_CACHE.get(mpath)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    symbols = _manifest_identity_value(manifest, "symbols")
    symbol = _manifest_identity_value(manifest, "symbol")
    verdict = manifest.get("verdict")
    record = {
        "run_id": run_id,
        "kind": kind,
        "command": manifest.get("command"),
        "label": _manifest_identity_value(manifest, "label")
        or symbol
        or (", ".join(symbols) if symbols else None)
        or manifest.get("source"),
        "display_name": display_name(kind, run_id, manifest, mpath.parent),
        "market": market_of(manifest),
        "symbol": symbol,
        "symbols": symbols,
        "snapshot_id": _manifest_identity_value(manifest, "snapshot_id"),
        "snapshot_hash": manifest.get("snapshot_hash"),
        "passed": manifest.get("passed"),
        "verdict": verdict.get("overall") if isinstance(verdict, dict) else None,
        "evidence": _stored_evidence(manifest.get("reading")),
        # spec §15 / ADR-0026: the permanent EXPLORATORY marker on runs launched under an
        # owner research-gate override; None for every unmarked run.
        "research_gate_watermark": research_gate_watermark(manifest),
        **run_context_projection(manifest),
        "rule_test_labels": _rule_test.labels_of(manifest),
        "mtime": mtime,
    }
    _RECORD_CACHE[mpath] = (mtime, record)
    return record


def _index_runs(*, data_dir: Path) -> list[dict[str, Any]]:
    """Every stored run as a rich record (see ``run_record``), unsorted."""
    records: list[dict[str, Any]] = []
    for sub in RUN_DIRS:
        base = data_dir / sub
        if not base.is_dir():
            continue
        for rdir in base.iterdir():
            try:
                records.append(run_record(sub, rdir.name, data_dir=data_dir))
            except (OSError, json.JSONDecodeError):
                continue  # no/partial manifest yet — invisible until fully written
    return records


def query_runs(
    *,
    data_dir: Path,
    kind: str | None = None,
    symbol: str | None = None,
    verdict: str | None = None,
    passed: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Filtered, newest-first (mtime-desc), paginated run index for the run browser."""
    records = _index_runs(data_dir=data_dir)
    if kind is not None:
        records = [r for r in records if r["kind"] == kind]
    if symbol is not None:
        records = [
            r for r in records if r["symbol"] == symbol or (r["symbols"] and symbol in r["symbols"])
        ]
    if verdict is not None:
        records = [r for r in records if r["verdict"] == verdict]
    if passed is not None:
        records = [r for r in records if r["passed"] is passed]
    records.sort(key=lambda r: r["mtime"], reverse=True)
    total = len(records)
    return {"total": total, "items": records[offset : offset + limit]}


def run_detail(run_id: str, *, data_dir: Path) -> dict[str, Any]:
    """Full manifest + kind/mtime + artifact-presence flags. Fail loud if the run is absent."""
    rdir = _run_dir(run_id, data_dir=data_dir)
    if rdir is None:
        raise FileNotFoundError(f"no run {run_id!r} under {data_dir}")
    mpath = rdir / "manifest.json"
    kind = rdir.parent.name
    manifest = _verified_manifest(rdir)
    return {
        "run_id": run_id,
        "kind": kind,
        "mtime": mpath.stat().st_mtime,
        "display_name": display_name(kind, run_id, manifest, rdir),
        "market": market_of(manifest),
        "manifest": manifest,
        "research_gate_watermark": research_gate_watermark(manifest),
        **run_context_projection(manifest),
        "rule_test": _rule_test.rule_test(manifest, rdir),
        "has_equity": (rdir / "equity_curve.parquet").exists(),
        "has_trades": (rdir / "trades.parquet").exists(),
        "has_tearsheet": (rdir / "tearsheet.html").exists(),
        "has_forecast": (rdir / "quantiles.parquet").exists(),
        "has_nulls": (rdir / "nulls.parquet").exists(),
        "has_trials": (rdir / "trials.parquet").exists(),
        "has_forecast_paths": kind == "forecast" and (rdir / "paths.parquet").exists(),
        "has_propfirm_paths": kind == "propfirm"
        and ((rdir / "propfirm_paths.parquet").exists() or (rdir / "paths.parquet").exists()),
        "has_origins": (rdir / "origins.parquet").exists(),
        "has_portfolio_analytics": (rdir / "portfolio_allocations.parquet").exists()
        and (rdir / "correlations.parquet").exists(),
    }


def equity_series(run_id: str, *, data_dir: Path) -> dict[str, list[float]]:
    """Equity curve as ``{ts (epoch seconds), equity, drawdown}``; empty lists when no curve."""
    frame = _artifact_frame(run_id, "equity_curve.parquet", data_dir=data_dir)
    if frame is None:
        return {"ts": [], "equity": [], "drawdown": []}
    equity = [float(v) for v in frame["equity"].to_list()]
    ts = [t.timestamp() for t in frame["ts"].to_list()]
    peak = float("-inf")
    drawdown: list[float] = []
    for v in equity:
        peak = max(peak, v)
        drawdown.append(v / peak - 1.0 if peak > 0 else 0.0)
    return {"ts": ts, "equity": equity, "drawdown": drawdown}


MAX_NATIVE_TEARSHEET_POINTS = 5_000


def _bounded_rows(
    rows: list[dict[str, Any]], point_limit: int
) -> tuple[list[dict[str, Any]], dict[str, int | bool | str]]:
    """Deterministically retain both endpoints and uniformly sample oversized series."""
    original = len(rows)
    if original <= point_limit:
        return rows, {
            "original": original,
            "returned": original,
            "truncated": False,
            "sampling": "all",
        }
    # point_limit >= 2 and point_limit <= original: rounding an evenly spaced monotone grid
    # produces unique indices while preserving the first and last observations exactly.
    indices = [round(index * (original - 1) / (point_limit - 1)) for index in range(point_limit)]
    sampled = [rows[index] for index in indices]
    return sampled, {
        "original": original,
        "returned": len(sampled),
        "truncated": True,
        "sampling": "endpoint_uniform",
    }


def native_tearsheet(run_id: str, *, data_dir: Path, point_limit: int = 2_000) -> dict[str, Any]:
    """Typed, bounded Python-authored analytics; legacy runs report unavailable."""
    if not 2 <= point_limit <= MAX_NATIVE_TEARSHEET_POINTS:
        raise DataError(
            f"native tear-sheet point_limit must be in [2, {MAX_NATIVE_TEARSHEET_POINTS}]"
        )
    rdir = _run_dir(run_id, data_dir=data_dir)
    if rdir is None:
        raise FileNotFoundError(f"no run {run_id!r} under {data_dir}")
    calendar = _artifact_frame(run_id, "calendar_returns.parquet", data_dir=data_dir)
    distribution = _artifact_frame(run_id, "return_distribution.parquet", data_dir=data_dir)
    rolling = _artifact_frame(run_id, "rolling_metrics.parquet", data_dir=data_dir)
    exposure = _artifact_frame(run_id, "exposure_turnover.parquet", data_dir=data_dir)
    benchmark = _artifact_frame(run_id, "benchmark_comparison.parquet", data_dir=data_dir)
    trade_statistics = _artifact_frame(run_id, "trade_statistics.parquet", data_dir=data_dir)
    manifest = json.loads((rdir / "manifest.json").read_text(encoding="utf-8"))
    declared = manifest.get("artifacts")
    artifact_names = (
        "calendar_returns.parquet",
        "benchmark_comparison.parquet",
        "exposure_turnover.parquet",
        "return_distribution.parquet",
        "rolling_metrics.parquet",
        "trade_statistics.parquet",
    )
    provenance = {
        "run_id": run_id,
        "metric_namespace": "alpha_validation",
        "artifact_contract_version": manifest.get("artifact_contract_version"),
        "artifact_sha256": {
            name: declared[name]["sha256"]
            for name in artifact_names
            if isinstance(declared, dict)
            and isinstance(declared.get(name), dict)
            and isinstance(declared[name].get("sha256"), str)
        },
    }
    return _finish_native_tearsheet(
        point_limit=point_limit,
        calendar=calendar,
        distribution=distribution,
        rolling=rolling,
        exposure=exposure,
        benchmark=benchmark,
        trade_statistics=trade_statistics,
        provenance=provenance,
    )


def _finish_native_tearsheet(
    *,
    point_limit: int,
    calendar: pl.DataFrame | None,
    distribution: pl.DataFrame | None,
    rolling: pl.DataFrame | None,
    exposure: pl.DataFrame | None,
    benchmark: pl.DataFrame | None,
    trade_statistics: pl.DataFrame | None,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    empty_bound = {"original": 0, "returned": 0, "truncated": False, "sampling": "all"}
    empty_bounds = {
        "point_limit": point_limit,
        "qq": dict(empty_bound),
        "rolling": dict(empty_bound),
        "exposure_turnover": dict(empty_bound),
        "benchmark": dict(empty_bound),
    }
    if calendar is None or distribution is None or rolling is None:
        return {
            "available": False,
            "calendar_returns": [],
            "yearly_returns": [],
            "histogram": [],
            "qq": [],
            "rolling": [],
            "exposure_turnover": [],
            "benchmark": [],
            "trade_statistics": [],
            "exposure_available": False,
            "turnover_available": False,
            "benchmark_available": False,
            "trade_statistics_available": False,
            "provenance": provenance,
            "bounds": empty_bounds,
        }

    month_rows = calendar.filter(pl.col("period_type") == "month").sort("year", "month")
    year_rows = calendar.filter(pl.col("period_type") == "year").sort("year")
    histogram_rows = distribution.filter(pl.col("kind") == "histogram").sort("index")
    qq_rows = distribution.filter(pl.col("kind") == "qq").sort("index").to_dicts()
    rolling_rows = rolling.sort("ts").to_dicts()
    exposure_rows = [] if exposure is None else exposure.sort("start_ts").to_dicts()
    benchmark_rows = [] if benchmark is None else benchmark.sort("ts").to_dicts()
    trade_stat_rows = [] if trade_statistics is None else trade_statistics.sort("metric").to_dicts()
    exposure_available = bool(exposure_rows and exposure_rows[0].get("exposure_available") is True)
    turnover_available = bool(exposure_rows and exposure_rows[0].get("turnover_available") is True)
    benchmark_available = bool(benchmark_rows and benchmark_rows[0].get("available") is True)
    trade_statistics_available = bool(
        trade_stat_rows and any(row.get("available") is True for row in trade_stat_rows)
    )
    qq_rows, qq_bound = _bounded_rows(qq_rows, point_limit)
    rolling_rows, rolling_bound = _bounded_rows(rolling_rows, point_limit)
    exposure_rows, exposure_bound = _bounded_rows(exposure_rows, point_limit)
    benchmark_rows, benchmark_bound = _bounded_rows(benchmark_rows, point_limit)

    return {
        "available": True,
        "calendar_returns": [
            {
                "year": int(row["year"]),
                "month": int(row["month"]),
                "return_value": float(row["return_value"]),
            }
            for row in month_rows.iter_rows(named=True)
        ],
        "yearly_returns": [
            {"year": int(row["year"]), "return_value": float(row["return_value"])}
            for row in year_rows.iter_rows(named=True)
        ],
        "histogram": [
            {
                "left": float(row["left"]),
                "right": float(row["right"]),
                "count": int(row["count"]),
            }
            for row in histogram_rows.iter_rows(named=True)
        ],
        "qq": [
            {
                "probability": float(row["probability"]),
                "theoretical": float(row["theoretical"]),
                "sample": float(row["sample"]),
            }
            for row in qq_rows
        ],
        "rolling": [
            {
                "ts": row["ts"].timestamp(),
                "window": int(row["window"]),
                "return_value": float(row["return_value"]),
                "volatility": float(row["volatility"]),
                "sharpe": float(row["sharpe"]) if row["sharpe"] is not None else None,
                "gross_exposure": (
                    float(row["gross_exposure"]) if row.get("gross_exposure") is not None else None
                ),
                "net_exposure": (
                    float(row["net_exposure"]) if row.get("net_exposure") is not None else None
                ),
                "turnover": (float(row["turnover"]) if row.get("turnover") is not None else None),
                "exposure_available": row.get("exposure_available") is True,
                "turnover_available": row.get("turnover_available") is True,
            }
            for row in rolling_rows
        ],
        "exposure_turnover": [
            {
                "start_ts": row["start_ts"].timestamp(),
                "end_ts": row["end_ts"].timestamp(),
                "gross_exposure": (
                    float(row["gross_exposure"]) if row.get("gross_exposure") is not None else None
                ),
                "net_exposure": (
                    float(row["net_exposure"]) if row.get("net_exposure") is not None else None
                ),
                "turnover": (float(row["turnover"]) if row.get("turnover") is not None else None),
                "exposure_available": row.get("exposure_available") is True,
                "turnover_available": row.get("turnover_available") is True,
                "exposure_unavailable_reason": row.get("exposure_unavailable_reason"),
                "turnover_unavailable_reason": row.get("turnover_unavailable_reason"),
            }
            for row in exposure_rows
        ],
        "benchmark": [
            {
                "ts": row["ts"].timestamp(),
                "strategy_equity": float(row["strategy_equity"]),
                "benchmark_equity": (
                    float(row["benchmark_equity"])
                    if row.get("benchmark_equity") is not None
                    else None
                ),
                "strategy_return": (
                    float(row["strategy_return"])
                    if row.get("strategy_return") is not None
                    else None
                ),
                "benchmark_return": (
                    float(row["benchmark_return"])
                    if row.get("benchmark_return") is not None
                    else None
                ),
                "excess_return": (
                    float(row["excess_return"]) if row.get("excess_return") is not None else None
                ),
                "available": row.get("available") is True,
                "benchmark_kind": row.get("benchmark_kind"),
                "unavailable_reason": row.get("unavailable_reason"),
            }
            for row in benchmark_rows
        ],
        "trade_statistics": [
            {
                "metric": str(row["metric"]),
                "value": float(row["value"]) if row.get("value") is not None else None,
                "unit": str(row["unit"]),
                "available": row.get("available") is True,
                "unavailable_reason": row.get("unavailable_reason"),
            }
            for row in trade_stat_rows
        ],
        "exposure_available": exposure_available,
        "turnover_available": turnover_available,
        "benchmark_available": benchmark_available,
        "trade_statistics_available": trade_statistics_available,
        "provenance": provenance,
        "bounds": {
            "point_limit": point_limit,
            "qq": qq_bound,
            "rolling": rolling_bound,
            "exposure_turnover": exposure_bound,
            "benchmark": benchmark_bound,
        },
    }


def trades(run_id: str, *, data_dir: Path) -> list[dict[str, Any]]:
    """The run's trade log rows (datetimes serialized to ISO strings); ``[]`` when none written."""
    frame = _artifact_frame(run_id, "trades.parquet", data_dir=data_dir)
    if frame is None:
        return []
    rows: list[dict[str, Any]] = frame.to_dicts()
    for row in rows:
        for key in ("entry_ts", "exit_ts"):
            value = row.get(key)
            if value is not None and hasattr(value, "isoformat"):
                row[key] = value.isoformat()
    return rows
