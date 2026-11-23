"""Bounded MCP helpers for CLI-owned data reads and development jobs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from alpha_mcp import _invoke


def bound(name: str, value: int, maximum: int) -> int:
    if isinstance(value, bool) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be in 1..{maximum}")
    return value


def offset(value: int) -> int:
    if isinstance(value, bool) or value < 0:
        raise ValueError("offset must be non-negative")
    return value


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RuntimeError(f"alpha returned an invalid {label} projection")
    return cast(dict[str, Any], value)


def _objects(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RuntimeError(f"alpha returned an invalid {label} projection")
    return [_object(item, label) for item in value]


def _json(value: Mapping[str, object]) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("control request must contain finite JSON values") from exc


def _page(rows: list[dict[str, Any]], *, limit: int, start: int) -> dict[str, Any]:
    return {
        "items": rows[:limit],
        "limit": limit,
        "offset": start,
        "has_more": len(rows) > limit,
    }


def data_inventory(*, data_dir: Path) -> dict[str, Any]:
    """Every stored symbol — the starting point of data feasibility."""
    return _object(_invoke.run_json(["data", "symbols", "--json"], data_dir=data_dir), "symbols")


def data_quality(symbol: str, *, data_dir: Path) -> dict[str, Any]:
    """One symbol's source/qualification/promotion status (read-only)."""
    return _object(
        _invoke.run_json(["data", "source-status", symbol, "--json"], data_dir=data_dir),
        "source status",
    )


def data_candles(
    symbol: str,
    *,
    data_dir: Path,
    start: str | None = None,
    end: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Bounded point-in-time candle preview (last ``limit`` bars, ≤500 like discovery)."""
    limit = bound("limit", limit, 500)
    args = ["data", "candles", symbol]
    if start is not None:
        args += ["--start", start]
    if end is not None:
        args += ["--end", end]
    args += ["--json"]
    payload = _object(_invoke.run_json(args, data_dir=data_dir), "candles")
    bars = payload.get("bars")
    if not isinstance(bars, list):
        raise RuntimeError("alpha returned an invalid candles projection")
    truncated = len(bars) > limit
    return {**payload, "bars": bars[-limit:], "truncated": truncated}


def snapshots(*, data_dir: Path) -> dict[str, Any]:
    """Every immutable snapshot's manifest summary."""
    return _object(
        _invoke.run_json(["data", "snapshots", "--json"], data_dir=data_dir), "snapshots"
    )


def provider_registry(*, data_dir: Path) -> dict[str, Any]:
    """The redacted provider capability/limitation registry (never probes the network)."""
    rows = _objects(
        _invoke.run_json(["info", "providers", "--json"], data_dir=data_dir), "providers"
    )
    return {"providers": rows}


def create_job(
    kind: str,
    request: Mapping[str, object],
    *,
    data_dir: Path,
    project_id: str | None,
    experiment_id: str | None,
) -> dict[str, Any]:
    args = ["project", "job-create", kind, "--request-json", _json(request)]
    if project_id is not None:
        args += ["--project-id", project_id]
    if experiment_id is not None:
        args += ["--experiment-id", experiment_id]
    args.append("--json")
    return _object(_invoke.run_json(args, data_dir=data_dir), "development job")


def list_jobs(*, data_dir: Path, limit: int, start: int) -> dict[str, Any]:
    limit = bound("limit", limit, 100)
    start = offset(start)
    rows = _objects(
        _invoke.run_json(
            [
                "project",
                "job-list",
                "--limit",
                str(limit + 1),
                "--offset",
                str(start),
                "--json",
            ],
            data_dir=data_dir,
        ),
        "development jobs",
    )
    return _page(rows, limit=limit, start=start)


def get_job(
    job_id: str, *, data_dir: Path, event_limit: int, event_offset: int = 0
) -> dict[str, Any]:
    event_limit = bound("event_limit", event_limit, 200)
    event_offset = offset(event_offset)
    row = _object(
        _invoke.run_json(
            [
                "project",
                "job-show",
                job_id,
                "--event-limit",
                str(event_limit),
                "--event-offset",
                str(event_offset),
                "--event-tail",
                "--json",
            ],
            data_dir=data_dir,
        ),
        "development job",
    )
    row["events"] = _objects(row.get("events"), "development job events")
    return row


def cancel_job(job_id: str, *, data_dir: Path, reason: str) -> dict[str, Any]:
    job = get_job(job_id, data_dir=data_dir, event_limit=1)
    if not str(job.get("kind", "")).startswith("suite:"):
        raise ValueError("only resolved suite jobs can be cancelled through MCP")
    return _object(
        _invoke.run_json(
            [
                "project",
                "job-cancel",
                job_id,
                "--actor",
                "mcp-agent",
                "--reason",
                reason,
                "--json",
            ],
            data_dir=data_dir,
        ),
        "job cancellation",
    )


def reconcile_jobs(*, data_dir: Path, stale_after_seconds: int) -> dict[str, Any]:
    if isinstance(stale_after_seconds, bool) or not 30 <= stale_after_seconds <= 86_400:
        raise ValueError("stale_after_seconds must be in 30..86400")
    rows = _objects(
        _invoke.run_json(
            [
                "project",
                "job-reconcile",
                "--stale-after-seconds",
                str(stale_after_seconds),
                "--json",
            ],
            data_dir=data_dir,
        ),
        "reconciled jobs",
    )
    return {"items": rows, "count": len(rows)}


__all__ = [
    "bound",
    "cancel_job",
    "create_job",
    "get_job",
    "list_jobs",
    "offset",
    "reconcile_jobs",
]
