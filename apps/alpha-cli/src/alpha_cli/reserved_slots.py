"""The ten reserved-period slots: owner authorizations, slot receipts and results.

The rows live in the control store beside the owner action receipts, in three append-only tables
(`_SCHEMA_RESERVED_CONFIRMATION`). This module is their only writer. It is not an owner-authority
route: an authorization row is written only by `owner_auth` after it has verified a WebAuthn
(Touch ID) assertion for the challenge, and a slot receipt only from such an authorization.

The rules are enforced twice, in code and by the store: WebAuthn only; one receipt per
authorization; one receipt per test key and per rule family on one asset, ever; ten slots, taken
in order, for the life of the reserved window. Every write runs in one `BEGIN IMMEDIATE`
transaction, so two processes cannot both take the last slot. Each write checks the rows it
builds on, and every read checks every row (`reserved_receipts`): the store file is not trusted.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

from alpha_cli._control_schema import _SCHEMA_RESERVED_CONFIRMATION
from alpha_cli.control_store import ControlStore
from alpha_cli.reserved_receipts import (
    ACTION,
    SLOTS,
    authorization_payload,
    binding_challenge,
    canonical,
    check_frozen,
    checked_rows,
    receipt_hash,
    receipts,
    reverify,
    sha256,
    verified_receipt,
)
from alpha_cli.reserved_receipts import format_timestamp as _format_timestamp
from alpha_core import DataError

# The owner's yes is used at once by the Workstation; an older unused yes is not a yes for today.
AUTHORIZATION_LIFETIME: Final = timedelta(minutes=30)


def _create_tables(connection: sqlite3.Connection) -> None:
    """Run the static DDL statement by statement, inside the caller's transaction."""
    pending = ""
    for line in _SCHEMA_RESERVED_CONFIRMATION.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            connection.execute(pending)
            pending = ""


@contextmanager
def _write(data_dir: Path) -> Iterator[sqlite3.Connection]:
    with ControlStore(data_dir)._transaction(write=True) as connection:
        _create_tables(connection)
        yield connection


def record_authorization(
    data_dir: Path,
    *,
    challenge_id: str,
    credential: Mapping[str, object],
    payload: Mapping[str, object],
    now: datetime,
) -> dict[str, Any]:
    """Verify one Touch ID assertion for this action and record it, once, in one transaction.

    The signature is checked here, inside the write, so no caller can record a yes without it.
    """
    from alpha_cli.owner_auth import check_assertion

    credential_id = credential.get("id")
    if not isinstance(credential_id, str) or not credential_id:
        raise DataError("owner WebAuthn credential id is missing")
    stamp = _format_timestamp(now)
    assertion_json = canonical(dict(credential))
    with _write(data_dir) as connection:
        challenge = connection.execute(
            "SELECT * FROM owner_auth_challenges WHERE challenge_id = ?", (challenge_id,)
        ).fetchone()
        if (
            challenge is None
            or challenge["ceremony"] != "action"
            or challenge["used_at"] is not None
            or str(challenge["expires_at"]) <= stamp
        ):
            raise DataError("owner action assertion is invalid, expired, stale, or already used")
        binding = json.loads(str(challenge["binding_json"]))
        if (
            not isinstance(binding, dict)
            or binding.get("action_type") != ACTION
            or binding.get("authorization_method") != "webauthn"
            or binding.get("request_hash") != sha256(dict(payload))
            or bytes(challenge["challenge"]) != binding_challenge(binding)
        ):
            raise DataError("this challenge is not a Touch ID reserved-period confirmation")
        stored = connection.execute(
            "SELECT * FROM owner_credentials WHERE credential_id = ?", (credential_id,)
        ).fetchone()
        if stored is None or stored["revoked_at"] is not None:
            raise DataError("Touch ID credential is not enrolled or has been revoked")
        previous_sign_count = int(stored["sign_count"])
        new_sign_count = check_assertion(
            credential=credential,
            challenge=bytes(challenge["challenge"]),
            public_key=bytes(stored["public_key"]),
            sign_count=previous_sign_count,
        )
        if new_sign_count <= previous_sign_count:
            raise DataError("owner credential signature counter regressed")
        connection.execute(
            "UPDATE owner_credentials SET sign_count = ? WHERE credential_id = ?",
            (new_sign_count, credential_id),
        )
        connection.execute(
            """UPDATE owner_auth_challenges
            SET used_at = ?, verified_credential_id = ? WHERE challenge_id = ?""",
            (stamp, credential_id, challenge_id),
        )
        row = {
            "authorization_id": str(uuid.uuid4()),
            "challenge_id": challenge_id,
            "credential_id": credential_id,
            "actor": str(stored["actor"]),
            "action_type": ACTION,
            "authorization_method": "webauthn",
            "artifact_hash": str(binding["artifact_hash"]),
            "request_hash": str(binding["request_hash"]),
            "payload_json": canonical(dict(payload)),
            "consequence_summary": str(binding["consequence_summary"]),
            "reason": str(binding["reason"]),
            "assertion_json": assertion_json,
            "assertion_hash": hashlib.sha256(assertion_json.encode()).hexdigest(),
            "previous_sign_count": previous_sign_count,
            "authorized_at": stamp,
        }
        names = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        connection.execute(
            f"INSERT INTO reserved_period_authorizations ({names}) VALUES ({marks})",
            tuple(row.values()),
        )
    return {key: row[key] for key in ("authorization_id", "actor", "authorized_at")}


def take_slot(
    data_dir: Path,
    *,
    authorization_id: str,
    frozen: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Spend one slot for one frozen test, before any reserved bar is read. Never twice."""
    stamp = _format_timestamp(now)
    with _write(data_dir) as connection:
        auth = connection.execute(
            "SELECT * FROM reserved_period_authorizations WHERE authorization_id = ?",
            (authorization_id,),
        ).fetchone()
        if auth is None:
            raise DataError("no owner authorization with this id; ask for a new one")
        reverify(connection, auth)
        check_frozen(frozen)
        spent = checked_rows(connection)
        if connection.execute(
            "SELECT 1 FROM reserved_period_receipts WHERE authorization_id = ?",
            (authorization_id,),
        ).fetchone():
            raise DataError("this owner authorization was already used for a slot")
        if str(auth["authorized_at"]) <= _format_timestamp(now - AUTHORIZATION_LIFETIME):
            raise DataError("this owner authorization is older than 30 minutes; ask again")
        if auth["artifact_hash"] != frozen["artifact_hash"]:
            raise DataError("the test changed after the owner confirmed it; nothing was spent")
        if json.loads(str(auth["payload_json"])).get("run_id") != frozen["run_id"]:
            raise DataError("the owner confirmed another run; nothing was spent")
        used = len(spent)
        if used >= SLOTS:
            raise DataError(f"all {SLOTS} reserved-period slots are used; nothing was spent")
        for column, value, words in (
            ("test_key_sha256", frozen["test_key_sha256"], "this exact test"),
            ("family_asset", frozen["family_asset"], "this rule family on this asset"),
            ("run_id", frozen["run_id"], "this run"),
        ):
            if connection.execute(
                f"SELECT 1 FROM reserved_period_receipts WHERE {column} = ?", (value,)
            ).fetchone():
                raise DataError(f"{words} was already confirmed once; it can never be again")
        row = {
            "receipt_id": str(uuid.uuid4()),
            "authorization_id": authorization_id,
            "slot": used + 1,
            "previous_slot": used or None,
            "test_key_sha256": str(frozen["test_key_sha256"]),
            "family_asset": str(frozen["family_asset"]),
            "run_id": str(frozen["run_id"]),
            "spec_sha256": str(frozen["spec_sha256"]),
            "frozen_json": canonical(dict(frozen)),
            "created_at": stamp,
        }
        row["receipt_sha256"] = receipt_hash(row, spent[-1]["receipt_sha256"] if spent else None)
        connection.execute(
            f"INSERT INTO reserved_period_receipts ({', '.join(row)}) "
            f"VALUES ({', '.join('?' for _ in row)})",
            tuple(row.values()),
        )
    shown = {key: value for key, value in row.items() if key != "frozen_json"}
    return {**shown, "frozen": dict(frozen), "result": None}


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
        if receipt_id not in {str(row["receipt_id"]) for row in checked_rows(connection)}:
            raise DataError(f"no valid reserved-period receipt {receipt_id!r}")
        if connection.execute(
            "SELECT 1 FROM reserved_period_results WHERE receipt_id = ?", (receipt_id,)
        ).fetchone():
            return
        connection.execute(
            """INSERT INTO reserved_period_results
            (receipt_id, confirmation_run_id, result_json, completed_at) VALUES (?, ?, ?, ?)""",
            (receipt_id, confirmation_run_id, canonical(dict(result)), _format_timestamp(now)),
        )


__all__ = [
    "ACTION",
    "AUTHORIZATION_LIFETIME",
    "SLOTS",
    "authorization_payload",
    "binding_challenge",
    "canonical",
    "receipts",
    "record_authorization",
    "record_result",
    "sha256",
    "take_slot",
    "verified_receipt",
]
