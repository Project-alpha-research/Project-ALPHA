"""Read, verify and append a follow journal, and keep its stored head. Paper only.

`journal.jsonl` is append-only and hash-chained (rules in `follow_journal`). After each append
the writer replaces `head.json` atomically under the same lock. A journal shorter than its
stored head, or whose entry at the head number has another hash, was cut or replaced. Both
files rewritten together is not detected: there is no outside anchor yet.
"""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any, NamedTuple

from alpha_cli.follow_journal import (
    CHAIN_BROKEN,
    GENESIS,
    NO_START,
    PARTIAL_LINE,
    REPAIR,
    SEQ_GAP,
    TRUNCATED,
    WRITTEN_AHEAD,
    WRONG_FOLDER,
    Break,
    Clock,
    Entry,
    JournalRefusal,
    JournalReport,
    Kind,
    build_entry,
    check_rules,
    entry_hash_of,
)

JOURNAL_FILE = "journal.jsonl"
HEAD_FILE = "head.json"


class Head(NamedTuple):
    entries: int
    head: str


def write_head(folder: Path, head: Head) -> None:
    staged = folder / f"{HEAD_FILE}.{os.getpid()}.part"
    with staged.open("w", encoding="utf-8") as stream:
        json.dump(head._asdict(), stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(staged, folder / HEAD_FILE)


def read_head(folder: Path) -> Head | None:
    """The stored head, or None when there is none. An unreadable head is a ValueError."""
    try:
        raw = json.loads((folder / HEAD_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), int):
        raise ValueError("the stored head cannot be read")
    return Head(int(raw["entries"]), str(raw.get("head", "")))


def _lines(folder: Path) -> tuple[list[str], bool]:
    """The complete lines, and whether a last line was cut off before its newline."""
    try:
        text = (folder / JOURNAL_FILE).read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], False
    partial = bool(text) and not text.endswith("\n")
    lines = [line for line in text.split("\n") if line]
    return (lines[:-1] if partial else lines), partial


def _read_line(position: int, line: str, entries: list[Entry]) -> Entry | Break:
    try:
        entry = Entry.model_validate(json.loads(line))
    except (ValueError, TypeError) as exc:
        return Break(
            position, CHAIN_BROKEN, f"Line {position} cannot be read ({type(exc).__name__})."
        )
    if entry.seq != position:
        reason = f"Entry {position} is numbered {entry.seq}: a line was moved or removed."
        return Break(position, SEQ_GAP, reason)
    if entry_hash_of(entry.model_dump(mode="json")) != entry.entry_hash:
        return Break(position, CHAIN_BROKEN, f"Entry {position} no longer matches its own hash.")
    try:
        check_rules(entries[-1] if entries else None, entry)
    except JournalRefusal as exc:
        return Break(position, str(exc.payload["code"]), str(exc))
    return entry


def _end_checks(folder: Path, entries: list[Entry], partial: bool) -> Break | None:
    count = len(entries)
    if partial:
        reason = f"Line {count + 1} was not written to its end. A write stopped part way."
        return Break(count + 1, PARTIAL_LINE, reason)
    try:
        stored = read_head(folder) or Head(0, GENESIS)
    except ValueError:
        return Break(count, CHAIN_BROKEN, "The stored head (head.json) cannot be read.")
    if stored.entries > count:
        reason = f"The stored head names {stored.entries} entries, the journal has {count}."
        return Break(count + 1, TRUNCATED, f"{reason} Entries were removed from the end.")
    if count - stored.entries > 1:
        reason = f"The stored head names {stored.entries} entries, the journal has {count}."
        return Break(stored.entries + 1, TRUNCATED, f"{reason} The head is not the writer's.")
    if stored.entries and entries[stored.entries - 1].entry_hash != stored.head:
        reason = f"Entry {stored.entries} differs from the stored head. The journal was replaced."
        return Break(stored.entries, CHAIN_BROKEN, reason)
    return None


def _walk(
    folder: Path, follow_id: str | None = None, now: datetime | None = None, empty: bool = False
) -> tuple[list[Entry], Break | None]:
    lines, partial = _lines(folder)
    entries: list[Entry] = []
    for position, line in enumerate(lines, start=1):
        read = _read_line(position, line, entries)
        if isinstance(read, Break):
            return entries, read
        if now is not None and read.written_at > now:
            return entries, Break(
                position, WRITTEN_AHEAD, f"Entry {position} is dated later than now."
            )
        if position == 1 and follow_id and read.payload.get("follow_id") != follow_id:
            reason = f"The start entry belongs to another follow, not {follow_id}."
            return entries, Break(1, WRONG_FOLDER, reason)
        entries.append(read)
    if follow_id and not entries and not partial and not empty:
        return entries, Break(1, NO_START, "The follow has no start entry.")
    return entries, _end_checks(folder, entries, partial)


def verify_journal(
    folder: Path, *, follow_id: str | None = None, now: datetime | None = None
) -> JournalReport:
    """Recompute the whole chain and compare it with the stored head. The first break is named."""
    entries, found = _walk(folder, follow_id, now)
    return JournalReport(len(entries), entries[-1].entry_hash if entries else GENESIS, found)


def read_entries(folder: Path, follow_id: str | None = None, empty: bool = False) -> list[Entry]:
    """The entries, or a refusal at the first break. `empty` allows a journal not begun yet."""
    entries, found = _walk(folder, follow_id, empty=empty)
    if found is not None:
        raise JournalRefusal(
            found.code,
            f"The journal is broken at entry {found.seq}: {found.reason}",
            REPAIR
            if found.code == PARTIAL_LINE
            else "Do not edit the journal. Run `alpha follow verify`.",
        )
    return entries


def append_entry(
    folder: Path,
    *,
    kind: Kind,
    session_date: date,
    clock: Clock,
    bar_hashes: Mapping[str, str] | None = None,
    payload: Mapping[str, Any] | None = None,
    follow_id: str | None = None,
) -> Entry:
    """Append one entry under a lock, then store the new head. `written_at` is the clock's."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / JOURNAL_FILE).open("ab") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        entries = read_entries(folder, follow_id, empty=True)
        entry = build_entry(
            entries[-1] if entries else None,
            kind=kind,
            session_date=session_date,
            written_at=clock(),
            bar_hashes=bar_hashes,
            payload=payload,
        )
        line = json.dumps(entry.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        stream.write(line.encode("utf-8") + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
        write_head(folder, Head(entry.seq, entry.entry_hash))
    return entry
