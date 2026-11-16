"""Read recorded rule trials and quote their stored facts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from alpha_cli._cli_json import emit
from alpha_cli.run_store import find_run_dir, read_manifest
from alpha_cli.spine.errors import SpineError, fail
from alpha_cli.spine.facts import build_facts, read_json, require_metric
from alpha_cli.spine.ledger import read_trials
from alpha_core import DataError
from alpha_core.config import AlphaSettings

results_app = typer.Typer(
    help="List rule tests and quote their stored results.", invoke_without_command=True
)


def _run(home: Path, run_id: str) -> tuple[Path, dict[str, Any]]:
    rdir = find_run_dir(home, run_id)
    if rdir is None:
        raise SpineError(
            "UNKNOWN_RUN",
            f"Unknown completed run {run_id!r}.",
            "Run alpha results --json to list recorded runs.",
        )
    return rdir, read_manifest(rdir)


def _error(exc: ValueError | OSError | DataError, json_out: bool) -> None:
    fail(
        exc
        if isinstance(exc, SpineError)
        else SpineError(
            "INVALID_ARTIFACT",
            str(exc),
            "Run alpha test again from the saved spec after correcting the artifact error.",
        ),
        json_out,
    )


@results_app.callback()
def list_results(
    ctx: typer.Context,
    limit: int = typer.Option(20, min=1, help="Maximum rows, newest first."),
    symbol: str | None = None,
    name: str | None = None,
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List recorded trials, including failed attempts, and the total count."""
    if ctx.invoked_subcommand is not None:
        return
    try:
        rows = read_trials(AlphaSettings().data_dir)
        if not rows:
            raise SpineError(
                "EMPTY_LEDGER",
                "No rule trials are recorded.",
                "Run alpha test with a saved spec or rule flags.",
            )
        selected = [
            row
            for row in reversed(rows)
            if (symbol is None or row.get("symbol") == symbol)
            and (name is None or row.get("name") == name)
        ][:limit]
        items = [
            {
                **{
                    key: row.get(key)
                    for key in (
                        "trial_index",
                        "recorded_at",
                        "name",
                        "symbol",
                        "verdict",
                        "oos_sharpe",
                        "benchmark_sharpe",
                        "labels",
                        "run_id",
                    )
                },
                "flags_count": len(row["flags"]) if isinstance(row.get("flags"), list) else None,
            }
            for row in selected
        ]
        lines = ["\t".join(str(row[key]) for key in row) for row in items]
        for row in items:
            row["reasons"] = {
                key: "unavailable in the stored ledger row"
                for key in ("oos_sharpe", "benchmark_sharpe", "flags_count")
                if row[key] is None
            }
        lines.append(f"Total trials: {len(rows)}")
        emit(
            {"items": items, "total_trials": len(rows)},
            json_out=json_out,
            fallback="\n".join(lines),
        )
    except (ValueError, OSError, DataError) as exc:
        _error(exc, json_out)


def _show(home: Path, run_id: str) -> dict[str, Any]:
    from alpha_cli.figures import available_figures

    rdir, manifest = _run(home, run_id)
    diagnostics = read_json(rdir / "diagnostics.json")
    return {
        "run_id": run_id,
        "facts": build_facts(rdir),
        "labels": manifest.get("spine", {}).get("labels", []),
        "flags": diagnostics.get("flags", []),
        "audit": diagnostics.get("audit", []),
        "diagnostics_reason": None
        if diagnostics
        else "diagnostics.json is unavailable; re-run alpha test for this spec",
        "charts": [
            entry.definition.figure_id
            for entry in available_figures(rdir, manifest)
            if entry.available
        ],
    }


@results_app.command("show")
def show_results(run_id: str, json_out: bool = typer.Option(False, "--json")) -> None:
    """Show sourced facts, observations, audit checks and chart names for a run or test."""
    try:
        home = AlphaSettings().data_dir
        if find_run_dir(home, run_id) is not None:
            ids = [run_id]
        else:
            ids = list(
                dict.fromkeys(
                    row["run_id"]
                    for row in read_trials(home)
                    if row.get("test_id") == run_id and row.get("run_id")
                )
            )
        if not ids:
            raise SpineError(
                "UNKNOWN_RUN",
                f"Unknown run or test {run_id!r}.",
                "Run alpha results --json to list recorded runs.",
            )
        output = {"runs": [_show(home, value) for value in ids]}
        emit(output, json_out=json_out, fallback=json.dumps(output, indent=2, allow_nan=False))
    except (ValueError, OSError, DataError) as exc:
        _error(exc, json_out)


@results_app.command("cite")
def cite_result(run_id: str, metric: str, json_out: bool = typer.Option(False, "--json")) -> None:
    """Quote exactly one stored fact; never recompute a metric."""
    try:
        require_metric(metric)
        rdir, _ = _run(AlphaSettings().data_dir, run_id)
        fact = next(item for item in build_facts(rdir) if item["metric"] == metric)
        value = "null" if fact["value"] is None else str(fact["value"])
        emit(fact, json_out=json_out, fallback=f"{value} [{run_id}:{metric}] ({fact['basis']})")
    except (ValueError, OSError, DataError) as exc:
        _error(exc, json_out)


def diagnose_run(run_id: str, json_out: bool = typer.Option(False, "--json")) -> None:
    """Read the automatic diagnostic pass and audit stored with a rule test."""
    try:
        rdir, _ = _run(AlphaSettings().data_dir, run_id)
        if not (rdir / "diagnostics.json").exists():
            raise SpineError(
                "NO_DIAGNOSTICS",
                f"Run {run_id} has no diagnostics.json.",
                f"Re-run alpha test with diagnostics enabled using the original spec for {run_id}.",
            )
        output = read_json(rdir / "diagnostics.json")
        emit(output, json_out=json_out, fallback=json.dumps(output, indent=2, allow_nan=False))
    except (ValueError, OSError, DataError) as exc:
        _error(exc, json_out)
