"""The final check's slots and the durable jobs stand on `home_db`, off the old control store.

`old_home_store_v7.sqlite3.gz` is a synthetic store made by the code on main before the split
(the old `ControlStore` and the old slot writer): schema version 7, all old tables and triggers,
one spent slot with its result and one running job. The new path must read it and append to it
with no migration, and must not touch its version or its other tables.
"""

from __future__ import annotations

import gzip
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alpha_cli import reserved_slots
from alpha_cli.control_store import ControlStore
from alpha_cli.job_store import JobStore
from alpha_core import DataError

FIXTURE = Path(__file__).parents[1] / "fixtures" / "old_home_store_v7.sqlite3.gz"
DB = Path("control") / "workstation.sqlite3"
OLD_JOB = "00000000-0000-4000-8000-000000000001"
NOW = datetime(2026, 2, 1, tzinfo=UTC)


def _frozen(n: int) -> dict[str, str]:
    return {
        "run_id": f"run{n:013d}",
        "rule": "synthetic",
        "symbol": f"SY{n}",
        "spec_sha256": "a" * 64,
        "test_key_sha256": reserved_slots.sha256(["key", n]),
        "family_asset": f"synthetic|SY{n}",
    }


def _schema(home: Path) -> tuple[int, list[tuple[str, str]]]:
    with sqlite3.connect(home / DB) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        objects = connection.execute(
            "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    return version, objects


def _old_home(tmp_path: Path) -> Path:
    (tmp_path / "control").mkdir()
    (tmp_path / DB).write_bytes(gzip.decompress(FIXTURE.read_bytes()))
    return tmp_path


def test_an_old_home_reads_and_appends_with_no_migration(tmp_path: Path) -> None:
    home = _old_home(tmp_path)
    before = _schema(home)
    assert before[0] == 7 and len(before[1]) > 60
    [spent] = reserved_slots.receipts(home)
    assert spent["slot"] == 1 and spent["frozen"] == _frozen(1) | {
        "symbol": "SYN",
        "family_asset": "synthetic|SYN",
    }
    assert spent["result"]["reserved"] == {"note": "synthetic"}
    with pytest.raises(DataError, match="already confirmed once"):
        reserved_slots.take_slot(home, frozen=spent["frozen"], now=NOW)
    assert reserved_slots.take_slot(home, frozen=_frozen(2), now=NOW)["slot"] == 2

    jobs = JobStore(home)
    assert jobs.get_job(OLD_JOB)["status"] == "running"
    assert jobs.append_job_event(OLD_JOB, event_type="heartbeat", payload={"n": 2}, at=NOW)[
        "sequence"
    ] == 4
    jobs.set_job_status(OLD_JOB, "succeeded", at=NOW)
    new = jobs.create_job(kind="ml:synthetic", request={"n": 1}, at=NOW)
    assert [row["job_id"] for row in jobs.list_jobs()] == sorted([OLD_JOB, str(new["job_id"])])

    assert _schema(home) == before
    # The old store still opens the same file, as it must until it is deleted.
    store = ControlStore(home)
    assert store.get_job(OLD_JOB)["status"] == "succeeded"
    with store._readonly_transaction() as connection:
        assert tuple(connection.execute("SELECT count(*) FROM jobs").fetchone()) == (2,)


def test_a_fresh_home_with_only_the_final_check_gets_only_the_slot_tables(tmp_path: Path) -> None:
    assert reserved_slots.receipts(tmp_path) == []
    assert not (tmp_path / "control").exists()
    reserved_slots.take_slot(tmp_path, frozen=_frozen(1), now=NOW)
    assert _schema(tmp_path) == (
        0,
        [("table", "reserved_slot_receipts"), ("table", "reserved_slot_results")],
    )
    JobStore(tmp_path).create_job(kind="ml:synthetic", request={}, at=NOW)
    version, objects = _schema(tmp_path)
    assert version == 0
    assert {name for _, name in objects} == {
        "idx_job_project",
        "job_events",
        "jobs",
        "reserved_slot_receipts",
        "reserved_slot_results",
    }
    # Until it is deleted, the old store can still build its schema around the kept tables.
    store = ControlStore(tmp_path)
    store.list_active_owner_credentials()
    assert _schema(tmp_path)[0] == 7
    assert len(store.list_jobs()) == 1
    assert len(reserved_slots.receipts(tmp_path)) == 1
    with store._readonly_transaction() as connection:
        count = connection.execute("SELECT count(*) FROM reserved_slot_receipts").fetchone()
        assert tuple(count) == (1,)


def test_the_slot_read_never_creates_or_writes(tmp_path: Path) -> None:
    home = _old_home(tmp_path)
    (home / DB).chmod(0o444)
    try:
        assert len(reserved_slots.receipts(home)) == 1
    finally:
        (home / DB).chmod(0o644)
    with pytest.raises(DataError, match="symlink"):
        (tmp_path / "linked").mkdir()
        (tmp_path / "linked" / "control").symlink_to(home / "control")
        reserved_slots.receipts(tmp_path / "linked")
