"""Rows for the default `alpha results` list from runs the trial ledger does not hold.

An ML run has a ledger row but no stored rule-test reading; its reading is the one `alpha report`
prints (`ml_reading`). Forecast, forecast-eval and Monte Carlo runs write no ledger row, so their
rows are read from the run folders. A run folder keeps no time (the id is a hash), so the time of a
folder row is the time its manifest file was written.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpha_cli.run_store import RUN_DIRS, read_manifest
from alpha_core import DataError

FOLDER_KINDS = ("forecast_run", "forecast_eval", "monte_carlo_classical", "monte_carlo_kronos")
NOT_HELD = "not kept for this kind of run"


def _pct(value: Any) -> str:
    return f"{float(value) * 100:+.1f}%"


def _forecast_sentence(manifest: dict[str, Any]) -> str:
    summary = manifest.get("summary")
    run = manifest.get("command") == "forecast_run"
    lead = f"Forecast {'run' if run else 'check'} for {manifest.get('symbol')}"
    if not isinstance(summary, dict):
        return f"{lead}: no summary is stored."
    if run:
        return (
            f"{lead}: median end return {_pct(summary['median_end_return'])}, middle 90% "
            f"{_pct(summary['p05_end_return'])} to {_pct(summary['p95_end_return'])}."
        )
    return (
        f"{lead}: skill vs random walk {_pct(summary['skill_vs_rw'])}, vs bootstrap "
        f"{_pct(summary['skill_vs_bootstrap'])}, hit rate {summary['hit_rate']:.0%}."
    )


def short_reading(rdir: Path, manifest: dict[str, Any]) -> str:
    """A short owner sentence for a forecast, forecast-eval or Monte Carlo run."""
    if str(manifest.get("command", "")).startswith("monte_carlo"):
        from alpha_cli import _mc_reading

        if not all((rdir / name).is_file() for name in _mc_reading.READS):
            return "Monte Carlo run: its stored paths are missing"
        return _mc_reading.stored_lines(rdir, manifest)[0]
    return _forecast_sentence(manifest)


def folder_rows(home: Path) -> list[dict[str, Any]]:
    """One list row per stored forecast, forecast-eval or Monte Carlo run."""
    rows: list[dict[str, Any]] = []
    for subdir in RUN_DIRS:
        for path in sorted((home / subdir).glob("*/manifest.json")):
            manifest = read_manifest(path.parent)
            kind = manifest.get("command")
            if kind not in FOLDER_KINDS:
                continue
            stamp = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
            rows.append(
                {
                    "kind": kind,
                    "name": kind,
                    "symbol": manifest.get("symbol"),
                    "run_id": path.parent.name,
                    "recorded_at": stamp,
                    "trial_index": None,
                    "verdict": None,
                    "labels": [],
                    "idea_id": None,
                    "evidence": short_reading(path.parent, manifest),
                    "oos_sharpe": None,
                    "benchmark_sharpe": None,
                    "flags": None,
                    "from_folder": True,
                }
            )
    return rows


def ml_fields(home: Path, row: dict[str, Any]) -> dict[str, Any]:
    """The reading word and Sharpe numbers `alpha report` shows for the ML run of a ledger row."""
    from alpha_cli.ml_reading import is_ml_manifest, ml_reading
    from alpha_cli.run_store import find_run_dir

    rdir = find_run_dir(home, str(row.get("run_id") or ""))
    try:
        manifest = read_manifest(rdir) if rdir is not None else None
        if rdir is None or manifest is None or not is_ml_manifest(manifest):
            return {}
        reading = ml_reading(home, rdir, manifest)
    except (ValueError, OSError, DataError):
        return {}
    return {
        "evidence": reading["evidence"],
        "oos_sharpe": reading["out_of_sample_sharpe"],
        "benchmark_sharpe": reading["equal_weight_basket_sharpe"],
        "reading": reading,
    }


def forecast_show(rdir: Path, manifest: dict[str, Any], run_id: str) -> dict[str, Any]:
    """`alpha results show` for a forecast or forecast-eval run: the same sentence as the list."""
    from alpha_cli.figures import available_figures

    return {
        "run_id": run_id,
        "reading": {"kind": "forecast", "sentence": short_reading(rdir, manifest)},
        "data_health": None,
        "facts": [],
        "labels": [],
        "flags": [],
        "audit": [],
        "tool_history": [],
        "tools": [],
        "tool_counts": {},
        "charts": [
            entry.definition.figure_id
            for entry in available_figures(rdir, manifest)
            if entry.available
        ],
    }
