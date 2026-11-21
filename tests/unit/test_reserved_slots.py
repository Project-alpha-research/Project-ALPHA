"""The ten reserved-period slots: owner yes, one-shot receipts, order, races and refusals.

Every test uses a temporary data home and the Touch ID test double; no real slot is used.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from alpha_cli import owner_auth, reserved_receipts, reserved_slots
from alpha_cli.control_store import ControlStore
from alpha_core import DataError
from alpha_web.api.owner_auth import OwnerActionChallengeRequest
from tests.fixtures.reserved_owner import (
    CREDENTIAL,
    challenge,
    enroll,
    install_double,
    owner_yes,
)

DB = Path("control") / "workstation.sqlite3"


def _frozen(n: int, *, rule: str | None = None, key: int | None = None) -> dict[str, Any]:
    """A frozen test whose derived fields follow from its body, as `Frozen.record` makes them."""
    body = {
        "run_id": f"run{n:013d}",
        "rule": rule or f"rule{n}",
        "symbol": "SPY",
        "test_key": ["key", n if key is None else key],
        "spec_sha256": "a" * 64,
        "reserved_end": "2024-05-19T00:00:00+00:00",
    }
    return {
        **body,
        "artifact_hash": reserved_slots.sha256(body),
        "test_key_sha256": reserved_slots.sha256(body["test_key"]),
        "family_asset": f"spine:{body['rule']}|SPY",
    }


def _yes(home: Path, frozen: dict[str, Any]) -> str:
    payload = {"run_id": frozen["run_id"], "reserved_end": frozen["reserved_end"]}
    return owner_yes(home, payload, frozen["artifact_hash"])


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    install_double(monkeypatch)
    enroll(tmp_path)
    return tmp_path


def _take(home: Path, frozen: dict[str, Any], **kw: Any) -> dict[str, Any]:
    now = kw.pop("now", datetime.now(UTC))
    return reserved_slots.take_slot(
        home, authorization_id=_yes(home, frozen), frozen=frozen, now=now, **kw
    )


def test_ten_slots_in_order_then_refused(home: Path) -> None:
    for n in range(1, 11):
        assert _take(home, _frozen(n))["slot"] == n
    with pytest.raises(DataError, match="all 10 reserved-period slots are used"):
        _take(home, _frozen(11))
    assert [r["slot"] for r in reserved_slots.receipts(home)] == list(range(1, 11))


def test_the_store_itself_refuses_an_eleventh_or_out_of_order_slot(home: Path) -> None:
    first = _take(home, _frozen(1))
    second = _yes(home, _frozen(2))
    insert = """INSERT INTO reserved_period_receipts (receipt_id, authorization_id, slot,
        previous_slot, test_key_sha256, family_asset, run_id, spec_sha256, frozen_json,
        receipt_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, 'now')"""
    with sqlite3.connect(home / DB) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for slot, previous, auth in (
            (11, 10, second),
            (3, 2, second),
            (3, None, second),
            (2, 1, first["authorization_id"]),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    insert,
                    ("r", auth, slot, previous, "b" * 64, "f", "x", "a" * 64, "c" * 64),
                )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM reserved_period_authorizations")


def test_a_changed_receipt_is_refused_on_read(home: Path) -> None:
    _take(home, _frozen(1))
    with sqlite3.connect(home / DB) as connection:
        connection.execute("UPDATE reserved_period_receipts SET created_at = 'later'")
    with pytest.raises(DataError, match="hash chain"):
        reserved_slots.receipts(home)


def test_one_test_key_one_family_one_run_one_authorization(home: Path) -> None:
    first = _frozen(1)
    receipt = _take(home, first)
    same_key = _frozen(2, key=1)
    same_family = _frozen(3, rule="rule1")
    for frozen, words in ((same_key, "this exact test"), (same_family, "this rule family")):
        with pytest.raises(DataError, match=words):
            _take(home, frozen)
    with pytest.raises(DataError, match="already used for a slot"):
        reserved_slots.take_slot(
            home,
            authorization_id=receipt["authorization_id"],
            frozen=_frozen(4),
            now=datetime.now(UTC),
        )
    assert len(reserved_slots.receipts(home)) == 1


def test_a_yes_binds_one_test_and_expires(home: Path) -> None:
    frozen = _frozen(1)
    auth = _yes(home, frozen)
    changed = _frozen(1, rule="other")
    with pytest.raises(DataError, match="test changed after the owner confirmed"):
        reserved_slots.take_slot(home, authorization_id=auth, frozen=changed, now=datetime.now(UTC))
    late = datetime.now(UTC) + reserved_slots.AUTHORIZATION_LIFETIME + timedelta(seconds=1)
    with pytest.raises(DataError, match="older than 30 minutes"):
        reserved_slots.take_slot(home, authorization_id=auth, frozen=frozen, now=late)
    assert reserved_slots.receipts(home) == []


def test_two_processes_cannot_both_take_the_last_slot(home: Path) -> None:
    for n in range(1, 10):
        _take(home, _frozen(n))
    contenders = [_frozen(10), _frozen(11)]
    yeses = [_yes(home, frozen) for frozen in contenders]
    gate = threading.Barrier(2)
    outcomes: list[str] = []

    def race(index: int) -> None:
        gate.wait()
        try:
            reserved_slots.take_slot(
                home, authorization_id=yeses[index], frozen=contenders[index], now=datetime.now(UTC)
            )
            outcomes.append("took")
        except DataError as exc:
            outcomes.append(str(exc))

    threads = [threading.Thread(target=race, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes)[-1] == "took" and outcomes.count("took") == 1, outcomes
    assert len(reserved_slots.receipts(home)) == 10


def test_a_bad_signature_records_nothing_and_a_forged_row_takes_no_slot(home: Path) -> None:
    frozen = _frozen(1)
    payload = {"run_id": frozen["run_id"], "reserved_end": frozen["reserved_end"]}
    challenge_id, _ = challenge(home, payload, frozen["artifact_hash"])
    with pytest.raises(DataError, match="could not be verified"):
        owner_auth.verify_action_assertion(
            data_dir=home,
            challenge_id=challenge_id,
            credential={"id": CREDENTIAL, "response": {"signature": "0" * 64}},
            payload=payload,
        )
    good = _yes(home, _frozen(2))
    with sqlite3.connect(home / DB) as connection:
        connection.execute(
            "UPDATE reserved_period_authorizations SET assertion_json = ?, assertion_hash = ?",
            ('{"forged":1}', reserved_slots.sha256({"forged": 1})),
        )
    with pytest.raises(DataError, match="does not check out|could not be verified"):
        reserved_slots.take_slot(
            home, authorization_id=good, frozen=_frozen(2), now=datetime.now(UTC)
        )
    assert reserved_slots.receipts(home) == []


def test_payload_must_match_the_challenge(home: Path) -> None:
    frozen = _frozen(1)
    payload = {"run_id": frozen["run_id"], "reserved_end": frozen["reserved_end"]}
    challenge_id, _ = challenge(home, payload, frozen["artifact_hash"])
    with pytest.raises(DataError, match="not a Touch ID reserved-period confirmation"):
        owner_auth.verify_action_assertion(
            data_dir=home,
            challenge_id=challenge_id,
            credential={"id": CREDENTIAL, "response": {"signature": "x"}},
            payload={**payload, "run_id": "other"},
        )


def test_no_local_click_no_web_route_no_research_receipt_can_give_the_yes(home: Path) -> None:
    binding = {"action_type": owner_auth.RESERVED_ACTION, "run_id": "r"}
    with pytest.raises(DataError, match="needs Touch ID"):
        owner_auth.local_confirmation_options(data_dir=home, binding=binding)
    with pytest.raises(DataError, match="unsupported owner action type"):
        owner_auth.action_binding(
            data_dir=home,
            action_type=owner_auth.RESERVED_ACTION,
            project_id="p",
            artifact_hash="a" * 64,
            expected_case_revision="b" * 64,
            consequence_summary="x",
            reason="x",
            payload={},
        )
    with pytest.raises(DataError, match="unsupported owner action type"):
        owner_auth.derive_action_artifact_hash(
            data_dir=home, action_type=owner_auth.RESERVED_ACTION, project_id="p", payload={}
        )
    with pytest.raises(ValueError, match="action_type"):
        OwnerActionChallengeRequest.model_validate(
            {
                "action_type": owner_auth.RESERVED_ACTION,
                "project_id": "p",
                "artifact_hash": "a" * 64,
                "expected_case_revision": "b" * 64,
                "consequence_summary": "x",
                "reason": "x",
                "payload": {},
            }
        )
    assert owner_auth.RESERVED_ACTION not in owner_auth.OWNER_ACTION_TYPES
    # A local-click challenge with this type, if one were written, is refused on use.
    now = datetime.now(UTC)
    made = ControlStore(home).create_owner_auth_challenge(
        ceremony="action",
        challenge=b"l" * 32,
        binding={**binding, "authorization_method": "local_confirmation"},
        now=now,
        expires_at=now + timedelta(seconds=60),
    )
    with pytest.raises(DataError, match="needs Touch ID"):
        owner_auth.verify_local_confirmation(
            data_dir=home,
            challenge_id=str(made["challenge_id"]),
            confirmation_token=(b"l" * 32).hex(),
            payload={},
        )


def test_an_old_store_without_the_tables_reads_as_no_slot_used(tmp_path: Path) -> None:
    assert reserved_slots.receipts(tmp_path) == []
    assert not (tmp_path / "control").exists()
    ControlStore(tmp_path).list_active_owner_credentials()
    assert reserved_slots.receipts(tmp_path) == []


def _sql(home: Path, *statements: tuple[str, tuple[Any, ...]]) -> None:
    """Direct edits by another process as the same OS user (no foreign keys, no ALPHA code)."""
    with sqlite3.connect(home / DB) as connection:
        for sql, args in statements:
            connection.execute(sql, args)


def test_an_owner_yes_cannot_be_re_pointed_to_another_test_in_sqlite(home: Path) -> None:
    """The owner says yes to A; editing every stored row to B fails: the signature covers A."""
    said_yes, wanted = _frozen(1), _frozen(2)
    auth = _yes(home, said_yes)
    payload = {"run_id": wanted["run_id"], "reserved_end": wanted["reserved_end"]}
    with sqlite3.connect(home / DB) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT challenge_id FROM reserved_period_authorizations WHERE authorization_id = ?",
            (auth,),
        ).fetchone()
        found = connection.execute(
            "SELECT binding_json FROM owner_auth_challenges WHERE challenge_id = ?",
            (row["challenge_id"],),
        ).fetchone()
    binding = {
        **json.loads(found["binding_json"]),
        "artifact_hash": wanted["artifact_hash"],
        "request_hash": reserved_slots.sha256(payload),
        "run_id": wanted["run_id"],
    }
    _sql(
        home,
        (
            "UPDATE owner_auth_challenges SET binding_json = ? WHERE challenge_id = ?",
            (reserved_slots.canonical(binding), row["challenge_id"]),
        ),
        (
            """UPDATE reserved_period_authorizations SET artifact_hash = ?, request_hash = ?,
            payload_json = ? WHERE authorization_id = ?""",
            (
                wanted["artifact_hash"],
                reserved_slots.sha256(payload),
                reserved_slots.canonical(payload),
                auth,
            ),
        ),
    )
    with pytest.raises(DataError, match="does not check out"):
        reserved_slots.take_slot(home, authorization_id=auth, frozen=wanted, now=datetime.now(UTC))
    assert reserved_slots.receipts(home) == []


def test_a_payload_edited_after_the_yes_is_refused(home: Path) -> None:
    frozen = _frozen(1)
    auth = _yes(home, frozen)
    edited = {"run_id": frozen["run_id"], "reserved_end": "2026-01-01T00:00:00+00:00"}
    _sql(
        home,
        (
            "UPDATE reserved_period_authorizations SET payload_json = ?",
            (reserved_slots.canonical(edited),),
        ),
    )
    with pytest.raises(DataError, match="does not check out"):
        reserved_slots.authorization_payload(home, auth)


def test_a_receipt_removed_from_the_middle_makes_every_read_refuse(home: Path) -> None:
    for n in (1, 2, 3):
        _take(home, _frozen(n))
    _sql(home, ("DELETE FROM reserved_period_receipts WHERE slot = 2", ()))
    with pytest.raises(DataError, match="hash chain"):
        reserved_slots.receipts(home)
    with pytest.raises(DataError, match="hash chain"):
        _take(home, _frozen(4))


def test_a_re_pointed_receipt_with_fresh_hashes_is_refused(home: Path) -> None:
    """Free a family by editing the receipt and its hashes: the signed yes still names it."""
    _take(home, _frozen(1))
    other = _frozen(1, rule="freed")
    with sqlite3.connect(home / DB) as connection:
        connection.row_factory = sqlite3.Row
        row = dict(connection.execute("SELECT * FROM reserved_period_receipts").fetchone())
    row.update(family_asset=other["family_asset"], frozen_json=reserved_slots.canonical(other))
    fresh = reserved_receipts.receipt_hash(row, None)
    _sql(
        home,
        (
            "UPDATE reserved_period_receipts SET family_asset = ?, frozen_json = ?, "
            "receipt_sha256 = ?",
            (row["family_asset"], row["frozen_json"], fresh),
        ),
    )
    with pytest.raises(DataError, match="no matching owner authorization"):
        reserved_slots.receipts(home)
    with pytest.raises(DataError, match="changed outside ALPHA"):
        _take(home, _frozen(5, rule="rule1"))


def test_the_challenge_is_the_hash_of_what_the_owner_says_yes_to(home: Path) -> None:
    frozen = _frozen(1)
    payload = {"run_id": frozen["run_id"], "reserved_end": frozen["reserved_end"]}
    challenge_id, raw = challenge(home, payload, frozen["artifact_hash"])
    with sqlite3.connect(home / DB) as connection:
        stored = connection.execute(
            "SELECT binding_json FROM owner_auth_challenges WHERE challenge_id = ?",
            (challenge_id,),
        ).fetchone()[0]
    binding = json.loads(stored)
    assert raw == reserved_slots.binding_challenge(binding)
    assert binding["artifact_hash"] == frozen["artifact_hash"] and len(binding["nonce"]) == 64
