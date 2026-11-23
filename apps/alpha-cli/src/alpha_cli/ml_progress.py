"""Time estimate and progress for `alpha ml run`.

The worker prints nothing while it trains, so the fold in progress is an estimate from the time
so far. The seconds per fold and asset are measured on each finished run and kept in the data
folder; a first run uses a rough default.
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


def fold_phrase(elapsed: float, per_fold: float, folds: int) -> str:
    """The fold in progress, estimated from the time so far (the worker reports none).

    The count runs to the last fold. Past the estimate the run is in its last fold or in the
    closing stages, and the line says so instead of freezing on one fold."""
    if elapsed >= per_fold * folds:
        return (
            f"past the estimate for {folds} folds: in the last fold, or in the closing stages "
            "(scoring, writing the run)"
        )
    return f"about fold {int(elapsed // per_fold) + 1} of {folds}"


def announce(data_dir: Path, assets: int, folds: int) -> tuple[float | None, float | None]:
    """Print the expected time first; return (expected seconds, seconds per fold), None if unknown."""
    each = seconds_per_fold(data_dir, assets)
    expected = None if each is None else each * folds
    typer.echo(expected_sentence(expected, folds), err=True)
    return expected, each
