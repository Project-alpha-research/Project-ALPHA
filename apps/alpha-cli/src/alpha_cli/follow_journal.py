"""The follow journal: one append-only, hash-chained file per followed idea. Paper only.

Each line is one entry. An entry names the hash of the one before it, so a changed, removed or
reordered line shows at the first place it differs. The writer refuses back-fill: a session date
that is not after the last one, a clock that runs backwards, a gap in the numbers, a second
start, and any write after a stop. A day not recorded in time can only be written as `missed`.
The clock is always passed in; nothing here sleeps or reads the wall clock. Reading, verifying
and appending are in `follow_chain`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alpha_cli.spine.errors import SpineError
from alpha_core import DataError
from alpha_data.sessions import session_bounds, sessions_between

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
SESSION_AHEAD = "FOLLOW_SESSION_AHEAD"
WRITTEN_AHEAD = "FOLLOW_WRITTEN_AHEAD"
PARTIAL_LINE = "FOLLOW_PARTIAL_LINE"
TRUNCATED = "FOLLOW_TRUNCATED"
WRONG_FOLDER = "FOLLOW_WRONG_FOLDER"
BAR_BEFORE_CLOSE = "FOLLOW_BAR_BEFORE_CLOSE"
DEADLINE_FORGED = "FOLLOW_DEADLINE_NOT_FROM_CALENDAR"
# The start entry names the market calendar ("" = trades every day). Only it sets the deadlines.
CALENDAR_KEY = "market_calendar"
REPAIR = "Keep a copy of the folder. Then see `docs/reference/invariants/cli-follow.md#repair`."


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
    start: Entry | None = None,
) -> Entry:
    """Build the next entry after `prev` and apply every refusal. A `bar` older than the allowed
    lateness is refused here, so such a day can only be written as `missed`. With a calendar in
    the `start` entry, the writer sets `must_write_by` itself; a caller's value must equal it."""
    payload = dict(payload or {})
    calendar = start.payload.get(CALENDAR_KEY) if start else None
    if kind == "bar" and calendar:
        payload.setdefault("must_write_by", next_open(str(calendar), session_date).isoformat())
    probe = Entry(
        seq=1 if prev is None else prev.seq + 1,
        session_date=session_date,
        written_at=written_at,
        kind=kind,
        bar_hashes=dict(bar_hashes or {}),
        payload=payload,
        prev_hash=GENESIS if prev is None else prev.entry_hash,
        entry_hash=GENESIS,
    )
    fields = probe.model_dump(mode="json")
    entry = _seal(fields)
    check_rules(prev, entry, start=start)
    return entry


def _refuse(code: str, message: str, next_step: str) -> JournalRefusal:
    return JournalRefusal(code, message, next_step)


def check_rules(prev: Entry | None, entry: Entry, *, start: Entry | None = None) -> None:
    """Raise `JournalRefusal` unless `entry` may follow `prev`. `start` is the journal's first
    entry; its market calendar, never the entry's own payload, sets a bar's time window."""
    if entry.session_date > entry.written_at.date():
        raise _refuse(
            SESSION_AHEAD,
            f"Session {entry.session_date} is later than the day it is written "
            f"({entry.written_at.date()}). A day cannot be recorded before it happens.",
            "Check the clock and the session date.",
        )
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
    if entry.kind == "bar":
        _check_bar_window(start, entry)


def _check_not_after(prev: Entry, entry: Entry) -> None:
    # A stop, or the first session after the start, may share the last session date: a follow can
    # start in the morning of the session it first records.
    same_ok = entry.kind == "stop" or prev.kind == "start"
    not_after = entry.session_date < prev.session_date or (
        entry.session_date == prev.session_date and not same_ok
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


def session_close(calendar: str, session: date) -> datetime:
    """The close of `session`. With no exchange calendar ("") a day closes at 00:00 UTC after it."""
    if not calendar:
        return datetime(session.year, session.month, session.day, tzinfo=UTC) + timedelta(days=1)
    return session_bounds(calendar, session)[1]


def next_open(calendar: str, session: date) -> datetime:
    """The open of the session after `session`: the open of the paper fill."""
    if not calendar:
        return session_close(calendar, session)
    nxt = sessions_between(calendar, session + timedelta(1), session + timedelta(14))[0]
    return session_bounds(calendar, nxt)[0]


def _check_bar_window(start: Entry | None, entry: Entry) -> None:
    calendar = start.payload.get(CALENDAR_KEY) if start else None
    given = entry.payload.get("must_write_by")
    if calendar is None:
        if given is not None:
            raise _refuse(
                DEADLINE_FORGED,
                "This bar names `must_write_by`, but the start entry names no market calendar.",
                "Do not write deadlines by hand. Run `alpha follow update`.",
            )
        late = (entry.written_at.date() - entry.session_date).days
        if late > MAX_BAR_LATENESS_DAYS:
            raise _too_late(entry, f"A bar must be written within {MAX_BAR_LATENESS_DAYS} day.")
        return
    try:
        closes = session_close(str(calendar), entry.session_date)
        opens = next_open(str(calendar), entry.session_date)
    except (DataError, IndexError) as exc:
        raise _refuse(
            DEADLINE_FORGED,
            f"{entry.session_date} is not a session of {calendar or 'a daily market'}: {exc}",
            "Do not edit the journal. Run `alpha follow verify`.",
        ) from exc
    deadline = opens if calendar else closes + timedelta(days=MAX_BAR_LATENESS_DAYS)
    if given != (opens.isoformat() if calendar else None):
        raise _refuse(
            DEADLINE_FORGED,
            f"The bar of {entry.session_date} names a `must_write_by` that is not the calendar's.",
            "Do not write deadlines by hand. Run `alpha follow update`.",
        )
    if entry.written_at < closes:
        raise _refuse(
            BAR_BEFORE_CLOSE,
            f"The bar of {entry.session_date} is written before that session closed.",
            "A decision waits for the close. Run the update after the close.",
        )
    if entry.written_at > deadline:
        raise _too_late(entry, "It was written after the next session opened.")


def _too_late(entry: Entry, why: str) -> JournalRefusal:
    return _refuse(
        BAR_TOO_LATE,
        f"The session of {entry.session_date} was not recorded in time. {why}",
        "Write that day as `missed`. It cannot be written as a bar.",
    )
