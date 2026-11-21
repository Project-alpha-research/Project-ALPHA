"""`alpha follow update` for a followed rule test: one journal entry per new session. Paper only.

Decide on the close of session t from the bars known at the run time. The paper fill is the open
of t+1 and is booked by the update that first sees that bar. Rules for a session that is not
written in time (market calendar, `alpha_data.sessions`; crypto trades every day):
- the session has closed and its bar is not stored: a `late` entry, no decision;
- the run is after the next session's open (crypto: more than a day after the session): a
  `missed` entry that says what the rule "would have signalled". No paper order. An older
  skipped session is written the same way, never back-filled as a normal entry;
- otherwise a normal `bar` entry. There is one entry per session.
Each run replays the frozen rule over the stored bars with the rule test's engine step and
compares the journal with it. The journal is never rewritten: the replay is a check. Reads the
newest bars only through `follow_source`. Writes only under `forward/<follow id>/`.
"""

from __future__ import annotations

import bisect
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from alpha_cli import follow_book as paper
from alpha_cli import follow_replay as engine
from alpha_cli import follow_source
from alpha_cli import follow_store as store
from alpha_cli.follow_chain import append_entry
from alpha_cli.follow_journal import (
    CALENDAR_KEY,
    MAX_BAR_LATENESS_DAYS,
    STOPPED,
    Clock,
    Entry,
    JournalRefusal,
    Kind,
    session_close,
)
from alpha_cli.follow_journal import next_open as _next_open
from alpha_cli.follow_replay import Replay
from alpha_cli.follow_update_check import Digests, check_replay, digests_of
from alpha_cli.spine.errors import SpineError
from alpha_core import DataError
from alpha_data.sessions import sessions_between


class _Ctx:
    def __init__(self, home: Path, record: store.FollowRecord, now: datetime) -> None:
        self.record, self.now, self.asset = record, now, record.assets[0]
        self.idea = follow_source.frozen_idea(home, record.source_id, record.spec_sha256)
        self.bars, self.calendar = follow_source.forward_bars(home, self.asset, now)
        self.dates = [b.ts.date() for b in self.bars]
        self.digests: Digests = digests_of(self.bars)
        self.first_session = self._first_session()
        self.first = bisect.bisect_left(self.dates, self.first_session)
        self.engine_sha = engine.engine_code_sha256()
        self.replay: Replay | None = None
        if self.first < len(self.bars):
            try:
                self.replay = engine.replay(self.bars, self.idea, self.first)
            except DataError as exc:
                raise follow_source.refuse(
                    "FOLLOW_NOT_ENOUGH_HISTORY",
                    f"Cannot replay the rule: {exc}",
                    "Store more bars before the follow's start.",
                ) from exc

    def _first_session(self) -> date:
        start = self.record.started_at
        days = [start.date() + timedelta(n) for n in range(15)]
        if self.calendar is not None:
            days = _sessions(self.calendar, days[0], days[-1])
        return next(s for s in days if close_of(self.calendar, s) > start)

    def expected(self) -> list[date]:
        days = [
            self.first_session + timedelta(n)
            for n in range((self.now.date() - self.first_session).days + 1)
        ]
        if self.calendar is not None:
            days = _sessions(self.calendar, self.first_session, self.now.date())
        return [s for s in days if close_of(self.calendar, s) <= self.now]


def _sessions(calendar: str, first: date, last: date) -> list[date]:
    """The sessions of the forward window only, or a plain-words refusal outside the calendar."""
    with follow_source.calendar_guard(calendar):
        return sessions_between(calendar, first, last)


def close_of(calendar: str | None, session: date) -> datetime:
    with follow_source.calendar_guard(calendar):
        return session_close(calendar or "", session)


def next_open(calendar: str | None, session: date) -> datetime:
    # The open after `session` is up to 14 days on: a session at the calendar's end has none.
    with follow_source.calendar_guard(calendar):
        return _next_open(calendar or "", session)


def _armed(replay: Replay | None, session: date) -> bool:
    """False while the rule has stayed long since before the start: the paper book waits for the
    next entry signal. True once the rule was not long at the start, or has been flat since."""
    if replay is None or not replay.long_before:
        return True
    return any(not d.long for day, d in replay.sessions.items() if day < session)


def _settle(ctx: _Ctx, book: paper.Book, session: date) -> tuple[paper.Book, list[dict[str, Any]]]:
    pending = book["pending"]
    if pending is None:
        return book, []
    at = bisect.bisect_right(ctx.dates, date.fromisoformat(pending["decided"]))
    if at >= len(ctx.bars) or ctx.dates[at] > session:
        return book, []
    bar = ctx.bars[at]
    hit = ctx.replay.fills.get(ctx.dates[at]) if ctx.replay else None
    slip = ctx.idea.costs.slippage_bps / 10_000.0
    sign = 1.0 if pending["side"] == "buy" else -1.0
    price, source = (hit.price, "engine") if hit else (bar.open * (1 + sign * slip), "open")
    costs = ctx.idea.costs
    book, done = paper.fill(
        book,
        price=price,
        ts=bar.ts.isoformat(),
        size_pct=ctx.record.paper_account_percent,
        fee_bps=costs.fee_bps,
    )
    return book, [{**done, "price_from": source}]


def _entry(
    ctx: _Ctx, book: paper.Book, session: date
) -> tuple[Kind, dict[str, Any], dict[str, str], paper.Book]:
    at = ctx.dates.index(session) if session in ctx.dates else None
    opens = next_open(ctx.calendar, session)
    past = (
        (ctx.now.date() - session).days > MAX_BAR_LATENESS_DAYS
        if ctx.calendar is None
        else ctx.now > opens
    )
    kind: Kind = "missed" if past else ("bar" if at is not None else "late")
    book, fills = _settle(ctx, book, session)
    payload: dict[str, Any] = {"session": session.isoformat(), "paper": True, "fills": fills}
    payload["engine_code_sha256"] = ctx.engine_sha
    if kind == "late":
        payload.update(reason="the bar of this session was not stored at run time", book=book)
        return kind, payload, {}, book
    if at is None or ctx.replay is None:
        payload.update(reason="the bar of this session is not stored; no decision", book=book)
        return kind, payload, {}, book
    book = paper.mark(book, ctx.bars[at].close)
    seen = ctx.replay.sessions.get(session)
    held, words = paper.decide(
        book, long=bool(seen and seen.long), armed=_armed(ctx.replay, session), session=session
    )
    note = {} if seen else {"words": "no signal: indicators still warming up"}
    decision = {
        **words,
        **note,
        "signal": seen.signal if seen else None,
        "reason": seen.reason if seen else "",
    }
    payload.update(
        readings=seen.readings if seen else {}, latest_bar_ts=ctx.bars[-1].ts.isoformat()
    )
    if kind == "bar":
        book = held
        payload["decision"] = decision
        payload["labels"] = _labels(ctx, session, opens)
    else:
        payload.update(
            would_have=decision["words"], reason="written after the next open: no paper order"
        )
    payload["book"] = book
    return kind, payload, {ctx.asset: ctx.digests[at]}, book


def _labels(ctx: _Ctx, session: date, opens: datetime) -> list[str]:
    if ctx.calendar is None:
        hours = (ctx.now - opens).total_seconds() / 3600.0
        return [f"written {hours:.1f} h after the fill open"]
    return ["written late, before the fill"] if ctx.now.date() > session else []


def _last_book(entries: list[Entry]) -> paper.Book:
    for entry in reversed(entries):
        if "book" in entry.payload:
            return dict(entry.payload["book"])
    return paper.new_book()


def update_follow(home: Path, follow_id: str, *, clock: Clock) -> dict[str, Any]:
    """Write one entry per new session of a followed rule test, or say there is nothing to write."""
    folder = store.folder_of(home, follow_id)
    record = store.load_record(folder)
    entries = store.entries_of(home, follow_id)
    if store.state_of(entries) == "stopped":
        raise follow_source.refuse(
            STOPPED,
            f"Follow {follow_id} is stopped.",
            "Start a new follow with `alpha follow start`.",
        )
    if record.kind != "rule_test":
        raise follow_source.refuse(
            "FOLLOW_UPDATE_SETUP_NOT_BUILT",
            "Following a setup is not built yet. Only a followed rule test can be updated.",
            "Follow a rule test (--test).",
        )
    now = clock()
    ctx = _Ctx(home, record, now)
    sealed = entries[0].payload.get(CALENDAR_KEY)
    if sealed is None or sealed != (ctx.calendar or ""):
        raise follow_source.refuse(
            "FOLLOW_CALENDAR_CHANGED",
            f"The start entry names the market calendar {sealed!r}; the store now names "
            f"{ctx.calendar or ''!r}. The journal deadlines come only from the start entry.",
            "Start a new follow with `alpha follow start`.",
        )
    last = entries[-1]
    todo = [s for s in ctx.expected() if last.kind == "start" or s > last.session_date]
    check = check_replay(
        asset=ctx.asset,
        dates=ctx.dates,
        digests=ctx.digests,
        replay=ctx.replay,
        engine_sha=ctx.engine_sha,
        entries=entries,
    )
    if not todo:
        waiting = last.kind == "start"
        newest = f"The newest completed session, {last.session_date}, is already in the journal."
        message = (
            "No session has closed since the follow started: waiting for its first new bar."
            if waiting
            else newest
        )
        return {
            "follow_id": follow_id,
            "status": "no-op",
            "written": [],
            "message": message,
            "replay": check,
        }
    book, written = _last_book(entries), []
    for session in todo:
        kind, payload, hashes, book = _entry(ctx, book, session)
        body = {**payload, "replay": check}
        entry = append_entry(
            folder,
            kind=kind,
            session_date=session,
            clock=lambda: now,
            bar_hashes=hashes,
            payload=body,
            follow_id=follow_id,
        )
        words = payload.get("decision", {}).get("words") or payload.get("would_have", "no decision")
        written.append(
            {"seq": entry.seq, "session": session.isoformat(), "kind": kind, "words": words}
        )
    return {
        "follow_id": follow_id,
        "status": "written",
        "written": written,
        "replay": check,
        "message": f"Wrote {len(written)} entr{'y' if len(written) == 1 else 'ies'} (paper).",
    }


def update_all(home: Path, *, clock: Clock) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for follow_id in store.all_ids(home):
        try:
            record = store.load_record(store.folder_of(home, follow_id))
            if store.state_of(store.entries_of(home, follow_id)) == "stopped":
                rows.append({"follow_id": follow_id, "status": "skipped", "message": "stopped"})
            elif record.kind != "rule_test":
                rows.append(
                    {
                        "follow_id": follow_id,
                        "status": "skipped",
                        "message": "a setup follow is not built yet",
                    }
                )
            else:
                rows.append(update_follow(home, follow_id, clock=clock))
        except (SpineError, JournalRefusal) as exc:
            rows.append(
                {
                    "follow_id": follow_id,
                    "status": "refused",
                    "message": str(exc),
                    "code": exc.payload["code"],
                }
            )
    return rows
