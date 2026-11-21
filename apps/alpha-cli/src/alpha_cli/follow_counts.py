"""The count `alpha next` prints about follows. Light on purpose: no engine is imported.

`next_cmds.py` calls only this module, so it names no follow store module and opens nothing under
`forward/`. This module is on the guard's reader list; the counts come from `follow_today`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpha_cli import follow_today
from alpha_cli.follow_journal import JournalRefusal
from alpha_cli.spine.errors import SpineError


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


CLOCK = utc_now  # tests replace this


def followed_counts(home: Path) -> dict[str, Any] | None:
    """Counts of active follows by group, or None when nothing is followed."""
    try:
        facts = follow_today.build(home, CLOCK())
    except (SpineError, JournalRefusal):
        return {"active": None}  # a count and nothing else: no journal text passes this door
    if not facts["followed"]:
        return None
    by = {g["key"]: g["count"] for g in facts["groups"]}
    return {
        "active": facts["followed"],
        "new_signal": by["new_signal"],
        "open_position": by["open_position"],
        "late_or_missed": by["late_or_missed"],
    }


def followed_line(counts: dict[str, Any]) -> str:
    if counts.get("active") is None:
        return "Followed on paper: could not be read. See: alpha follow today"
    return (
        f"Followed on paper: {counts['active']} ({counts['new_signal']} new signal, "
        f"{counts['open_position']} open, {counts['late_or_missed']} late or missed). "
        "See: alpha follow today. As one paper account: alpha follow book"
    )
