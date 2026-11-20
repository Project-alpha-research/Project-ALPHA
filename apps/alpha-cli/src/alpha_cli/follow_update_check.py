"""The replay check of a follow update: the journal against the rule replayed on stored bars.

The journal is never rewritten. This only says where the two differ: a decision, a fill, the
engine code, or the stored bars (their hash differs, so the data changed since the entry). A
`missed` entry is compared on its bars only: it holds no order. Paper only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import date
from typing import Any

from alpha_cli.follow_journal import Entry
from alpha_cli.follow_replay import Replay
from alpha_core import Bar

type Digests = list[str]
TOLERANCE = 1e-9


def digests_of(bars: Sequence[Bar]) -> Digests:
    """`digests[i]` hashes the canonical bytes of the bars up to and including bar i."""
    running = hashlib.sha256()
    out: Digests = []
    for b in bars:
        running.update(
            f"{b.ts.isoformat()}|{b.open!r}|{b.high!r}|{b.low!r}|{b.close!r}|{b.volume!r}\n".encode()
        )
        out.append(running.copy().hexdigest())
    return out


def _decision_differs(entry: Entry, replay: Replay, session: date) -> bool:
    seen = replay.sessions.get(session)
    recorded = entry.payload.get("decision", {})
    if seen is None:
        return bool(recorded.get("long"))
    readings = entry.payload.get("readings", {})
    same = readings.keys() == seen.readings.keys() and all(
        abs(readings[k] - v) <= TOLERANCE for k, v in seen.readings.items()
    )
    return recorded.get("long") != seen.long or not same


def _fill_differs(entry: Entry, replay: Replay) -> bool:
    for fill in entry.payload.get("fills", []):
        hit = replay.fills.get(date.fromisoformat(str(fill["bar_ts"])[:10]))
        if hit is None or abs(hit.price - fill["price"]) > TOLERANCE:
            return True
    return False


def check_replay(
    *,
    asset: str,
    dates: list[date],
    digests: Digests,
    replay: Replay | None,
    engine_sha: str,
    entries: list[Entry],
) -> dict[str, Any]:
    """`agrees` is true only if no decision, fill, engine hash or stored bar differs."""
    found: list[dict[str, str]] = []
    changed: list[date] = []
    checked = 0
    engines = [
        e.session_date
        for e in entries
        if e.payload.get("engine_code_sha256", engine_sha) != engine_sha
    ]
    for entry in entries:
        recorded = entry.bar_hashes.get(asset)
        if recorded is None or entry.kind not in {"bar", "missed"}:
            continue
        session = entry.session_date
        at = dates.index(session) if session in dates else None
        if at is None or digests[at] != recorded:
            changed.append(session)
        if entry.kind != "bar" or replay is None:
            continue
        checked += 1
        if _decision_differs(entry, replay, session):
            found.append(
                {
                    "session": session.isoformat(),
                    "what": "decision",
                    "detail": "the replay decides differently",
                }
            )
        if _fill_differs(entry, replay):
            found.append(
                {
                    "session": session.isoformat(),
                    "what": "fill",
                    "detail": "the replayed fill differs",
                }
            )
    if changed:
        detail = f"stored bars changed (hash differs): {len(changed)} session(s) from here"
        found.append({"session": changed[0].isoformat(), "what": "bars", "detail": detail})
    if engines:
        detail = f"engine code changed since the entry: {len(engines)} session(s) from here"
        found.append({"session": engines[0].isoformat(), "what": "engine", "detail": detail})
    found.sort(key=lambda d: (d["session"], d["what"]))
    return {
        "agrees": not found,
        "checked": checked,
        "differences": found,
        "bars_changed_from": changed[0].isoformat() if changed else None,
    }
