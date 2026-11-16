"""Read recorded rule trials and quote their stored facts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from alpha_cli._cli_json import emit
from alpha_cli.run_store import RUN_DIRS, find_run_dir, read_manifest, valid_run_id
from alpha_cli.spine.check import FlagLookup, check_text, render_check
from alpha_cli.spine.compare import (
    DEFAULT_METRICS,
    Lookup,
    compare_runs,
    render_compare,
    resolve_run,
)
from alpha_cli.spine.errors import SpineError, fail, unreadable_file
from alpha_cli.spine.facts import build_facts, read_json, require_metric
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.trial_reader import family_counts, spine_snapshot
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
    rule = manifest.get("spine", {}).get("rule", {}).get("kind")
    family_id = f"spine:{rule}" if rule else None
    counts = family_counts(spine_snapshot(home))
    current = next(
        (row for row in counts if row["family_id"] == family_id),
        {"reader_trials": 0, "rows": 0, "outcomes": {}},
    )
    at_run = diagnostics.get("trials", {}).get("family", {}).get("n_trials_used")
    return {
        "family": {
            "family_id": family_id,
            "trials_at_run": at_run,
            "now": {key: current[key] for key in ("reader_trials", "rows", "outcomes")},
            "reason": None if at_run is not None else "recorded before family counts were used",
        },
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
                    for row in spine_snapshot(home).raw_rows.values()
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


def _run_paths(home: Path) -> dict[str, Path]:
    """Discover completed runs in the same precedence order as run lookup."""
    paths: dict[str, Path] = {}
    for directory in RUN_DIRS:
        for manifest in (home / directory).glob("*/manifest.json"):
            if valid_run_id(manifest.parent.name):
                paths.setdefault(manifest.parent.name, manifest.parent)
    return paths


def flag_lookup(home: Path) -> FlagLookup:
    """Read stored diagnostic flags for cited runs; missing diagnostics have none."""
    paths = _run_paths(home)

    def lookup(run_id: str) -> list[dict[str, str]]:
        flags: list[dict[str, str]] = read_json(
            paths[resolve_run(run_id, paths)] / "diagnostics.json"
        ).get("flags", [])
        return flags

    return lookup


def fact_lookup(home: Path) -> Lookup:
    """Discover completed runs; read each cited run's facts once, on demand."""
    paths = _run_paths(home)
    cache: dict[str, dict[str, dict[str, Any]]] = {}

    def lookup(prefix: str, metric: str) -> dict[str, Any]:
        require_metric(metric)
        run_id = resolve_run(prefix, paths)
        if run_id not in cache:
            cache[run_id] = {fact["metric"]: fact for fact in build_facts(paths[run_id])}
        if metric not in cache[run_id]:
            raise SpineError(
                "METRIC_NOT_STORED",
                f"Run {run_id} has no stored fact {metric} in its run folder.",
                "Cite tool facts with alpha results cite <run_id> <metric> --tool-output <id>.",
            )
        return cache[run_id][metric]

    return lookup


@results_app.command("check")
def check_answer(
    path: Path,
    json_out: bool = typer.Option(False, "--json"),
    allow_untagged: int = typer.Option(
        0, min=0, help="Tolerate this many untagged numbers as warnings."
    ),
) -> None:
    """Check a draft's tagged numbers, required labels and flags against stored facts."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        fail(unreadable_file(path, exc), json_out)
    try:
        home = AlphaSettings().data_dir
        result = check_text(text, fact_lookup(home), allow_untagged, flag_lookup(home))
        emit(result, json_out=json_out, fallback=render_check(result))
        if not result["ok"]:
            raise typer.Exit(1)
    except (ValueError, OSError, DataError) as exc:
        _error(exc, json_out)


@results_app.command("compare")
def compare_results(
    run_ids: Annotated[list[str], typer.Argument(help="Two to eight runs; first is base.")],
    metric: Annotated[
        list[str] | None, typer.Option("--metric", help="Metric; repeatable.")
    ] = None,
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Compare stored values, differences and ratios, with bases and run labels."""
    try:
        result = compare_runs(
            run_ids, fact_lookup(AlphaSettings().data_dir), metric or DEFAULT_METRICS
        )
        emit(result, json_out=json_out, fallback=render_compare(result))
    except (ValueError, OSError, DataError) as exc:
        _error(exc, json_out)
