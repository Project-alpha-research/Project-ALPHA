"""Time estimate and progress for `alpha ml run`.

The worker prints nothing while it trains and writes its files only at the end, so no fold in
progress is named. The seconds per fold and asset are measured on each finished run and kept in
the data folder; a first run has no estimate.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import typer

from alpha_cli import _progress

PROGRESS_EVERY = _progress.EVERY_SECONDS


def _path(data_dir: Path) -> Path:
    return data_dir / "ml_timing.json"


def seconds_per_fold(data_dir: Path, assets: int) -> float | None:
    """Seconds one fold takes for this many assets, as measured on the last run on this computer.

    None when no run was timed here: no number is made up."""
    try:
        stored = json.loads(_path(data_dir).read_text(encoding="utf-8"))["seconds_per_asset_fold"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if isinstance(stored, int | float) and not isinstance(stored, bool) and stored > 0:
        return float(stored) * assets
    return None


def record(data_dir: Path, assets: int, folds: int, seconds: float) -> None:
    """Keep the measured rate for the next estimate."""
    rate = seconds / (assets * folds)
    _path(data_dir).write_text(json.dumps({"seconds_per_asset_fold": rate}), encoding="utf-8")


def expected_sentence(expected: float | None, folds: int) -> str:
    if expected is None:
        return (
            f"The model trains {folds} times. No time estimate yet: this computer has not timed "
            "a model run. This run is timed, and the next run gets an estimate. "
            "A line follows about every 10 seconds."
        )
    minutes = max(1, math.ceil(expected / 60))
    unit = "minute" if minutes == 1 else "minutes"
    return (
        f"The model trains {folds} times. Expected time: about {minutes} {unit} "
        "(from the last model run on this computer). A line follows about every 10 seconds."
    )


def training_phrase(folds: int) -> str:
    """What the progress line says: the fold count. The worker reports no fold until it ends,
    and writes no per-fold file the command could count, so no fold in progress is named."""
    return f"fold count {folds}; this stage reports when it ends"


def announce(data_dir: Path, assets: int, folds: int) -> tuple[float | None, float | None]:
    """Print the expected time first; return (expected, seconds per fold); None if unknown."""
    each = seconds_per_fold(data_dir, assets)
    expected = None if each is None else each * folds
    typer.echo(expected_sentence(expected, folds), err=True)
    return expected, each
