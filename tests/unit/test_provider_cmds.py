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
    monkeypatch.setenv("ALPHA_TIINGO_API_KEY", "set")
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


def test_provider_check_says_no_key_set_and_names_the_variable_never_a_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APCA_API_KEY_ID", "id-value-never-shown")
    called: list[str] = []
    monkeypatch.setattr(
        provider_readiness, "run_explicit_check", lambda *args, **kwargs: called.append("x")
    )
    result = runner.invoke(app, ["provider", "check", "alpaca"])
    assert result.exit_code == 1 and not called
    assert "alpaca: no key set" in result.output and "APCA_API_SECRET_KEY" in result.output
    assert "id-value-never-shown" not in result.output and "schema_drift" not in result.output


def test_provider_check_for_a_provider_with_no_check_lists_those_that_have_one() -> None:
    result = runner.invoke(app, ["provider", "check", "yfinance"])
    assert result.exit_code != 0
    assert "alpaca, coingecko, defillama, tiingo" in result.output
