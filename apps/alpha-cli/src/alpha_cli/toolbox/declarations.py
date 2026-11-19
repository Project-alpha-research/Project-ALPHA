"""Checks chosen before a result was seen. A record, never a gate: nothing here refuses a run."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox.registry import get
from alpha_cli.toolbox.sets import SETS

DECLARED, EXPLORATORY = "declared", "exploratory"
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _file(home: Path, run_id: str) -> Path:
    return home / "ledger" / "declarations" / f"{run_id}.jsonl"


def read(home: Path, run_id: str) -> list[dict[str, Any]]:
    """Every declaration for the run, in the order written."""
    path = _file(home, run_id)
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def declare(
    home: Path,
    run_id: str,
    *,
    set_name: str | None = None,
    tools: Iterable[str] = (),
    why: str = "",
    now: Clock = utc_now,
) -> dict[str, Any]:
    """Append one declaration with the time it was made. Unknown names are an error."""
    names = list(tools)
    if (set_name is None) == (not names):
        raise SpineError(
            "BAD_DECLARATION",
            "Name a set or a list of tools, not both and not neither.",
            "Use --set <name> or --tools a,b,c.",
        )
    if set_name is not None:
        if set_name not in SETS:
            raise SpineError(
                "UNKNOWN_SET", f"Unknown set {set_name!r}.", "Choose a known set.", list(SETS)
            )
        names = list(SETS[set_name])
    for tool_id in names:
        get(tool_id)
    row = {
        "run_id": run_id,
        "set": set_name,
        "tools": names,
        "why": why,
        "declared_at": now().isoformat(),
    }
    path = _file(home, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(json.dumps(row, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return row


def status(
    home: Path, run_id: str, tool_id: str, set_name: str | None, written_at: datetime
) -> str:
    """`declared` if a declaration naming the tool (or its set) was made before the write."""
    for row in read(home, run_id):
        names = tool_id in row["tools"] or (set_name is not None and row["set"] == set_name)
        if names and datetime.fromisoformat(row["declared_at"]) < written_at:
            return DECLARED
    return EXPLORATORY


def word_of(labels: Iterable[str]) -> str:
    """The declared/exploratory word of a stored result; results older than this are exploratory."""
    return DECLARED if DECLARED in labels else EXPLORATORY


def counts(labels_of_results: Iterable[Iterable[str]]) -> dict[str, Any]:
    words = [word_of(list(labels)) for labels in labels_of_results]
    declared = words.count(DECLARED)
    total, exploratory = len(words), len(words) - declared
    noun = "check" if total == 1 else "checks"
    text = f"{total} {noun} run on this result: {declared} declared, {exploratory} exploratory"
    return {"total": total, "declared": declared, "exploratory": exploratory, "text": text}
