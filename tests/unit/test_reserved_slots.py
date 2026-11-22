"""The ten reserved-period slots: plain insert-only receipts, in order, once each, race-safe.

Every test uses a temporary data home; no real slot is used.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from alpha_cli import reserved_slots
from alpha_cli.control_store import ControlStore
from alpha_core import DataError

DB = Path("control") / "workstation.sqlite3"


def _frozen(n: int, *, rule: str | None = None, key: int | None = None) -> dict[str, Any]:
    """A frozen test record, shaped as `Frozen.record` makes it."""
    rule = rule or f"rule{n}"
    return {
        "run_id": f"run{n:013d}",
        "rule": rule,
        "symbol": "SPY",
        "spec_sha256": "a" * 64,
        "artifact_hash": reserved_slots.sha256(["artifact", n]),
        "test_key_sha256": reserved_slots.sha256(["key", n if key is None else key]),
        "family_asset": f"spine:{rule}|SPY",
        "reserved_end": "2024-05-19T00:00:00+00:00",
    }


def _take(home: Path, frozen: dict[str, Any]) -> dict[str, Any]:
    return reserved_slots.take_slot(home, frozen=frozen, now=datetime.now(UTC))


def test_ten_slots_in_order_then_refused(tmp_path: Path) -> None:
    for n in range(1, 11):
        assert _take(tmp_path, _frozen(n))["slot"] == n
    with pytest.raises(DataError, match="all 10 reserved-period slots are used"):
        _take(tmp_path, _frozen(11))
    assert [r["slot"] for r in reserved_slots.receipts(tmp_path)] == list(range(1, 11))


def test_one_test_key_one_family_one_run(tmp_path: Path) -> None:
    _take(tmp_path, _frozen(1))
    same_run = {**_frozen(2), "run_id": _frozen(1)["run_id"]}
    for frozen, words in (
        (_frozen(2, key=1), "this exact test"),
        (_frozen(3, rule="rule1"), "this rule family on this asset"),
        (same_run, "this run"),
    ):
        with pytest.raises(DataError, match=words):
            _take(tmp_path, frozen)
    assert len(reserved_slots.receipts(tmp_path)) == 1


def test_the_store_itself_refuses_a_duplicate_or_an_eleventh_slot(tmp_path: Path) -> None:
    _take(tmp_path, _frozen(1))
    insert = """INSERT INTO reserved_slot_receipts (receipt_id, slot, test_key_sha256,
        family_asset, run_id, spec_sha256, frozen_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, '{}', 'now')"""
    first = _frozen(1)
    with sqlite3.connect(tmp_path / DB) as connection:
        for slot, key, family, run in (
            (11, "b" * 64, "f", "x"),
            (1, "b" * 64, "f", "x"),
            (2, first["test_key_sha256"], "f", "x"),
            (2, "b" * 64, first["family_asset"], "x"),
            (2, "b" * 64, "f", first["run_id"]),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(insert, ("r", slot, key, family, run, "a" * 64))


def test_two_processes_cannot_both_take_the_last_slot(tmp_path: Path) -> None:
    for n in range(1, 10):
        _take(tmp_path, _frozen(n))
    contenders = [_frozen(10), _frozen(11)]
    gate = threading.Barrier(2)
    outcomes: list[str] = []

    def race(index: int) -> None:
        gate.wait()
        try:
            _take(tmp_path, contenders[index])
            outcomes.append("took")
        except DataError as exc:
            outcomes.append(str(exc))

    threads = [threading.Thread(target=race, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("took") == 1, outcomes
    assert len(reserved_slots.receipts(tmp_path)) == 10


def test_a_result_is_recorded_once_and_read_back(tmp_path: Path) -> None:
    receipt = _take(tmp_path, _frozen(1))
    assert receipt["result"] is None and receipt["frozen"] == _frozen(1)
    for value in (1.5, 9.9):
        reserved_slots.record_result(
            tmp_path,
            receipt_id=receipt["receipt_id"],
            confirmation_run_id="c1",
            result={"reserved": {"oos_sharpe": value}},
            now=datetime.now(UTC),
        )
    found = reserved_slots.receipt(tmp_path, receipt["receipt_id"])
    assert found["result"]["reserved"] == {"oos_sharpe": 1.5}
    assert found["result"]["confirmation_run_id"] == "c1"
    with pytest.raises(DataError, match="no reserved-period receipt"):
        reserved_slots.receipt(tmp_path, "missing")


def test_an_old_store_without_the_tables_reads_as_no_slot_used(tmp_path: Path) -> None:
    assert reserved_slots.receipts(tmp_path) == []
    assert not (tmp_path / "control").exists()
    ControlStore(tmp_path).list_active_owner_credentials()
    assert reserved_slots.receipts(tmp_path) == []


def test_the_slot_code_needs_no_owner_auth() -> None:
    root = Path(__file__).resolve().parents[2] / "apps/alpha-cli/src/alpha_cli"
    for rel in ("reserved_slots.py", "confirm_cmds.py", "spine/confirm.py", "spine/confirm_run.py"):
        assert "owner_auth" not in (root / rel).read_text(encoding="utf-8"), rel
    assert not (root / "reserved_receipts.py").exists()
