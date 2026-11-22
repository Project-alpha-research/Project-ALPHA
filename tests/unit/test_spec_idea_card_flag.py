"""`--idea-card` is a label, not a rule flag: it may sit beside a spec file."""

from __future__ import annotations

from pathlib import Path

import pytest

from alpha_cli.spine.spec import load_spec

SPEC = 'name = "t"\nassets = ["SPY"]\n[rule]\nkind = "ma_cross"\nfast = "5"\nslow = "20"\n'


def _write(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "spec.toml"
    path.write_text(extra + SPEC, encoding="utf-8")
    return path


def test_idea_card_flag_is_accepted_with_a_spec_file(tmp_path: Path) -> None:
    spec = load_spec(_write(tmp_path), idea_card="abc123abc123")
    assert spec.idea_card == "abc123abc123"


def test_idea_card_flag_wins_over_the_file_value(tmp_path: Path) -> None:
    spec = load_spec(_write(tmp_path, 'idea_card = "000000000000"\n'), idea_card="abc123abc123")
    assert spec.idea_card == "abc123abc123"


def test_idea_card_flag_changes_no_identity(tmp_path: Path) -> None:
    path = _write(tmp_path)
    assert load_spec(path, idea_card="abc123abc123").spec_sha256 == load_spec(path).spec_sha256


def test_other_flag_with_a_spec_names_the_flag_and_the_fix(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"--fee-bps.*spec file.*Put it in the spec"):
        load_spec(_write(tmp_path), fee_bps=2.0)


def test_cli_links_the_card_from_the_flag_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from alpha_data.store import ParquetStore
    from typer.testing import CliRunner

    from alpha_cli.main import app
    from tests.fixtures.cli_fixtures import seed_store

    home = tmp_path / "home"
    seed_store(home, n=400)
    ParquetStore(home / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    runner = CliRunner()
    made = runner.invoke(app, ["idea", "new", "--claim", "A claim.", "--json"])
    card = str(json.loads(made.output)["id"])
    result = runner.invoke(app, ["test", str(_write(tmp_path)), "--idea-card", card, "--quick"])
    assert result.exit_code == 0, result.output
    assert f"Linked to idea card {card}." in result.output
