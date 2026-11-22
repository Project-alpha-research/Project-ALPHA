"""Composing immutable run artifacts into rendered figures.

``alpha_research.figures`` owns the contract and the drawing; this package owns the part
that needs to know about runs -- which artifacts a run actually has, how to read them, and
what the answer sentence should say. That split is what lets the renderer stay core-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alpha_cli.figures import rule_periods
from alpha_cli.figures._builders import BUILDERS
from alpha_cli.figures._common import BuildContext
from alpha_cli.run_store import find_run_dir, read_manifest, valid_run_id
from alpha_core import DataError
from alpha_research.figures import FigureDefinition, FigureSpec, figures_for_command

__all__ = [
    "FigureAvailability",
    "available_figures",
    "build_figure_spec",
    "resolve_run",
]


@dataclass(frozen=True, slots=True)
class FigureAvailability:
    """Whether a figure can be drawn for one run, and if not, precisely why."""

    definition: FigureDefinition
    available: bool
    unavailable_reason: str | None


def resolve_run(run_id: str, *, data_dir: Path) -> tuple[Path, dict[str, Any]]:
    if not valid_run_id(run_id):
        raise DataError(f"invalid run id {run_id!r}; expected 16 lowercase hex characters")
    rdir = find_run_dir(data_dir, run_id)
    if rdir is None:
        raise DataError(f"unknown completed run {run_id!r}")
    return rdir, read_manifest(rdir)


def _reason(definition: FigureDefinition, rdir: Path, manifest: dict[str, Any]) -> str | None:
    """A specific reason beats a blank slot: the UI shows this text verbatim."""
    if definition.figure_id not in BUILDERS and definition.figure_id not in rule_periods.TRADABLE:
        return "builder_not_implemented"
    version = manifest.get("artifact_contract_version")
    if not isinstance(version, int) or version < 3:
        needs_sidecars = any(
            name.endswith(".parquet") and name != "equity_curve.parquet"
            for name in definition.required_artifacts
        )
        if needs_sidecars:
            return f"legacy_contract_v{version or 1}"
    for name in definition.required_artifacts:
        if name == "manifest.json":
            continue
        path = rdir / name
        if not path.is_file() or path.is_symlink():
            return f"artifact_missing:{name}"
        # A run can emit a well-formed artifact with no rows -- a backtest that never
        # traded writes an empty trades.parquet. That is "nothing to draw", not a fault,
        # and the UI should say so rather than surfacing a render error.
        if path.stat().st_size and _is_empty(path):
            return f"artifact_empty:{name}"
    metadata = manifest.get("metadata")
    nested = metadata if isinstance(metadata, dict) else {}
    snapshot = manifest.get("snapshot_id") or nested.get("snapshot_id")
    # A rule test saves no snapshot: its price chart reads the stored bars, fingerprint-checked.
    if (
        definition.requires_snapshot
        and not snapshot
        and not isinstance(manifest.get("spine"), dict)
    ):
        return "snapshot_unavailable"
    return None


def _is_empty(path: Path) -> bool:
    if path.suffix != ".parquet":
        return False
    import polars as pl

    return (
        pl.read_parquet_schema(path) is not None
        and pl.scan_parquet(path).select(pl.len()).collect().item() == 0
    )


def available_figures(rdir: Path, manifest: dict[str, Any]) -> tuple[FigureAvailability, ...]:
    command = manifest.get("command")
    if not isinstance(command, str):
        return ()
    definitions = figures_for_command(command)
    if manifest.get("spine", {}).get("periods"):
        definitions += tuple(rule_periods.definition(name) for name in rule_periods.TRADABLE)
    return tuple(
        FigureAvailability(
            definition=definition,
            available=(reason := _reason(definition, rdir, manifest)) is None,
            unavailable_reason=reason,
        )
        for definition in definitions
    )


def build_figure_spec(
    figure_id: str, *, run_id: str, rdir: Path, manifest: dict[str, Any], data_dir: Path
) -> FigureSpec:
    context = BuildContext(run_id=run_id, rdir=rdir, manifest=manifest, data_dir=data_dir)
    periods = manifest.get("spine", {}).get("periods") or {}
    if figure_id in (*rule_periods.CHARTS, *rule_periods.TRADABLE):
        period = "tradable" if figure_id in rule_periods.TRADABLE else "scored"
        return rule_periods.build(context, figure_id, periods.get(period))
    builder = BUILDERS.get(figure_id)
    if builder is None:
        raise DataError(f"no builder implemented for figure {figure_id!r}")
    return builder(context)
