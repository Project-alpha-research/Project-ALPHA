"""Test doubles for the owner's Touch ID yes on the reserved period (no real slot, temp homes).

The WebAuthn double stands in for `webauthn.verify_authentication_response`, as the other owner
auth tests do. It is a deterministic signature: SHA-256 of the challenge and the public key. A
bogus signature fails, so a forged authorization row cannot pass the reverification.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from alpha_cli import owner_auth
from alpha_cli.control_store import ControlStore

PUBLIC_KEY = b"owner-public-key"
CREDENTIAL = "dG91Y2gtaWQtY3JlZGVudGlhbA"


def signature(challenge: bytes, public_key: bytes = PUBLIC_KEY) -> str:
    return hashlib.sha256(challenge + public_key).hexdigest()


def install_double(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Replace the WebAuthn check; returns the list of sign counts it was asked about."""
    calls: list[int] = []

    def verify(**kwargs: Any) -> SimpleNamespace:
        sent = kwargs["credential"]["response"]["signature"]
        calls.append(int(kwargs["credential_current_sign_count"]))
        if sent != signature(kwargs["expected_challenge"], kwargs["credential_public_key"]):
            raise ValueError("bad signature")
        assert kwargs["expected_origin"] == "http://localhost:8801"
        assert kwargs["require_user_verification"] is True
        return SimpleNamespace(new_sign_count=int(kwargs["credential_current_sign_count"]) + 1)

    monkeypatch.setattr(owner_auth, "verify_authentication_response", verify)
    return calls


def enroll(home: Path) -> None:
    store = ControlStore(home)
    now = datetime.now(UTC)
    token_hash = hashlib.sha256(b"trusted-test-token").hexdigest()
    request = store.create_owner_enrollment_request(
        token_hash=token_hash,
        reason="test enrollment",
        replace_existing=False,
        now=now,
        expires_at=now + timedelta(minutes=5),
    )
    registration = store.create_owner_auth_challenge(
        ceremony="registration",
        challenge=b"r" * 32,
        binding={"token_hash": token_hash},
        enrollment_request_id=str(request["request_id"]),
        now=now,
        expires_at=now + timedelta(seconds=60),
    )
    store.complete_owner_registration(
        token_hash=token_hash,
        challenge_id=str(registration["challenge_id"]),
        credential_id=CREDENTIAL,
        public_key=PUBLIC_KEY,
        sign_count=1,
        transports=["internal"],
        now=now,
    )


def challenge(home: Path, payload: dict[str, Any], artifact_hash: str) -> tuple[str, bytes]:
    options = owner_auth.reserved_confirmation_options(
        data_dir=home,
        payload=payload,
        artifact_hash=artifact_hash,
        consequence_summary="Uses 1 of 10 slots.",
        reason="test",
    )
    public_key = cast(dict[str, Any], options["public_key"])
    raw = str(public_key["challenge"])
    return str(options["challenge_id"]), base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def owner_yes(home: Path, payload: dict[str, Any], artifact_hash: str) -> str:
    """One Touch ID yes through the real verify path, with the signature double."""
    challenge_id, raw = challenge(home, payload, artifact_hash)
    found = owner_auth.verify_action_assertion(
        data_dir=home,
        challenge_id=challenge_id,
        credential={"id": CREDENTIAL, "response": {"signature": signature(raw)}},
        payload=payload,
    )
    return str(found["authorization_id"])
