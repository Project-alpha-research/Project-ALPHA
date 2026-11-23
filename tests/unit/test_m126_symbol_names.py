"""A short symbol (BTC) means the stored name (BTC/USDT) in the ledger commands too."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import load_spec
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("symbols")
    seed_store(root, symbol="BTC/USDT", n=1100)
    ParquetStore(root / "store").write_provenance(
        "BTC/USDT", source="ccxt", adapter_version="1", parser_version="1"
    )
    spec = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["BTC"])
    run_idea(spec, home=root, quick=True, no_diagnose=True)
    return root


def _cli(home: Path, *args: str) -> tuple[int, str]:
    out = CliRunner().invoke(app, list(args), env={"ALPHA_DATA_DIR": str(home)})
    return out.exit_code, out.output


def test_ledger_tries_resolves_a_short_symbol_and_says_so(home: Path) -> None:
    code, text = _cli(home, "ledger", "tries", "BTC")
    assert code == 0, text
    assert "You have tested 1 idea on BTC/USDT" in text
    assert "BTC is stored as BTC/USDT" in text


def test_a_full_symbol_prints_no_note(home: Path) -> None:
    code, text = _cli(home, "ledger", "tries", "BTC/USDT")
    assert code == 0, text
    assert "1 idea on BTC/USDT" in text and "is stored as" not in text


def test_ledger_list_and_query_resolve_the_asset_too(home: Path) -> None:
    code, text = _cli(home, "ledger", "list", "--asset", "BTC")
    assert code == 0, text
    assert "BTC is stored as BTC/USDT" in text
    code, text = _cli(home, "ledger", "query", "asset-history", "--asset", "BTC", "--json")
    assert code == 0, text
    assert "BTC is stored as BTC/USDT" in text and "ma_cross" in text


def test_an_unstored_symbol_still_answers_as_typed(home: Path) -> None:
    code, text = _cli(home, "ledger", "tries", "NOPE")
    assert code == 0, text
    assert "0 ideas on NOPE" in text


def test_results_list_resolves_the_symbol(home: Path) -> None:
    code, text = _cli(home, "results", "--symbol", "BTC")
    assert code == 0, text
    assert "BTC is stored as BTC/USDT" in text and "ma_cross" in text
