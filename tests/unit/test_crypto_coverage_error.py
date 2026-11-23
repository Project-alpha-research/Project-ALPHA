"""`alpha crypto-data coverage` reports a store problem as one plain sentence."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from alpha_cli import crypto_data_cmds
from alpha_core import DataError


def test_a_store_error_is_one_plain_sentence(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> None:
        raise DataError("the volume is not mounted\nmore detail")

    monkeypatch.setattr(crypto_data_cmds, "_bulk_store", broken)
    ran = CliRunner().invoke(crypto_data_cmds.crypto_data_app, ["coverage"])
    assert ran.exit_code == 2
    assert "Invalid value" not in ran.output
    assert ran.output.strip() == "the volume is not mounted."
