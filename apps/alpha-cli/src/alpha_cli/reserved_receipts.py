"""Reading and checking the reserved-period slot rows: every read checks every row it returns.

The rows are insert-only by rule, but the control store is a file the same OS user can edit. So
no read trusts a row. The owner's Touch ID challenge is the SHA-256 of its binding (the action,
the frozen test's hash and the request), so the signature covers what the owner said yes to. A
read verifies, for every receipt: the owner's signature again, the binding behind it, the frozen
test against the signed hash, and the chain of slots (each receipt's hash names the one before).
A changed, removed-from-the-middle or re-pointed row makes every read refuse.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from alpha_cli.control_store import DATABASE_NAME, ControlStore
from alpha_cli.owner_auth import RESERVED_ACTION, check_assertion
from alpha_core import DataError

ACTION: Final = RESERVED_ACTION
SLOTS: Final = 10
TABLES: Final = (
    "reserved_period_authorizations",
    "reserved_period_receipts",
    "reserved_period_results",
)
# Fields of a frozen test derived from its hashed body (so they are checked, not trusted).
_DERIVED: Final = ("artifact_hash", "test_key_sha256", "family_asset")
_BROKEN: Final = "the reserved-period slot records were changed outside ALPHA"


def format_timestamp(value: datetime) -> str:
    """The control store's timestamp form (UTC, microseconds, `Z`)."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise DataError("control timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def binding_challenge(binding: Mapping[str, object]) -> bytes:
    """The Touch ID challenge of one binding: its hash, so the signature covers the binding."""
    return hashlib.sha256(canonical(dict(binding)).encode()).digest()


def family_asset(rule_kind: str, symbol: str) -> str:
    """The idea family on one asset: the unit that can be confirmed once (deflation family)."""
    return f"spine:{rule_kind}|{symbol}"


def check_frozen(frozen: Mapping[str, Any]) -> None:
    """A frozen test's derived fields must follow from its hashed body."""
    body = {key: value for key, value in frozen.items() if key not in _DERIVED}
    if (
        frozen.get("artifact_hash") != sha256(body)
        or frozen.get("test_key_sha256") != sha256(frozen.get("test_key"))
        or frozen.get("family_asset")
        != family_asset(str(frozen.get("rule")), str(frozen.get("symbol")))
    ):
        raise DataError(f"{_BROKEN}: a frozen test does not match its own hash")


@contextmanager
def read(data_dir: Path) -> Iterator[sqlite3.Connection | None]:
    """A read snapshot, or None when no store or no slot table exists yet (nothing used)."""
    if not (data_dir / "control" / DATABASE_NAME).is_file():
        yield None
        return
    # The read-only seam: it never migrates, heals or writes (an `alpha test` reads here too).
    with ControlStore(data_dir)._readonly_transaction() as connection:
        names = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        yield connection if set(TABLES) <= names else None


def reverify(connection: sqlite3.Connection, auth: Mapping[str, Any]) -> None:
    """Check one stored Touch ID yes again: its signature, its challenge and its binding."""
    found = connection.execute(
        """SELECT c.challenge, c.binding_json, k.public_key FROM owner_auth_challenges c
        JOIN owner_credentials k ON k.credential_id = ?
        WHERE c.challenge_id = ? AND c.verified_credential_id = ?""",
        (auth["credential_id"], auth["challenge_id"], auth["credential_id"]),
    ).fetchone()
    text = str(auth["assertion_json"])
    if found is None or hashlib.sha256(text.encode()).hexdigest() != auth["assertion_hash"]:
        raise DataError("the owner authorization for this slot does not check out")
    binding = json.loads(str(found["binding_json"]))
    payload = json.loads(str(auth["payload_json"]))
    if (
        not isinstance(binding, dict)
        or bytes(found["challenge"]) != binding_challenge(binding)
        or binding.get("action_type") != ACTION
        or binding.get("authorization_method") != "webauthn"
        or binding.get("artifact_hash") != auth["artifact_hash"]
        or binding.get("request_hash") != auth["request_hash"]
        or auth["request_hash"] != sha256(payload)
    ):
        raise DataError("the owner authorization for this slot does not check out")
    check_assertion(
        credential=json.loads(text),
        challenge=bytes(found["challenge"]),
        public_key=bytes(found["public_key"]),
        sign_count=int(auth["previous_sign_count"]),
    )


def receipt_hash(row: Mapping[str, Any], previous: str | None) -> str:
    """One receipt's hash: its own fields and the hash of the receipt before it (the chain)."""
    fields = (
        "receipt_id",
        "authorization_id",
        "slot",
        "previous_slot",
        "test_key_sha256",
        "family_asset",
        "run_id",
        "spec_sha256",
        "created_at",
    )
    return sha256(
        {
            **{name: row[name] for name in fields},
            "frozen": json.loads(row["frozen_json"]),
            "previous_receipt_sha256": previous,
        }
    )


def _check_receipt(
    connection: sqlite3.Connection, row: Mapping[str, Any], index: int, previous: str | None
) -> None:
    if (
        row["slot"] != index + 1
        or row["previous_slot"] != (index or None)
        or receipt_hash(row, previous) != row["receipt_sha256"]
    ):
        raise DataError(f"{_BROKEN}: slot {index + 1} is missing or changed (hash chain)")
    frozen = json.loads(str(row["frozen_json"]))
    check_frozen(frozen)
    if [row[k] for k in ("test_key_sha256", "family_asset", "run_id", "spec_sha256")] != [
        frozen[k] for k in ("test_key_sha256", "family_asset", "run_id", "spec_sha256")
    ]:
        raise DataError(f"{_BROKEN}: slot {index + 1} does not match its frozen test")
    auth = connection.execute(
        "SELECT * FROM reserved_period_authorizations WHERE authorization_id = ?",
        (row["authorization_id"],),
    ).fetchone()
    if auth is None or auth["artifact_hash"] != frozen["artifact_hash"]:
        raise DataError(f"{_BROKEN}: slot {index + 1} has no matching owner authorization")
    payload = json.loads(str(auth["payload_json"]))
    if payload.get("run_id") != frozen["run_id"]:
        raise DataError(f"{_BROKEN}: slot {index + 1} has no matching owner authorization")
    reverify(connection, auth)


def checked_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every receipt row in slot order, each one and the whole chain checked."""
    rows = [
        dict(row)
        for row in connection.execute("SELECT * FROM reserved_period_receipts ORDER BY slot")
    ]
    previous = None
    for index, row in enumerate(rows):
        _check_receipt(connection, row, index, previous)
        previous = str(row["receipt_sha256"])
    if len(rows) > SLOTS:
        raise DataError(f"{_BROKEN}: more than {SLOTS} slots")
    return rows


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
    """Every slot receipt, in slot order, all checked, with its result when finished."""
    with read(data_dir) as connection:
        if connection is None:
            return []
        rows = checked_rows(connection)
        results = {
            str(row["receipt_id"]): dict(row)
            for row in connection.execute("SELECT * FROM reserved_period_results")
        }
    known = {str(row["receipt_id"]) for row in rows}
    if set(results) - known:
        raise DataError(f"{_BROKEN}: a result has no receipt")
    return [_shape(row, results.get(str(row["receipt_id"]))) for row in rows]


def verified_receipt(data_dir: Path, receipt_id: str) -> dict[str, Any]:
    """One receipt, with the whole chain and its owner's assertion checked again, on every call."""
    found = [item for item in receipts(data_dir) if item["receipt_id"] == receipt_id]
    if not found:
        raise DataError(f"no valid reserved-period receipt {receipt_id!r}")
    return found[0]


def authorization_payload(data_dir: Path, authorization_id: str) -> dict[str, Any]:
    """What the owner said yes to (the run, the reserved span and the words they read)."""
    with read(data_dir) as connection:
        found = None
        if connection is not None:
            found = connection.execute(
                "SELECT * FROM reserved_period_authorizations WHERE authorization_id = ?",
                (authorization_id,),
            ).fetchone()
            if found is not None:
                reverify(connection, found)
    if found is None:
        raise DataError("no owner authorization with this id; ask for a new one")
    payload: dict[str, Any] = json.loads(str(found["payload_json"]))
    return payload


__all__ = [
    "ACTION",
    "SLOTS",
    "TABLES",
    "authorization_payload",
    "binding_challenge",
    "canonical",
    "check_frozen",
    "checked_rows",
    "family_asset",
    "format_timestamp",
    "read",
    "receipt_hash",
    "receipts",
    "reverify",
    "sha256",
    "verified_receipt",
]
