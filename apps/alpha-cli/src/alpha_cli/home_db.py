"""The data home's SQLite file, opened for the kept features: the final check's slots and jobs.

`data_dir/control/workstation.sqlite3` also holds the old research-case tables, but this module
never reads, migrates or versions them: it opens the same file, creates only the tables its caller
declares (`CREATE TABLE IF NOT EXISTS`) and leaves `user_version` alone. So a home made by the old
control store keeps working with no migration, and a fresh home gets only the kept tables.

The row checks and the JSON codec below repeat the old store's rules and messages word for word;
the old copies go when the old store is deleted.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from alpha_core import DataError

DATABASE_NAME: Final = "workstation.sqlite3"
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_MAX_TEXT = 8_192
_MAX_JSON_BYTES = 65_536


def database_path(data_dir: Path) -> Path:
    """The real database path; refuses symlinks. Creates the `control/` folder."""
    root = Path(data_dir) / "control"
    if root.is_symlink():
        raise DataError(f"control store root must not be a symlink: {root}")
    root.mkdir(parents=True, exist_ok=True)
    database = root / DATABASE_NAME
    if database.is_symlink():
        raise DataError(f"control store database must not be a symlink: {database}")
    if database.exists() and not database.is_file():
        raise DataError(f"control store database is not a file: {database}")
    return database


def _enable_wal(connection: sqlite3.Connection) -> None:
    """Retry journal negotiation (a database-wide write) within the SQLite busy budget."""
    budget_ms = int(connection.execute("PRAGMA busy_timeout").fetchone()[0])
    deadline = time.monotonic() + budget_ms / 1000
    try:
        while True:
            connection.execute(
                f"PRAGMA busy_timeout = {max(0, int((deadline - time.monotonic()) * 1000))}"
            )
            try:
                connection.execute("PRAGMA journal_mode = WAL")
                return
            except sqlite3.OperationalError as exc:
                remaining = deadline - time.monotonic()
                if exc.sqlite_errorcode != sqlite3.SQLITE_BUSY or remaining <= 0:
                    raise
                time.sleep(min(0.01, remaining))
    finally:
        connection.execute(f"PRAGMA busy_timeout = {budget_ms}")


def _missing(connection: sqlite3.Connection, tables: Sequence[str]) -> bool:
    found = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master")}
    return not set(tables) <= found


@contextmanager
def transaction(
    data_dir: Path, ddl: str, tables: Sequence[str], *, write: bool
) -> Iterator[sqlite3.Connection]:
    """One transaction on the home's file; first creates the declared tables if any is missing."""
    try:
        connection = sqlite3.connect(database_path(data_dir), timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        for pragma in ("foreign_keys = ON", "busy_timeout = 5000", "synchronous = FULL"):
            connection.execute(f"PRAGMA {pragma}")
        _enable_wal(connection)
    except (OSError, sqlite3.Error) as exc:
        raise DataError("cannot initialize control store") from exc
    try:
        if _missing(connection, tables):
            connection.execute("BEGIN IMMEDIATE")
            pending = ""
            for line in ddl.splitlines(keepends=True):
                pending += line
                if sqlite3.complete_statement(pending):
                    connection.execute(pending)
                    pending = ""
            connection.commit()
        connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield connection
        connection.commit()
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.rollback()
        raise DataError("control store transaction failed") from exc
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


@contextmanager
def read_only(data_dir: Path) -> Iterator[sqlite3.Connection | None]:
    """A read snapshot that never creates, migrates or writes; None when there is no file yet."""
    database = Path(data_dir) / "control" / DATABASE_NAME
    if database.is_symlink() or database.parent.is_symlink():
        raise DataError(f"control store database must not be a symlink: {database}")
    if not database.is_file():
        yield None
        return
    try:
        uri = f"{database.resolve(strict=True).as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
    except (OSError, sqlite3.Error) as exc:
        raise DataError("cannot read control store without changing it") from exc
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        yield connection
    except sqlite3.Error as exc:
        raise DataError("control store read-only transaction failed") from exc
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def required_text(value: object, field: str, *, max_length: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise DataError(f"invalid control {field}: expected a string")
    clean = value.strip()
    if not clean or "\x00" in clean or len(clean) > max_length:
        raise DataError(f"invalid control {field}: expected 1..{max_length} safe characters")
    return clean


def optional_text(value: str | None, field: str) -> str | None:
    return None if value is None else required_text(value, field)


def canonical_uuid(value: str, field: str) -> str:
    try:
        parsed = str(uuid.UUID(value)) if _UUID_RE.fullmatch(value) else None
    except ValueError:
        parsed = None
    if parsed != value:
        raise DataError(f"invalid control {field}: expected a canonical UUID")
    return value


def new_uuid(value: str | None, field: str) -> str:
    return str(uuid.uuid4()) if value is None else canonical_uuid(value, field)


def stamp(value: datetime | None = None) -> str:
    """The store's timestamp form (UTC, microseconds, `Z`); now when no time is given."""
    value = datetime.now(UTC) if value is None else value
    if value.tzinfo is None or value.utcoffset() is None:
        raise DataError("control timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def page(limit: int, offset: int) -> tuple[int, int]:
    if isinstance(limit, bool) or not 1 <= limit <= 500:
        raise DataError("control query limit must be in 1..500")
    if isinstance(offset, bool) or offset < 0:
        raise DataError("control query offset must be non-negative")
    return limit, offset


def _clean_json(value: object, *, label: str, depth: int = 0) -> object:
    if depth > 16:
        raise DataError(f"invalid control {label}: JSON nesting exceeds 16 levels")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, Mapping):
        clean: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or "\x00" in key:
                raise DataError(f"invalid control {label}: JSON keys must be non-empty strings")
            clean[key] = _clean_json(item, label=label, depth=depth + 1)
        return clean
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_clean_json(item, label=label, depth=depth + 1) for item in value]
    raise DataError(f"invalid control {label}: expected finite JSON values")


def canonical_json(value: object, label: str) -> str:
    try:
        result = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise DataError(f"invalid control {label}: expected finite JSON values") from exc
    if len(result.encode("utf-8")) > _MAX_JSON_BYTES:
        raise DataError(f"invalid control {label}: JSON exceeds {_MAX_JSON_BYTES} bytes")
    return result


def json_object(value: Mapping[str, object], label: str) -> dict[str, object]:
    clean = _clean_json(value, label=label)
    if not isinstance(clean, dict):
        raise DataError(f"invalid control {label}: expected a JSON object")
    canonical_json(clean, label)
    return clean


def decode_json(value: object, label: str) -> object:
    if not isinstance(value, str):
        raise DataError(f"corrupt control store: {label} is not text")
    try:
        result: object = json.loads(value)
    except json.JSONDecodeError as exc:
        raise DataError(f"corrupt control store: invalid {label}") from exc
    return _clean_json(result, label=label)
