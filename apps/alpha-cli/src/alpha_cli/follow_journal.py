"""The follow journal: one append-only, hash-chained file per followed idea. Paper only.

Each line is one entry. An entry names the hash of the one before it, so a changed, removed or
reordered line shows at the first place it differs. The writer refuses back-fill: a session date
that is not after the last one, a clock that runs backwards, a gap in the numbers, a second
start, and any write after a stop. A day not recorded in time can only be written as `missed`.
The clock is always passed in; nothing here sleeps or reads the wall clock.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alpha_cli.spine.errors import SpineError

JOURNAL_FILE = "journal.jsonl"
GENESIS = "0" * 64
# A bar for session day D may be written on D or on the next calendar day. Later, it is `missed`.
MAX_BAR_LATENESS_DAYS = 1
type Kind = Literal["start", "bar", "missed", "late", "stop"]
type Clock = Callable[[], datetime]

SESSION_NOT_AFTER = "FOLLOW_SESSION_NOT_AFTER"
CLOCK_BACK = "FOLLOW_CLOCK_BACK"
SEQ_GAP = "FOLLOW_SEQ_GAP"
CHAIN_BROKEN = "FOLLOW_CHAIN_BROKEN"
STOPPED = "FOLLOW_STOPPED"
SECOND_START = "FOLLOW_SECOND_START"
NO_START = "FOLLOW_NO_START"
BAR_TOO_LATE = "FOLLOW_BAR_TOO_LATE"


class JournalRefusal(SpineError):
    """A write or a chain check that the journal refuses. The code is stable."""

    def __init__(self, code: str, message: str, next_step: str) -> None:
        super().__init__(code, message, next_step)


class Entry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    seq: int = Field(ge=1)
    session_date: date
    written_at: datetime
    kind: Kind
    bar_hashes: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str = Field(pattern="^[0-9a-f]{64}$")
    entry_hash: str = Field(pattern="^[0-9a-f]{64}$")

    @field_validator("written_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("written_at must be an aware UTC time")
        return value.astimezone(UTC)

    @field_validator("bar_hashes")
    @classmethod
    def _hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if any(len(h) != 64 or set(h) - set("0123456789abcdef") for h in value.values()):
            raise ValueError("a bar hash must be 64 lowercase hex characters")
        return value


class Break(NamedTuple):
    seq: int
    code: str
    reason: str


class JournalReport(NamedTuple):
    entries: int
    head: str
    first_break: Break | None


def entry_hash_of(fields: Mapping[str, Any]) -> str:
    body = {k: v for k, v in fields.items() if k != "entry_hash"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _seal(fields: dict[str, Any]) -> Entry:
    return Entry.model_validate({**fields, "entry_hash": entry_hash_of(fields)})


def build_entry(
    prev: Entry | None,
    *,
    kind: Kind,
    session_date: date,
    written_at: datetime,
    bar_hashes: Mapping[str, str] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> Entry:
    """Build the next entry after `prev` and apply every refusal. A `bar` older than the allowed
    lateness is refused here, so such a day can only be written as `missed`."""
    probe = Entry(
        seq=1 if prev is None else prev.seq + 1,
        session_date=session_date,
        written_at=written_at,
        kind=kind,
        bar_hashes=dict(bar_hashes or {}),
        payload=dict(payload or {}),
        prev_hash=GENESIS if prev is None else prev.entry_hash,
        entry_hash=GENESIS,
    )
    fields = probe.model_dump(mode="json")
    entry = _seal(fields)
    check_rules(prev, entry)
    return entry


def _refuse(code: str, message: str, next_step: str) -> JournalRefusal:
    return JournalRefusal(code, message, next_step)


def check_rules(prev: Entry | None, entry: Entry) -> None:
    """Raise `JournalRefusal` unless `entry` may follow `prev`."""
    if prev is None:
        if entry.kind != "start":
            raise _refuse(
                NO_START, "The journal must begin with a start entry.", "Start the follow."
            )
        if entry.seq != 1 or entry.prev_hash != GENESIS:
            raise _refuse(
                CHAIN_BROKEN, "The first entry must be number 1.", "Do not edit the file."
            )
        return
    if entry.kind == "start":
        raise _refuse(
            SECOND_START,
            "This follow already has a start entry. A second start is refused.",
            "To follow a changed spec, run `alpha follow start`. It makes a new version.",
        )
    if prev.kind == "stop":
        raise _refuse(
            STOPPED,
            "This follow is stopped. Nothing can be written after a stop.",
            "Start a new follow with `alpha follow start`.",
        )
    if entry.seq != prev.seq + 1:
        raise _refuse(
            SEQ_GAP,
            f"Entry number {entry.seq} follows number {prev.seq}. A number is missing or moved.",
            "Do not edit the journal. Run `alpha follow verify`.",
        )
    if entry.prev_hash != prev.entry_hash:
        raise _refuse(
            CHAIN_BROKEN,
            f"Entry {entry.seq} does not link to entry {prev.seq}.",
            "Do not edit the journal. Run `alpha follow verify`.",
        )
    _check_not_after(prev, entry)


def _check_not_after(prev: Entry, entry: Entry) -> None:
    not_after = entry.session_date < prev.session_date or (
        entry.session_date == prev.session_date and entry.kind != "stop"
    )
    if not_after:
        raise _refuse(
            SESSION_NOT_AFTER,
            f"Session {entry.session_date} is not after the last session {prev.session_date}. "
            "There are no inserts and no back-fill.",
            "A day that was skipped stays skipped.",
        )
    if entry.written_at < prev.written_at:
        raise _refuse(
            CLOCK_BACK,
            f"Entry {entry.seq} is written earlier than entry {prev.seq}.",
            "The clock must not run backwards.",
        )
    if entry.kind == "bar":
        late = (entry.written_at.date() - entry.session_date).days
        if late > MAX_BAR_LATENESS_DAYS:
            raise _refuse(
                BAR_TOO_LATE,
                f"The session of {entry.session_date} was not recorded in time. "
                f"A bar must be written within {MAX_BAR_LATENESS_DAYS} day of its session.",
                "Write that day as `missed`. It cannot be written as a bar.",
            )


def _lines(folder: Path) -> list[str]:
    try:
        text = (folder / JOURNAL_FILE).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return [line for line in text.split("\n") if line]


def _walk(folder: Path) -> tuple[list[Entry], Break | None]:
    entries: list[Entry] = []
    for position, line in enumerate(_lines(folder), start=1):
        try:
            raw = json.loads(line)
            entry = Entry.model_validate(raw)
        except (ValueError, TypeError) as exc:
            reason = f"Line {position} cannot be read ({type(exc).__name__})."
            return entries, Break(position, CHAIN_BROKEN, reason)
        recomputed = entry_hash_of(entry.model_dump(mode="json"))
        if entry.seq != position:
            return entries, Break(
                position,
                SEQ_GAP,
                f"Entry {position} is numbered {entry.seq}: a line was moved or removed.",
            )
        if recomputed != entry.entry_hash:
            return entries, Break(
                position, CHAIN_BROKEN, f"Entry {position} no longer matches its own hash."
            )
        try:
            check_rules(entries[-1] if entries else None, entry)
        except JournalRefusal as exc:
            return entries, Break(position, str(exc.payload["code"]), str(exc))
        entries.append(entry)
    return entries, None


def verify_journal(folder: Path) -> JournalReport:
    """Recompute the whole chain. The first break is named by its entry number."""
    entries, found = _walk(folder)
    return JournalReport(len(entries), entries[-1].entry_hash if entries else GENESIS, found)


def read_entries(folder: Path) -> list[Entry]:
    """The entries, or a refusal at the first break."""
    entries, found = _walk(folder)
    if found is not None:
        raise _refuse(
            found.code,
            f"The journal is broken at entry {found.seq}: {found.reason}",
            "Do not edit the journal. Run `alpha follow verify`.",
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
) -> Entry:
    """Append one entry under a lock. `written_at` comes from the injected clock."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / JOURNAL_FILE
    with path.open("ab") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        entries = read_entries(folder)
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
    return entry
