"""Find and inspect daily setups before looking at their outcomes."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from alpha_cli._cli_json import emit
from alpha_cli.spine.contact_sheet import draw_sheet
from alpha_cli.spine.errors import SpineError, fail, setup_error
from alpha_cli.spine.ledger import append_trial
from alpha_core import DataError
from alpha_core.atomic import write_text
from alpha_core.config import AlphaSettings

setup_app = typer.Typer(help="Find every match of a chart setup.", no_args_is_help=True)


@setup_app.callback()
def setup_group() -> None:
    """Inspect setup matches before viewing outcomes."""


def _text(output: dict[str, Any]) -> str:
    lines = []
    for asset in output["assets"]:
        if asset["error"]:
            lines.append(f"{asset['asset']}: {asset['error']['code']}: {asset['error']['message']}")
        else:
            reasons = ", ".join(f"{k} {v}" for k, v in asset["rejected_by_reason"].items())
            lines.append(
                f"{asset['asset']}: {asset['accepted_clusters']} separate occurrences "
                f"({asset['accepted']} matching days); {asset['pending']} pending; "
                f"rejected: {reasons or 'none'}"
            )
    if "repeat" in output["labels"]:
        lines.append(
            "Repeat of an earlier find on the same spec and data: nothing was redrawn "
            f"(its sheets show {output['context_bars']} bars before each event)."
        )
    return "\n".join(
        [
            *lines,
            output["folder"],
            "Outcomes were not looked at. Next: open the sheets; "
            "outcomes come with alpha setup study (not built yet).",
        ]
    )


@setup_app.command("find")
def find_command(
    spec: Path,
    asset: Annotated[list[str] | None, typer.Option("--asset", help="Keep a spec asset.")] = None,
    context_bars: int = typer.Option(30, min=5, max=250, help="Bars before the event."),
    max_sheets: int = typer.Option(10, min=1, max=50, help="Maximum accepted sheets."),
    json_out: bool = typer.Option(False, "--json", help="Emit one JSON result object."),
) -> None:
    """Record every match and draw contact sheets ending at the entry open."""
    from alpha_cli.spine.stores import _stores

    home = AlphaSettings().data_dir
    try:
        with redirect_stdout(sys.stderr if json_out else sys.stdout):
            output = run_find(
                spec, home=home, assets=asset, context_bars=context_bars, max_sheets=max_sheets
            )
    except (DataError, ValueError, OSError) as exc:
        fail(setup_error(exc, list(_stores(home))), json_out)
    emit(output, json_out=json_out, fallback=_text(output))


BASIS = (
    "setup evaluator: decided at each bar's close using bars up to it; entry is the next "
    "bar's open; no outcome after entry was computed"
)
FOOTER = (
    "Bars up to the entry open only. What happened after entry is not shown: "
    "that is a separate, counted step."
)


def _sheets(
    spec: Any,
    frames: dict[str, Any],
    rows: list[dict[str, Any]],
    folder: Path,
    context_bars: int,
    max_sheets: int,
) -> tuple[list[str], dict[str, Any]]:
    from alpha_cli.spine.setup_find import sheet_panels
    from alpha_research.figures.theme import load_theme

    batches, counts = sheet_panels(spec, frames, rows, context_bars, max_sheets)
    # Only an unfinished find (no manifest) reaches here: drop sheets an interrupted attempt left.
    for stale in sorted((folder / "sheets").glob("*.png")):
        stale.unlink()
    paths = []
    for index, (title, panels) in enumerate(batches, 1):
        mode = panels[0].mode
        path = folder / "sheets" / f"{mode}-{index if mode == 'accepted' else 1:03d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(draw_sheet(panels, title=title, footer=FOOTER, theme=load_theme()))
        paths.append(str(path.relative_to(folder)))
    return paths, counts


def run_find(
    path: Path,
    *,
    home: Path,
    assets: list[str] | None = None,
    context_bars: int = 30,
    max_sheets: int = 10,
) -> dict[str, Any]:
    """A find counts one exploratory look; completed folders are never rewritten."""
    import polars as pl

    from alpha_cli.spine.setup_find import _counts, load_spec, prepare_assets

    if not 5 <= context_bars <= 250 or not 1 <= max_sheets <= 50:
        raise ValueError("context-bars must be 5–250 and max-sheets 1–50")
    spec = load_spec(path, assets)
    results, candidates, frames = prepare_assets(spec, home, assets)
    for result, rows in zip((r for r in results if r["error"] is None), candidates, strict=True):
        result.update(_counts(rows))
    if not candidates:
        raise SpineError(
            "FIND_FAILED",
            json.dumps(results),
            "Correct the asset errors and run alpha setup find again.",
        )
    keys = sorted(f"{r['asset']}={r['source_fingerprint']}" for r in results if r["error"] is None)
    find_id = hashlib.sha256((spec.spec_sha256 + "|" + "|".join(keys)).encode()).hexdigest()[:16]
    identity = dict(find_id=find_id, spec_sha256=spec.spec_sha256, name=spec.setup.name)
    folder = home / "setups" / find_id
    labels = ["exploratory", "outcomes-not-viewed", "dev-machine-data", "daily-only"]
    labels += sorted({label for r in results for label in r["labels"]})
    if (folder / "manifest.json").exists():
        summary = json.loads((folder / "summary.json").read_text())
        manifest = json.loads((folder / "manifest.json").read_text())
        labels = [*summary["labels"], "repeat"]
        sheets = manifest["files"]["sheets"]
        context_bars = manifest["context_bars"]
    else:
        combined = pl.concat(candidates)
        totals = {
            k: sum(r.get(k, 0) for r in results)
            for k in ("events", "accepted", "pending", "rejected", "clusters", "accepted_clusters")
        }
        totals["rejected_by_reason"] = dict(
            sum((Counter(r.get("rejected_by_reason", {})) for r in results), Counter())
        )
        if totals["pending"]:
            labels.append("pending-at-end")
        sheets, sheet_counts = _sheets(
            spec, frames, combined.to_dicts(), folder, context_bars, max_sheets
        )
        if sheet_counts["accepted_not_drawn"]:
            labels.append("sheets-truncated")
        facts = [
            dict(
                metric=f"setup_{k}",
                value=totals[k],
                run_id=find_id,
                basis=BASIS,
                source=f"summary.json:totals.{k}",
                labels=labels,
                reason=None,
            )
            for k in ("events", "accepted", "pending", "rejected", "clusters", "accepted_clusters")
        ]
        summary = dict(
            **identity,
            labels=labels,
            basis=BASIS,
            totals=totals,
            assets=results,
            sheets=sheet_counts,
            facts=facts,
        )
        folder.mkdir(parents=True, exist_ok=True)
        write_text(
            folder / "spec.json",
            json.dumps({**spec.model_dump(mode="json"), "spec_sha256": spec.spec_sha256}),
        )
        combined.write_parquet(folder / "candidates.parquet")
        write_text(folder / "summary.json", json.dumps(summary, default=str, allow_nan=False))
        manifest = dict(
            schema="AlphaSetupFindV1",
            **identity,
            idea=spec.setup.idea,
            recorded_at=datetime.now(UTC).isoformat(),
            context_bars=context_bars,
            labels=labels,
            assets=results,
            files=dict(candidates="candidates.parquet", summary="summary.json", sheets=sheets),
        )
        write_text(folder / "manifest.json", json.dumps(manifest, default=str, allow_nan=False))
    ledger = append_trial(
        home,
        dict(
            kind="setup_find",
            run_id=None,
            **identity,
            idea=spec.setup.idea,
            assets=[r["asset"] for r in results],
            labels=labels,
            verdict=None,
            **{
                k: summary["totals"][k]
                for k in ("accepted", "pending", "rejected", "accepted_clusters")
            },
        ),
    )
    return dict(
        find_id=find_id,
        folder=str(folder),
        labels=labels,
        context_bars=context_bars,
        trials_total=ledger["total_trials"],
        totals=summary["totals"],
        assets=json.loads(json.dumps(results, default=str)),
        sheets=[str((folder / s).relative_to(home)) for s in sheets],
        facts=[{**f, "labels": labels} for f in summary["facts"]],
    )
