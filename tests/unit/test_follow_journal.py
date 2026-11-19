"""The follow journal: append-only, hash-chained, and strict about back-fill."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from alpha_cli.follow_chain import append_entry, read_entries, verify_journal
from alpha_cli.follow_journal import (
    GENESIS,
    MAX_BAR_LATENESS_DAYS,
    Entry,
    JournalRefusal,
    Kind,
    build_entry,
    check_rules,
)

T0 = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)
D0 = date(2026, 11, 19)
HASH = "a" * 64


def _write(
    folder: Path,
    kind: Kind,
    day: date,
    at: datetime,
    *,
    bar_hashes: dict[str, str] | None = None,
    payload: dict[str, object] | None = None,
) -> Entry:
    return append_entry(
        folder,
        kind=kind,
        session_date=day,
        clock=lambda: at,
        bar_hashes=bar_hashes,
        payload=payload,
    )


def _journal(folder: Path, bars: int = 3) -> Path:
    _write(folder, "start", D0, T0, bar_hashes={"SPY": HASH})
    for i in range(1, bars + 1):
        _write(folder, "bar", D0 + timedelta(days=i), T0 + timedelta(days=i, hours=1))
    return folder / "journal.jsonl"


def _code(error: pytest.ExceptionInfo[JournalRefusal]) -> str:
    return str(error.value.payload["code"])


def test_start_entry_chains_from_genesis_and_next_entry_links_to_it(tmp_path: Path) -> None:
    first = _write(tmp_path, "start", D0, T0, bar_hashes={"SPY": HASH})
    second = _write(tmp_path, "bar", D0 + timedelta(days=1), T0 + timedelta(days=1))
    assert (first.seq, first.prev_hash) == (1, GENESIS)
    assert (second.seq, second.prev_hash) == (2, first.entry_hash)
    assert [e.kind for e in read_entries(tmp_path)] == ["start", "bar"]
    assert verify_journal(tmp_path).first_break is None


def test_session_date_must_be_after_the_last_session_date(tmp_path: Path) -> None:
    _journal(tmp_path, bars=2)
    with pytest.raises(JournalRefusal) as same:
        _write(tmp_path, "bar", D0 + timedelta(days=2), T0 + timedelta(days=3))
    with pytest.raises(JournalRefusal) as older:
        _write(tmp_path, "missed", D0 + timedelta(days=1), T0 + timedelta(days=3))
    assert _code(same) == _code(older) == "FOLLOW_SESSION_NOT_AFTER"
    assert "no inserts" in str(same.value)


def test_written_at_must_not_go_backwards(tmp_path: Path) -> None:
    _write(tmp_path, "start", D0, T0)
    _write(tmp_path, "bar", D0 + timedelta(days=1), T0 + timedelta(days=2))
    with pytest.raises(JournalRefusal) as error:
        _write(tmp_path, "bar", D0 + timedelta(days=2), T0 + timedelta(days=2, hours=-1))
    assert _code(error) == "FOLLOW_CLOCK_BACK"


def test_a_sequence_gap_is_refused() -> None:
    first = build_entry(None, kind="start", session_date=D0, written_at=T0)
    second = build_entry(
        first, kind="bar", session_date=D0 + timedelta(days=1), written_at=T0 + timedelta(days=1)
    )
    skipped = second.model_copy(update={"seq": 3})
    with pytest.raises(JournalRefusal) as error:
        check_rules(first, skipped)
    assert _code(error) == "FOLLOW_SEQ_GAP"


def test_a_broken_chain_is_refused_by_the_writer(tmp_path: Path) -> None:
    path = _journal(tmp_path, bars=2)
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    with pytest.raises(JournalRefusal) as error:
        _write(tmp_path, "bar", D0 + timedelta(days=9), T0 + timedelta(days=9))
    assert _code(error) in {"FOLLOW_SEQ_GAP", "FOLLOW_CHAIN_BROKEN"}
    first = build_entry(None, kind="start", session_date=D0, written_at=T0)
    wrong = build_entry(
        first, kind="bar", session_date=D0 + timedelta(days=1), written_at=T0 + timedelta(days=1)
    )
    with pytest.raises(JournalRefusal) as link:
        check_rules(first.model_copy(update={"entry_hash": HASH}), wrong)
    assert _code(link) == "FOLLOW_CHAIN_BROKEN"


def test_nothing_can_be_written_after_stop(tmp_path: Path) -> None:
    _journal(tmp_path, bars=1)
    _write(tmp_path, "stop", D0 + timedelta(days=2), T0 + timedelta(days=2), payload={"r": "x"})
    kinds: tuple[Kind, ...] = ("bar", "missed", "late", "stop")
    for kind in kinds:
        with pytest.raises(JournalRefusal) as error:
            _write(tmp_path, kind, D0 + timedelta(days=5), T0 + timedelta(days=5))
        assert _code(error) == "FOLLOW_STOPPED"


def test_a_second_start_is_refused(tmp_path: Path) -> None:
    _journal(tmp_path, bars=0)
    with pytest.raises(JournalRefusal) as error:
        _write(tmp_path, "start", D0 + timedelta(days=1), T0 + timedelta(days=1))
    assert _code(error) == "FOLLOW_SECOND_START"


def test_the_first_entry_must_be_a_start(tmp_path: Path) -> None:
    with pytest.raises(JournalRefusal) as error:
        _write(tmp_path, "bar", D0, T0)
    assert _code(error) == "FOLLOW_NO_START"


def test_a_late_day_can_only_be_written_as_missed_never_as_bar(tmp_path: Path) -> None:
    _write(tmp_path, "start", D0, T0)
    day = D0 + timedelta(days=1)
    on_time = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(
        days=MAX_BAR_LATENESS_DAYS, hours=23
    )
    too_late = on_time + timedelta(hours=2)
    with pytest.raises(JournalRefusal) as error:
        _write(tmp_path, "bar", day, too_late)
    assert _code(error) == "FOLLOW_BAR_TOO_LATE"
    with pytest.raises(JournalRefusal):
        build_entry(None, kind="bar", session_date=day, written_at=too_late)
    assert _write(tmp_path, "missed", day, too_late).kind == "missed"
    assert _write(tmp_path, "bar", too_late.date(), too_late + timedelta(hours=1)).kind == "bar"


def test_every_kind_can_be_written_with_bar_hashes_and_a_payload(tmp_path: Path) -> None:
    _write(tmp_path, "start", D0, T0, bar_hashes={"SPY": HASH})
    _write(
        tmp_path, "bar", D0 + timedelta(days=1), T0 + timedelta(days=1), bar_hashes={"SPY": HASH}
    )
    _write(tmp_path, "late", D0 + timedelta(days=2), T0 + timedelta(days=2), payload={"why": "x"})
    _write(tmp_path, "missed", D0 + timedelta(days=3), T0 + timedelta(days=5))
    _write(tmp_path, "stop", D0 + timedelta(days=6), T0 + timedelta(days=6), payload={"n": 1})
    kinds = [e.kind for e in read_entries(tmp_path)]
    assert kinds == ["start", "bar", "late", "missed", "stop"]
    assert verify_journal(tmp_path).first_break is None


def test_written_at_must_be_aware_utc() -> None:
    with pytest.raises(ValueError, match="UTC"):
        build_entry(None, kind="start", session_date=D0, written_at=datetime(2026, 11, 19, 8, 0))


def test_verify_detects_a_flipped_byte(tmp_path: Path) -> None:
    path = _journal(tmp_path)
    text = path.read_text()
    lines = text.splitlines()
    row = json.loads(lines[2])
    row["payload"] = {"changed": True}
    lines[2] = json.dumps(row, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    report = verify_journal(tmp_path)
    assert report.first_break is not None and report.first_break.seq == 3
    assert report.first_break.code == "FOLLOW_CHAIN_BROKEN"


def test_verify_detects_a_removed_line(tmp_path: Path) -> None:
    path = _journal(tmp_path)
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[2], lines[3]]) + "\n")
    report = verify_journal(tmp_path)
    assert report.first_break is not None and report.first_break.seq == 2


def test_verify_detects_a_reordered_line(tmp_path: Path) -> None:
    path = _journal(tmp_path)
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[2], lines[1], lines[3]]) + "\n")
    report = verify_journal(tmp_path)
    assert report.first_break is not None and report.first_break.seq == 2


def test_verify_detects_a_line_that_cannot_be_read(tmp_path: Path) -> None:
    path = _journal(tmp_path)
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[1][:-9], lines[2]]) + "\n")
    report = verify_journal(tmp_path)
    assert report.first_break is not None and report.first_break.seq == 2


def test_verify_of_a_clean_journal_reports_the_head(tmp_path: Path) -> None:
    path = _journal(tmp_path)
    last = json.loads(path.read_text().splitlines()[-1])
    report = verify_journal(tmp_path)
    assert report.first_break is None
    assert (report.entries, report.head) == (4, last["entry_hash"])
