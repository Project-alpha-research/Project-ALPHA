"""How a stored setup study or trade reads: its evidence word and its place in the setup's family.

Read from the stored ``summary.json`` and the ledger rows the Setup Lab already reads. A new
record carries ``evidence`` beside the old ``outcome``; an old record carries only ``outcome``,
which maps to the word it was derived from. The place in the family is a count of ledger rows. No
statistic is computed here: the family-adjusted random-date figure is the command line's alone.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from alpha_web.api.models.setup_runs import SetupReading

# The three words a setup record reads with, and how its old outcome word maps. The command line
# owns both (``alpha_cli.spine.reading``); ``tests/unit/test_web_setup_reading.py`` fails on drift.
EVIDENCE_WORDS = ("too little to read", "not clear of chance", "some evidence")
OLD_OUTCOMES = {
    "inconclusive": "too little to read",
    "not supported": "not clear of chance",
    "supported (exploratory, not confirmed)": "some evidence",
}


def _idea_key(idea: Any) -> str | None:
    return " ".join(idea.casefold().split()) if isinstance(idea, str) and idea.strip() else None


def _evidence(summary: Mapping[str, Any]) -> tuple[str | None, bool]:
    word = summary.get("evidence")
    if isinstance(word, str) and word in EVIDENCE_WORDS:
        return word, False
    old = summary.get("outcome")
    return (OLD_OUTCOMES.get(old), True) if isinstance(old, str) else (None, False)


def _place(
    ledger: list[dict[str, Any]] | None, kind: str, run_id: str, idea: Any
) -> tuple[int | None, int | None]:
    """This run's place among the ledger rows of its kind on the same idea text, and their count."""
    key = _idea_key(idea)
    if ledger is None or key is None:
        return None, None
    rows = [
        row
        for row in ledger
        if row.get("kind") == f"setup_{kind}"
        and _idea_key(row.get("idea")) == key
        and "repeat" not in (row.get("labels") or [])
    ]
    ids = [row.get(f"{kind}_id") for row in rows]
    return (ids.index(run_id) + 1 if run_id in ids else None), len(rows)


def reading_of(
    summary: Mapping[str, Any] | None,
    ledger: list[dict[str, Any]] | None,
    kind: str,
    run_id: str,
) -> SetupReading | None:
    """The reading of one stored setup outcome; ``None`` when no summary was stored."""
    if summary is None:
        return None
    word, old = _evidence(summary)
    position, count = _place(ledger, kind, run_id, summary.get("idea"))
    return SetupReading(
        evidence=word, old_wording=old, family_position=position, family_count=count
    )
