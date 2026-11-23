"""`alpha ml run` names every symbol with no stored bars at once."""

from __future__ import annotations

from pathlib import Path

import pytest

from alpha_cli.ml_run import MlRunError, _require_stored
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store


def test_all_missing_symbols_are_named_with_their_pull_lines(tmp_path: Path) -> None:
    seed_store(tmp_path, symbol="SPY", n=30)
    store = ParquetStore(tmp_path / "store")
    with pytest.raises(MlRunError) as caught:
        _require_stored(store, ["QQQ", "SPY", "IWM"])
    said = str(caught.value)
    assert "No stored bars for QQQ, IWM." in said
    assert "alpha data pull QQQ --start <date> --end <date>" in said
    assert "alpha data pull IWM --start <date> --end <date>" in said
    assert "alpha data pull SPY" not in said
    assert "edit the `assets` list in the spec" in said


def test_nothing_is_raised_when_all_are_stored(tmp_path: Path) -> None:
    seed_store(tmp_path, symbol="SPY", n=30)
    _require_stored(ParquetStore(tmp_path / "store"), ["SPY"])
