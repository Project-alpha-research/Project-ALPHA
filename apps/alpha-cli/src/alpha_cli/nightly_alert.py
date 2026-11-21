"""Tell the owner when a night fails: the `LAST_FAILED` marker and an optional desktop notice.

The marker is `<home>/nightly/LAST_FAILED`, plain text, written atomically. A run with a blocking
defect, or a run that crashes, writes it. A later full-attempt run (no `--only`) with no blocking
defect removes it. The notice calls the local `notify-send` program only when the config says
`notify = true`. A missing program or a failing call is never an error. No network is used.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from alpha_cli.nightly_record import is_partial
from alpha_core.atomic import write_text

MARKER = "LAST_FAILED"
HEAD = "The last nightly run failed: "
NOTIFY_SECONDS = 10.0


def marker_path(home: Path) -> Path:
    return home / "nightly" / MARKER


def notify(summary: str, enabled: bool) -> bool:
    """Show one line on the desktop if asked and possible. Says whether the call worked."""
    program = shutil.which("notify-send") if enabled else None
    if program is None:
        return False
    try:
        done = subprocess.run(
            [program, "ALPHA nightly run", summary],
            capture_output=True,
            timeout=NOTIFY_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _mark(home: Path, day: date, number: int, headline: str, details: list[str]) -> None:
    name = f"{day.isoformat()}-{number}"
    lines = [f"{HEAD}run {name} {headline}", f"Date: {day.isoformat()}", f"Run: {name}", *details]
    try:
        write_text(marker_path(home), "\n".join(lines) + "\n")
    except OSError as error:  # the marker must never hide the run's own result or error
        print(
            f"Warning: the failure marker {marker_path(home)} cannot be written: {error}",
            file=sys.stderr,
        )


def after_run(home: Path, record: dict[str, Any], *, notify_owner: bool) -> None:
    """Write the marker for a run with a blocking defect; a clean full attempt removes it."""
    blocking = [d for d in record["defects"] if d["severity"] == "blocking"]
    if not blocking:
        if not is_partial(tuple(record["scenarios"])):
            try:
                marker_path(home).unlink(missing_ok=True)
            except OSError as error:
                print(f"Warning: the failure marker cannot be removed: {error}", file=sys.stderr)
        return
    count = len(blocking)
    headline = f"has {count} blocking defect{'' if count == 1 else 's'}."
    details = [f"{d['step']}: {' '.join(str(d['text']).split())}" for d in blocking]
    day = date.fromisoformat(record["date"])
    _mark(home, day, record["run_number"], headline, details)
    notify(f"{HEAD}run {record['date']}-{record['run_number']} {headline}", notify_owner)


def after_crash(
    home: Path, day: date, number: int, error: BaseException, *, notify_owner: bool
) -> None:
    """The run itself stopped: no record may exist, so the marker must say what happened."""
    headline = "stopped before it finished."
    words = " ".join(str(error).split()) or "no message"
    _mark(home, day, number, headline, [f"The run stopped with {type(error).__name__}: {words}"])
    notify(f"{HEAD}run {day.isoformat()}-{number} {headline}", notify_owner)


def failed_line(home: Path) -> str | None:
    """One plain line when the marker exists; None when the last full run was clean."""
    path = marker_path(home)
    try:
        first = path.read_text(encoding="utf-8").splitlines()[:1]
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        return f"{HEAD}the marker file {path} cannot be read ({error})."
    head = first[0] if first and first[0].startswith(HEAD) else f"{HEAD}the marker has no summary."
    return f"{head} Details: {path}"
