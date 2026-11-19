"""The follow journal on disk: the stored head, cut-off lines, the lock and the clock."""

from __future__ import annotations

import json
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from alpha_cli.follow_chain import HEAD_FILE, append_entry, read_entries, verify_journal
from alpha_cli.follow_journal import JournalRefusal, Kind, build_entry

T0 = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)
D0 = date(2026, 11, 19)
FID = "abcdef012345"


def _write(folder: Path, kind: Kind, day: date, at: datetime) -> None:
    payload = {"follow_id": FID} if kind == "start" else {}
    append_entry(folder, kind=kind, session_date=day, clock=lambda: at, payload=payload)


def _journal(folder: Path, bars: int = 3) -> Path:
    _write(folder, "start", D0, T0)
    for i in range(1, bars + 1):
        _write(folder, "bar", D0 + timedelta(days=i), T0 + timedelta(days=i, hours=1))
    return folder / "journal.jsonl"


def _break_code(folder: Path, *, follow_id: str | None = None, now: datetime | None = None) -> str:
    found = verify_journal(folder, follow_id=follow_id, now=now).first_break
    assert found is not None
    return found.code


def test_each_append_stores_the_head(tmp_path: Path) -> None:
    path = _journal(tmp_path)
    head = json.loads((tmp_path / HEAD_FILE).read_text())
    last = json.loads(path.read_text().splitlines()[-1])
    assert head == {"entries": 4, "head": last["entry_hash"]}


def test_removing_the_last_line_fails_verify(tmp_path: Path) -> None:
    path = _journal(tmp_path)
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n")
    assert _break_code(tmp_path) == "FOLLOW_TRUNCATED"
    with pytest.raises(JournalRefusal):
        read_entries(tmp_path)


def test_a_shorter_valid_chain_in_place_of_the_file_fails_verify(tmp_path: Path) -> None:
    _journal(tmp_path / "long", bars=3)
    short = _journal(tmp_path / "short", bars=1)
    (tmp_path / "long" / "journal.jsonl").write_bytes(short.read_bytes())
    assert _break_code(tmp_path / "long") == "FOLLOW_TRUNCATED"


def test_a_replaced_chain_of_the_same_length_fails_verify(tmp_path: Path) -> None:
    _journal(tmp_path / "a", bars=2)
    other = tmp_path / "b"
    _write(other, "start", D0, T0 + timedelta(minutes=5))
    for i in (1, 2):
        _write(other, "bar", D0 + timedelta(days=i), T0 + timedelta(days=i))
    (tmp_path / "a" / "journal.jsonl").write_bytes((other / "journal.jsonl").read_bytes())
    assert _break_code(tmp_path / "a") == "FOLLOW_CHAIN_BROKEN"


def test_a_head_one_behind_after_a_crash_still_verifies(tmp_path: Path) -> None:
    _journal(tmp_path, bars=2)
    head = tmp_path / HEAD_FILE
    stored = json.loads(head.read_text())
    _write(tmp_path, "bar", D0 + timedelta(days=3), T0 + timedelta(days=3))
    head.write_text(json.dumps(stored))
    assert verify_journal(tmp_path).first_break is None
    _write(tmp_path, "bar", D0 + timedelta(days=4), T0 + timedelta(days=4))
    assert json.loads(head.read_text())["entries"] == 5


def test_a_cut_off_last_line_fails_loud_and_blocks_appends(tmp_path: Path) -> None:
    path = _journal(tmp_path)
    data = path.read_bytes()
    path.write_bytes(data + data.splitlines()[1][:40])
    assert _break_code(tmp_path) == "FOLLOW_PARTIAL_LINE"
    with pytest.raises(JournalRefusal, match="not written to its end") as error:
        _write(tmp_path, "bar", D0 + timedelta(days=4), T0 + timedelta(days=4))
    assert "cli-follow.md#repair" in str(error.value.payload["next"])
    assert path.read_bytes().startswith(data)


def test_a_session_after_the_writing_day_is_refused() -> None:
    with pytest.raises(JournalRefusal) as error:
        build_entry(None, kind="start", session_date=D0 + timedelta(days=1), written_at=T0)
    assert error.value.payload["code"] == "FOLLOW_SESSION_AHEAD"


def test_an_entry_dated_after_now_fails_verify(tmp_path: Path) -> None:
    _journal(tmp_path, bars=1)
    assert verify_journal(tmp_path, now=T0 + timedelta(days=2)).first_break is None
    assert _break_code(tmp_path, now=T0 + timedelta(hours=1)) == "FOLLOW_WRITTEN_AHEAD"


def test_a_journal_from_another_follow_fails_verify(tmp_path: Path) -> None:
    _journal(tmp_path, bars=1)
    assert verify_journal(tmp_path, follow_id=FID).first_break is None
    assert _break_code(tmp_path, follow_id="0" * 12) == "FOLLOW_WRONG_FOLDER"


def test_two_writers_at_once_leave_one_intact_chain(tmp_path: Path) -> None:
    _write(tmp_path, "start", D0, T0)
    results: list[str] = []
    gate = threading.Barrier(2)

    def stop() -> None:
        gate.wait()
        try:
            _write(tmp_path, "stop", D0, T0 + timedelta(minutes=1))
            results.append("ok")
        except JournalRefusal as exc:
            results.append(str(exc.payload["code"]))

    threads = [threading.Thread(target=stop) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["FOLLOW_STOPPED", "ok"]
    assert verify_journal(tmp_path).entries == 2
    assert verify_journal(tmp_path).first_break is None
