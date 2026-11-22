"""The provider CLI emits receipts and converts unsupported checks to safe usage errors."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from alpha_cli import provider_readiness
from alpha_cli.main import app
from alpha_core import DataError

runner = CliRunner()


def test_provider_check_cli_supports_json_human_and_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt: dict[str, object] = {
        "schema_version": 1,
        "provider_id": "tiingo",
        "verification_state": "verified",
        "checked_at": "2026-08-13T00:00:00Z",
        "granted_capabilities": ["historical_bars"],
        "recovery_action": "No action required.",
        "details": {"interface": "rest"},
        "receipt_id": "a" * 64,
        "content_sha256": "a" * 64,
    }
    monkeypatch.setattr(
        provider_readiness,
        "run_explicit_check",
        lambda *args, **kwargs: receipt,
    )
    machine = runner.invoke(app, ["provider", "check", "tiingo", "--json"])
    human = runner.invoke(app, ["provider", "check", "tiingo"])
    assert machine.exit_code == 0
    assert json.loads(machine.stdout)["verification_state"] == "verified"
    assert human.exit_code == 0
    assert "tiingo: verified" in human.stdout

    def fail(*args: object, **kwargs: object) -> dict[str, object]:
        raise DataError("unsupported provider")

    monkeypatch.setattr(provider_readiness, "run_explicit_check", fail)
    rejected = runner.invoke(app, ["provider", "check", "unknown"])
    assert rejected.exit_code != 0
    assert "unsupported provider" in rejected.output
