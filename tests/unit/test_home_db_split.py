"""The final check's slots and the durable jobs stand on `home_db`, off the old control store.

`old_home_store_v7.sqlite3.gz` is a synthetic store made by the code on main before the split
(the old `ControlStore` and the old slot writer): schema version 7, all old tables and triggers,
one spent slot with its result and one running job. The new path must read it and append to it
with no migration, and must not touch its version or its other tables.
"""

from __future__ import annotations

import gzip
import multiprocessing
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Barrier
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from alpha_cli import _control_json, control_store, home_db, reserved_slots
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
    assert (
        jobs.append_job_event(OLD_JOB, event_type="heartbeat", payload={"n": 2}, at=NOW)["sequence"]
        == 4
    )
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


_JSON = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats()
    | st.text(max_size=8)
    | st.binary(max_size=4),
    lambda inner: (
        st.lists(inner, max_size=4)
        | st.tuples(inner)
        | st.dictionaries(st.text(max_size=4) | st.integers(), inner, max_size=4)
    ),
    max_leaves=30,
)


def _outcome(function: Callable[..., object], *args: object) -> tuple[str, object]:
    try:
        return "ok", function(*args)
    except DataError as exc:
        return "error", str(exc)


@settings(max_examples=400, deadline=None)
@given(value=_JSON, text=st.text(max_size=12) | st.none() | st.integers())
def test_the_copied_codec_and_row_checks_match_the_old_ones(value: object, text: object) -> None:
    payload = {"p": value}
    old_json = _outcome(_control_json._json_object, payload, "job request")
    assert old_json == _outcome(home_db.json_object, payload, "job request")
    if old_json[0] == "ok":
        stored = _control_json._canonical_json(old_json[1], "job request")
        assert stored == home_db.canonical_json(old_json[1], "job request")
        old_decoded = _outcome(_control_json._decode_json, stored, "job request")
        assert old_decoded == _outcome(home_db.decode_json, stored, "job request")
    raw = text if isinstance(text, str) else value
    assert _outcome(_control_json._decode_json, raw, "x") == _outcome(home_db.decode_json, raw, "x")
    assert _outcome(control_store._required_text, raw, "f") == _outcome(
        home_db.required_text, raw, "f"
    )
    if isinstance(raw, str):
        for candidate in (raw, str(uuid.UUID(int=len(raw))), str(uuid.UUID(int=7)).upper()):
            assert _outcome(control_store._canonical_uuid, candidate, "id") == _outcome(
                home_db.canonical_uuid, candidate, "id"
            )
    if isinstance(value, int):
        assert _outcome(control_store._page, value, value) == _outcome(home_db.page, value, value)


def test_the_copied_timestamp_matches_the_old_one() -> None:
    for moment in (NOW, datetime(2026, 2, 1, 3, 4, 5, 6, tzinfo=timezone(timedelta(hours=-5)))):
        assert control_store._at(moment) == home_db.stamp(moment)
    for function in (control_store._at, home_db.stamp):
        with pytest.raises(DataError, match="timezone-aware"):
            function(datetime(2026, 2, 1))


def _race(home: str, n: int, barrier: Barrier, queue: Queue[str]) -> None:
    barrier.wait()
    try:
        reserved_slots.take_slot(Path(home), frozen=_frozen(n), now=NOW)
        queue.put("won")
    except DataError as exc:
        queue.put(str(exc))


def test_two_processes_racing_for_the_last_slot_spend_it_once(tmp_path: Path) -> None:
    for n in range(1, reserved_slots.SLOTS):
        reserved_slots.take_slot(tmp_path, frozen=_frozen(n), now=NOW)
    context = multiprocessing.get_context("spawn")
    barrier, queue = context.Barrier(2), context.Queue()
    racers = [
        context.Process(target=_race, args=(str(tmp_path), n, barrier, queue)) for n in (10, 11)
    ]
    for racer in racers:
        racer.start()
    for racer in racers:
        racer.join(60)
    outcomes = sorted(queue.get(timeout=5) for _ in racers)
    assert outcomes[1] == "won" and "all 10 reserved-period slots are used" in outcomes[0]
    assert [row["slot"] for row in reserved_slots.receipts(tmp_path)] == list(range(1, 11))


def test_the_old_store_first_then_the_new_path_keeps_the_version(tmp_path: Path) -> None:
    ControlStore(tmp_path).list_active_owner_credentials()
    before = _schema(tmp_path)
    assert before[0] == 7
    reserved_slots.take_slot(tmp_path, frozen=_frozen(1), now=NOW)
    JobStore(tmp_path).create_job(kind="ml:synthetic", request={}, at=NOW)
    slot_tables = [("table", name) for name in reserved_slots.TABLES]
    assert _schema(tmp_path) == (7, sorted(before[1] + slot_tables, key=lambda row: row[1]))
    with sqlite3.connect(tmp_path / DB) as connection:
        foreign = connection.execute("PRAGMA foreign_key_list(jobs)").fetchall()
    assert {row[2] for row in foreign} == {"projects", "experiment_specs"}


def test_a_home_with_only_slots_upgrades_under_the_old_store(tmp_path: Path) -> None:
    reserved_slots.take_slot(tmp_path, frozen=_frozen(1), now=NOW)
    ControlStore(tmp_path).list_active_owner_credentials()
    assert _schema(tmp_path)[0] == 7
    assert len(reserved_slots.receipts(tmp_path)) == 1
