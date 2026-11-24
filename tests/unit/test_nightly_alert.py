"""The nightly failure marker, the optional desktop notification and the disk trend."""

from __future__ import annotations

import json
import os
import signal
import time
from collections import namedtuple
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli.home_disk import disk_facts, disk_lines, human, tree_bytes
from alpha_cli.main import app
from alpha_cli.nightly_alert import MARKER, failed_line
from alpha_cli.nightly_config import NightlyConfigError, load_config
from alpha_cli.nightly_status import last_night_line, read_records, status_facts, status_text
from alpha_cli.nightly_steps import Outcome
from tests.unit.test_nightly import FakeRunner, Reply, run, states

BOOM: dict[str, Reply] = {"test": Outcome(1, "", "boom", 0.2, False)}
Usage = namedtuple("Usage", "total used free")
GB = 1_000_000_000


def marker(tmp_path: Path) -> Path:
    return tmp_path / "home" / "nightly" / MARKER


def test_a_blocking_defect_writes_the_marker_in_plain_words(tmp_path: Path) -> None:
    record = run(tmp_path, FakeRunner(BOOM))
    assert record["blocking"] == 1
    text = marker(tmp_path).read_text(encoding="utf-8")
    name = f"{record['date']}-{record['run_number']}"
    assert text.startswith(f"The last nightly run failed: run {name} has 1 blocking defect.")
    assert f"Date: {record['date']}" in text and f"Run: {name}" in text
    assert "N1.test: " in text and "boom" in text
    leftovers = [p.name for p in marker(tmp_path).parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []  # atomic: no half-written sibling stays behind


def test_a_clean_run_writes_no_marker(tmp_path: Path) -> None:
    run(tmp_path, FakeRunner())
    assert not marker(tmp_path).exists()
    assert failed_line(tmp_path / "home") is None


def test_a_later_clean_full_run_removes_the_marker(tmp_path: Path) -> None:
    run(tmp_path, FakeRunner(BOOM))
    assert marker(tmp_path).exists()
    run(tmp_path, FakeRunner(), only=("N2",))
    assert marker(tmp_path).exists()  # a partial run proves too little to clear it
    run(tmp_path, FakeRunner())
    assert not marker(tmp_path).exists()


def test_a_crashing_step_still_leaves_the_marker_and_fails_loud(tmp_path: Path) -> None:
    def crash(tail: list[str]) -> Outcome:
        raise RuntimeError("injected failure in a step")

    with pytest.raises(RuntimeError, match="injected failure"):
        run(tmp_path, FakeRunner({"setup find": crash}))
    text = marker(tmp_path).read_text(encoding="utf-8")
    assert text.startswith("The last nightly run failed: run ")
    assert "stopped before it finished" in text and "injected failure in a step" in text
    assert read_records(tmp_path / "home") == []  # no record was written, so the marker speaks


def test_status_and_next_show_one_plain_line(tmp_path: Path) -> None:
    home = tmp_path / "home"
    run(tmp_path, FakeRunner(BOOM))
    facts = status_facts(home, tmp_path / "nightly.toml")
    line = facts["failed"]
    assert line.startswith("The last nightly run failed: ") and "\n" not in line
    assert status_text(facts).splitlines()[0] == line
    assert line in str(last_night_line(home))
    env = {"ALPHA_DATA_DIR": str(home)}
    assert line in CliRunner().invoke(app, ["next"], env=env).output
    assert line in CliRunner().invoke(app, ["nightly", "status"], env=env).output
    run(tmp_path, FakeRunner())
    assert status_facts(home, tmp_path / "nightly.toml")["failed"] is None
    assert "failed" not in str(last_night_line(home))


def fake_notify(folder: Path, exit_code: int = 0) -> Path:
    """A fake `notify-send` on PATH: it writes its arguments to a file."""
    folder.mkdir(parents=True, exist_ok=True)
    seen = folder / "seen.txt"
    program = folder / "notify-send"
    program.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{seen}"\nexit {exit_code}\n')
    program.chmod(0o755)
    return seen


def test_notification_is_sent_only_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = fake_notify(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    run(tmp_path / "off", FakeRunner(BOOM))
    assert not seen.exists()
    record = run(tmp_path / "on", FakeRunner(BOOM), notify=True)
    lines = seen.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and lines[1].startswith("The last nightly run failed: run ")
    assert record["blocking"] == 1
    seen.unlink()
    run(tmp_path / "clean", FakeRunner(), notify=True)
    assert not seen.exists()  # a clean night sends nothing


def test_a_missing_or_failing_notifier_never_changes_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = run(tmp_path / "plain", FakeRunner(BOOM))
    fake_notify(tmp_path / "bin", exit_code=3)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    failing = run(tmp_path / "failing", FakeRunner(BOOM), notify=True)
    monkeypatch.setenv("PATH", str(tmp_path / "nothing-here"))
    missing = run(tmp_path / "missing", FakeRunner(BOOM), notify=True)
    for record in (failing, missing):
        assert states(record) == states(plain) and record["blocking"] == 1
    assert marker(tmp_path / "failing").exists() and marker(tmp_path / "missing").exists()


def test_notify_is_a_true_or_false_setting(tmp_path: Path) -> None:
    for name in ("rule.toml", "setup.toml"):
        (tmp_path / name).write_text("x = 1\n")
    body = 'assets = ["SPY"]\nrule_spec = "rule.toml"\nsetup_spec = "setup.toml"\n'
    path = tmp_path / "nightly.toml"
    path.write_text(body)
    assert load_config(path).notify is False
    path.write_text(body + "notify = true\n")
    assert load_config(path).notify is True
    path.write_text(body + 'notify = "yes"\n')
    with pytest.raises(NightlyConfigError, match="notify"):
        load_config(path)


def test_each_new_record_keeps_the_home_size_at_the_end_of_its_run(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "data").mkdir(parents=True)
    (home / "data" / "bars.bin").write_bytes(b"x" * 5000)
    record = run(tmp_path, FakeRunner())
    assert isinstance(record["home_bytes"], int) and record["home_bytes"] >= 5000
    stored = json.loads((home / "nightly" / f"{record['date']}-1" / "record.json").read_text())
    assert stored["home_bytes"] == record["home_bytes"]


def test_tree_bytes_counts_files_and_never_follows_links(tmp_path: Path) -> None:
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"y" * 9000)
    home = tmp_path / "home"
    (home / "a").mkdir(parents=True)
    (home / "a" / "one").write_bytes(b"x" * 100)
    (home / "two").write_bytes(b"x" * 23)
    (home / "link").symlink_to(outside)
    assert tree_bytes(home) < 9000 and tree_bytes(home) >= 123
    assert tree_bytes(tmp_path / "absent") == 0


def test_human_sizes() -> None:
    assert [human(0), human(999), human(1500), human(2_340_000), human(7 * GB)] == [
        "0 bytes",
        "999 bytes",
        "1.5 kB",
        "2.3 MB",
        "7.0 GB",
    ]


def records(sizes: Sequence[int | None]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, size in enumerate(sizes, 1):
        row: dict[str, Any] = {"date": "2026-11-20", "run_number": number}
        if size is not None:
            row["home_bytes"] = size
        rows.append(row)
    return rows


def test_trend_reads_stored_sizes_and_old_records_say_not_recorded(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    facts = disk_facts(
        home, records([None, 1 * GB, 3 * GB]), lambda _: Usage(500 * GB, 0, 400 * GB)
    )
    trend = facts["trend"]
    assert trend["recorded"] == 2 and trend["not_recorded"] == 1
    assert trend["first"] == {"run": "2026-11-20-2", "bytes": 1 * GB}
    assert trend["last"] == {"run": "2026-11-20-3", "bytes": 3 * GB}
    assert trend["change_bytes"] == 2 * GB
    text = "\n".join(disk_lines(facts))
    assert "Free space on its disk: 400.0 GB" in text
    assert "grew by 2.0 GB" in text and "1 older record: not recorded" in text
    empty = disk_facts(home, records([None]), lambda _: Usage(500 * GB, 0, 400 * GB))
    assert empty["trend"]["change_bytes"] is None
    assert "not recorded" in "\n".join(disk_lines(empty))


def test_low_free_space_is_one_plain_line_against_the_owner_reserve(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "crypto").mkdir(parents=True)
    reserve = {
        "schema": "OwnerStorageReserveV1",
        "minimum_free_bytes": 10 * GB,
        "advisory_free_bytes": 20 * GB,
        "decided_by": "owner",
        "decided_on": "2026-11-14",
        "decision_record": "ADR-0043",
    }
    settings = json.dumps({"schema": "CryptoBulkStorageConfigV1", "free_space_reserve": reserve})
    (home / "crypto" / "storage-config.json").write_text(settings)
    low = disk_facts(home, [], lambda _: Usage(500 * GB, 0, 4 * GB))
    assert low["reserve_bytes"] == 10 * GB and low["under_reserve"] is True
    warning = [line for line in disk_lines(low) if "under your storage reserve" in line]
    assert len(warning) == 1 and "4.0 GB" in warning[0] and "10.0 GB" in warning[0]
    fine = disk_facts(home, [], lambda _: Usage(500 * GB, 0, 40 * GB))
    assert fine["under_reserve"] is False
    assert not any("under your storage reserve" in line for line in disk_lines(fine))


def test_without_an_owner_setting_the_default_reserve_applies(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    facts = disk_facts(home, [], lambda _: Usage(1000 * GB, 0, 120 * GB))
    assert facts["reserve_bytes"] == 150 * GB and facts["under_reserve"] is True
    assert "default" in facts["reserve_source"]
    (home / "crypto").mkdir()
    (home / "crypto" / "storage-config.json").write_text("not json")
    broken = disk_facts(home, [], lambda _: Usage(1000 * GB, 0, 120 * GB))
    assert broken["reserve_bytes"] is None and broken["under_reserve"] is None
    assert any("cannot be read" in line for line in disk_lines(broken))


def test_status_shows_the_disk_lines_and_writes_nothing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    run(tmp_path, FakeRunner())
    before = sorted(str(p) for p in home.rglob("*"))
    facts = status_facts(home, tmp_path / "nightly.toml")
    assert facts["disk"]["home_bytes"] > 0 and facts["disk"]["free_bytes"] > 0
    assert facts["disk"]["trend"]["recorded"] == 1
    text = status_text(facts)
    assert "Data home size now: " in text and "Free space on its disk: " in text
    assert sorted(str(p) for p in home.rglob("*")) == before


def test_a_hanging_notifier_is_stopped_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli import nightly_alert

    folder = tmp_path / "bin"
    folder.mkdir()
    program = folder / "notify-send"
    started = folder / "sleeper.pid"
    program.write_text(f"#!/bin/sh\nsleep 30 &\necho $! > {started}\nwait\n")
    program.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(nightly_alert, "NOTIFY_SECONDS", 1.0)
    record = run(tmp_path / "slow", FakeRunner(BOOM), notify=True)
    assert record["blocking"] == 1 and marker(tmp_path / "slow").exists()
    # The program started a child of its own: it must be gone when the notice gives up.
    sleeper = int(started.read_text())
    for _ in range(100):
        try:
            os.kill(sleeper, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        os.kill(sleeper, signal.SIGKILL)
        pytest.fail("the notifier's own child was left running")


def test_a_failure_while_writing_the_record_still_leaves_the_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli import nightly_run

    def broken(folder: Path, record: dict[str, Any]) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(nightly_run, "write_record", broken)
    with pytest.raises(OSError, match="disk full"):
        run(tmp_path, FakeRunner())
    assert "disk full" in marker(tmp_path).read_text(encoding="utf-8")


def test_a_marker_that_cannot_be_written_never_hides_the_real_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli import nightly_alert

    def refuse(path: Path, text: str) -> None:
        raise OSError("marker write refused")

    monkeypatch.setattr(nightly_alert, "write_text", refuse)

    def crash(tail: list[str]) -> Outcome:
        raise RuntimeError("the real failure")

    with pytest.raises(RuntimeError, match="the real failure"):
        run(tmp_path / "a", FakeRunner({"setup find": crash}))
    record = run(tmp_path / "b", FakeRunner(BOOM))  # a refused marker never changes the result
    assert record["blocking"] == 1


def test_an_interrupted_run_leaves_the_marker(tmp_path: Path) -> None:
    def stop(tail: list[str]) -> Outcome:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, FakeRunner({"setup find": stop}))
    assert "stopped before it finished" in marker(tmp_path).read_text(encoding="utf-8")
