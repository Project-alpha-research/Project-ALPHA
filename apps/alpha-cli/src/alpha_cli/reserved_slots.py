"""The ten reserved-period slots: one insert-only receipt per confirmation, and its result.

The rows live in two tables of the home's SQLite file (`_SCHEMA`, opened through `home_db`, never
through the old control store). This module is their only writer. The rules are enforced in
code and by the table constraints: ten slots, taken in order; one receipt per test key, per rule
family on one asset and per run, ever. Each write runs in one `BEGIN IMMEDIATE` transaction,
so two processes cannot both take the last slot.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from alpha_cli import home_db
from alpha_cli.home_db import stamp as _stamp
from alpha_core import DataError

SLOTS: Final = 10
TABLES: Final = ("reserved_slot_receipts", "reserved_slot_results")
# Additive only: two insert-only tables, created here inside the write transaction, so a home of
# any age accepts them without a rebuild or a version change. No trigger; the rules are
# constraints: slots 1 to 10, one receipt per slot, per test key, per rule family on one asset
# and per run.
_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS reserved_slot_receipts (
    receipt_id TEXT PRIMARY KEY,
    slot INTEGER NOT NULL UNIQUE CHECK (slot BETWEEN 1 AND 10),
    test_key_sha256 TEXT NOT NULL UNIQUE CHECK (length(test_key_sha256) = 64),
    family_asset TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL UNIQUE,
    spec_sha256 TEXT NOT NULL CHECK (length(spec_sha256) = 64),
    frozen_json TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS reserved_slot_results (
    receipt_id TEXT PRIMARY KEY REFERENCES reserved_slot_receipts(receipt_id),
    confirmation_run_id TEXT NOT NULL UNIQUE,
    result_json TEXT NOT NULL,
    completed_at TEXT NOT NULL
) STRICT;
"""


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _write(data_dir: Path) -> AbstractContextManager[sqlite3.Connection]:
    return home_db.transaction(data_dir, _SCHEMA, TABLES, write=True)


@contextmanager
def _read(data_dir: Path) -> Iterator[sqlite3.Connection | None]:
    """A read snapshot, or None when no store or no slot table exists yet (nothing used)."""
    # The read-only seam: it never creates, migrates or writes (an `alpha test` reads here too).
    with home_db.read_only(data_dir) as connection:
        if connection is None:
            yield None
            return
        names = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        yield connection if set(TABLES) <= names else None


def take_slot(data_dir: Path, *, frozen: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """Spend one slot for one frozen test, before any reserved bar is read. Never twice."""
    with _write(data_dir) as connection:
        used = int(connection.execute("SELECT count(*) FROM reserved_slot_receipts").fetchone()[0])
        if used >= SLOTS:
            raise DataError(f"all {SLOTS} reserved-period slots are used; nothing was spent")
        for column, words in (
            ("test_key_sha256", "this exact test"),
            ("family_asset", "this rule family on this asset"),
            ("run_id", "this run"),
        ):
            if connection.execute(
                f"SELECT 1 FROM reserved_slot_receipts WHERE {column} = ?", (frozen[column],)
            ).fetchone():
                raise DataError(f"{words} was already confirmed once; it can never be again")
        row = {
            "receipt_id": str(uuid.uuid4()),
            "slot": used + 1,
            "test_key_sha256": str(frozen["test_key_sha256"]),
            "family_asset": str(frozen["family_asset"]),
            "run_id": str(frozen["run_id"]),
            "spec_sha256": str(frozen["spec_sha256"]),
            "frozen_json": canonical(dict(frozen)),
            "created_at": _stamp(now),
        }
        connection.execute(
            f"INSERT INTO reserved_slot_receipts ({', '.join(row)}) "
            f"VALUES ({', '.join('?' for _ in row)})",
            tuple(row.values()),
        )
    return _shape(row, None)


def record_result(
    data_dir: Path,
    *,
    receipt_id: str,
    confirmation_run_id: str,
    result: Mapping[str, Any],
    now: datetime,
) -> None:
    """Record the finished confirmation once; a resumed run that finds it changes nothing."""
    with _write(data_dir) as connection:
        connection.execute(
            """INSERT INTO reserved_slot_results
            (receipt_id, confirmation_run_id, result_json, completed_at) VALUES (?, ?, ?, ?)
            ON CONFLICT (receipt_id) DO NOTHING""",
            (receipt_id, confirmation_run_id, canonical(dict(result)), _stamp(now)),
        )


def _shape(row: Mapping[str, Any], result: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        **{key: row[key] for key in row if key != "frozen_json"},
        "frozen": json.loads(str(row["frozen_json"])),
        "result": None
        if result is None
        else {
            "confirmation_run_id": result["confirmation_run_id"],
            "completed_at": result["completed_at"],
            **json.loads(str(result["result_json"])),
        },
    }


def receipts(data_dir: Path) -> list[dict[str, Any]]:
    """Every slot receipt, in slot order, with its result when finished."""
    with _read(data_dir) as connection:
        if connection is None:
            return []
        rows = [
            dict(row)
            for row in connection.execute("SELECT * FROM reserved_slot_receipts ORDER BY slot")
        ]
        results = {
            str(row["receipt_id"]): dict(row)
            for row in connection.execute("SELECT * FROM reserved_slot_results")
        }
    return [_shape(row, results.get(str(row["receipt_id"]))) for row in rows]


def receipt(data_dir: Path, receipt_id: str) -> dict[str, Any]:
    """One stored receipt; refuses an id the store does not hold."""
    found = [item for item in receipts(data_dir) if item["receipt_id"] == receipt_id]
    if not found:
        raise DataError(f"no reserved-period receipt {receipt_id!r}")
    return found[0]


__all__ = [
    "SLOTS",
    "TABLES",
    "canonical",
    "receipt",
    "receipts",
    "record_result",
    "sha256",
    "take_slot",
]
