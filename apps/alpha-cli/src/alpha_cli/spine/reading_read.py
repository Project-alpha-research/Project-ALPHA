"""Find the stored reading of a recorded rule test, for the commands that list runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alpha_cli.run_store import find_run_dir, read_manifest
from alpha_cli.spine.facts import read_json
from alpha_cli.spine.reading import old_grade_text, reading_word, stored_reading
from alpha_core import DataError


def run_reading(home: Path, run_id: Any) -> dict[str, Any] | None:
    """The reading of one stored run, or None when the run folder is missing or unreadable."""
    rdir = find_run_dir(home, str(run_id)) if run_id else None
    if rdir is None:
        return None
    try:
        manifest = read_manifest(rdir)
        return stored_reading(manifest, read_json(rdir / "diagnostics.json"))
    except (ValueError, OSError, DataError):
        return None


def owner_word(home: Path, run_id: Any, letter: Any) -> str:
    """Evidence word for a run; "graded X under the old rules" when only a letter is known."""
    found = run_reading(home, run_id)
    return reading_word(found) if found else old_grade_text(str(letter) if letter else None)
