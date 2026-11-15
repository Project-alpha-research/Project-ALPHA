"""Read recorded rule trials and quote their stored facts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from alpha_cli._cli_json import emit
from alpha_cli.run_store import find_run_dir, read_manifest
from alpha_cli.spine.errors import SpineError, fail
from alpha_cli.spine.facts import (
    TOOL_METRICS,
    build_facts,
    read_json,
    require_metric,
    tool_fact,
    tool_outputs,
)
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
                        "kind",
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
                key: "an investigation-tool row; see alpha results show for its output"
                if str(row["kind"]).startswith("tool:")
                else "unavailable in the stored ledger row"
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
        # Investigation-tool outputs live outside the immutable run directory.
        "tools": [
            {key: item[key] for key in ("tool", "id", "params", "recorded_at", "file", "labels")}
            for item in tool_outputs(home, run_id)
        ],
        "charts": [
            entry.definition.figure_id
            for entry in available_figures(rdir, manifest)
            if entry.available
        ],
    }


@results_app.command("show")
def show_results(run_id: str, json_out: bool = typer.Option(False, "--json")) -> None:
    """Show sourced facts, observations, audit checks, tool outputs and chart names."""
    try:
        home = AlphaSettings().data_dir
        failed: list[dict[str, Any]] = []
        if find_run_dir(home, run_id) is not None:
            ids = [run_id]
        else:
            # A test id: show every asset that completed and report each one that did not.
            rows = [
                row
                for row in read_trials(home)
                if row.get("test_id") == run_id and row["kind"] == "rule_test"
            ]
            ids = list(
                dict.fromkeys(
                    row["run_id"]
                    for row in rows
                    if row.get("run_id") and find_run_dir(home, row["run_id"]) is not None
                )
            )
            failed = [
                {
                    "symbol": row.get("symbol"),
                    "run_id": row.get("run_id"),
                    "trial_index": row["trial_index"],
                    "reason": "this asset's trial did not complete; no run is stored for it",
                }
                for row in rows
                if not row.get("run_id") or row["run_id"] not in ids
            ]
        if not ids and not failed:
            raise SpineError(
                "UNKNOWN_RUN",
                f"Unknown run or test {run_id!r}.",
                "Run alpha results --json to list recorded runs.",
            )
        if ids == [run_id]:
            runs = [_show(home, run_id)]  # one named run: an unreadable artifact fails loud
        else:
            runs = []
            for value in ids:
                try:
                    runs.append(_show(home, value))
                except (ValueError, OSError, DataError) as exc:
                    # One unreadable asset must not hide the others; report it by name.
                    row = next(item for item in rows if item.get("run_id") == value)
                    failed.append(
                        {
                            "symbol": row.get("symbol"),
                            "run_id": value,
                            "trial_index": row["trial_index"],
                            "reason": f"stored run could not be read: {exc}",
                        }
                    )
        output = {"runs": runs, "failed": failed}
        emit(output, json_out=json_out, fallback=json.dumps(output, indent=2, allow_nan=False))
    except (ValueError, OSError, DataError) as exc:
        _error(exc, json_out)


@results_app.command("cite")
def cite_result(
    run_id: str,
    metric: str,
    tool_output: str | None = typer.Option(
        None, "--tool-output", help="Id of one stored tool output, when a tool ran more than once."
    ),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Quote exactly one stored fact; never recompute a metric."""
    try:
        require_metric(metric)
        home = AlphaSettings().data_dir
        rdir, _ = _run(home, run_id)
        if metric in TOOL_METRICS:
            fact = tool_fact(home, run_id, metric, tool_output)
        else:
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
