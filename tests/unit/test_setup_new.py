"""`alpha setup new` and the direct options write a complete, valid spec; no hand-written file."""

from __future__ import annotations

import json
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli import setup_cmds
from alpha_cli._setup_spec_build import SpecOptions, build_spec, spec_text
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.setup_find import load_setup_spec
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

RUNNER = CliRunner()


def seed(home: Path) -> None:
    seed_store(home, n=100)
    ParquetStore(home / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    return tmp_path


def test_defaults_give_a_complete_valid_spec() -> None:
    options = SpecOptions(name="my-idea")
    spec = load_setup_spec(build_spec(options))
    assert spec.setup.assets == ("SPY",)
    assert spec.exit is not None
    assert (spec.exit.stop, spec.exit.target) == ("5 %", "10 %")
    assert spec.study is not None and spec.study.primary == 10


def test_every_option_reaches_the_spec() -> None:
    options = SpecOptions(
        name="dip",
        assets=("QQQ", "IWM"),
        when="close < sma(close, 20)",
        horizon=7,
        stop="2 atr(14)",
        target="15 %",
    )
    spec = load_setup_spec(build_spec(options))
    assert spec.setup.assets == ("QQQ", "IWM")
    assert spec.setup.event == "close < sma(close, 20)"
    assert spec.study is not None and spec.study.primary == 7 and 7 in spec.study.horizons
    assert spec.exit is not None and spec.exit.time_bars == 7
    assert (spec.exit.stop, spec.exit.target) == ("2 atr(14)", "15 %")


def test_the_text_is_commented_toml_that_loads_to_the_same_spec(tmp_path: Path) -> None:
    options = SpecOptions(name="dip", when="close > open and volume > 0")
    text = spec_text(options)
    assert text.count("#") >= 8 and "[exit]" in text
    path = tmp_path / "dip.toml"
    path.write_text(text)
    assert tomllib.loads(text) == build_spec(options)
    assert load_setup_spec(path).spec_sha256 == load_setup_spec(build_spec(options)).spec_sha256


BASE = SpecOptions(name="x")


@pytest.mark.parametrize(
    ("options", "words"),
    [
        (replace(BASE, when="nonsense("), "--when"),
        (replace(BASE, horizon=0), "--horizon"),
        (replace(BASE, stop="wide"), "--stop"),
        (replace(BASE, target="0 %"), "--target"),
        (replace(BASE, name="../evil"), "name"),
    ],
)
def test_a_bad_option_is_one_plain_sentence_naming_it(options: SpecOptions, words: str) -> None:
    with pytest.raises(SpineError) as caught:
        spec_text(options)
    assert words in str(caught.value)
    assert "Traceback" not in str(caught.value)


def test_new_writes_the_file_and_prints_path_and_command(home: Path) -> None:
    result = RUNNER.invoke(setup_cmds.setup_app, ["new", "dip", "--asset", "QQQ", "--horizon", "5"])
    assert result.exit_code == 0, result.output
    path = home / "specs" / "dip.toml"
    assert path.is_file()
    assert str(path) in result.stdout
    assert f"alpha setup find {path}" in result.stdout
    assert load_setup_spec(path).setup.assets == ("QQQ",)


def test_new_never_overwrites_a_file(home: Path) -> None:
    assert RUNNER.invoke(setup_cmds.setup_app, ["new", "dip"]).exit_code == 0
    before = (home / "specs" / "dip.toml").read_text()
    again = RUNNER.invoke(setup_cmds.setup_app, ["new", "dip", "--horizon", "3"])
    assert again.exit_code == 1
    assert "already exists" in again.output
    assert (home / "specs" / "dip.toml").read_text() == before


def test_find_needs_no_file_when_options_are_given(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(home)
    monkeypatch.setattr(setup_cmds, "draw_sheet", lambda *a, **k: b"png")
    args = ["find", "--when", "volume == 1", "--json"]
    first = RUNNER.invoke(setup_cmds.setup_app, args)
    assert first.exit_code == 0, first.output
    again = RUNNER.invoke(setup_cmds.setup_app, args)
    assert json.loads(again.stdout)["find_id"] == json.loads(first.stdout)["find_id"]
    assert len(list((home / "specs").glob("*.toml"))) == 1


def test_a_spec_file_and_direct_options_together_are_refused(home: Path) -> None:
    path = home / "a.toml"
    path.write_text(spec_text(SpecOptions(name="a")))
    result = RUNNER.invoke(setup_cmds.setup_app, ["find", str(path), "--when", "volume == 1"])
    assert result.exit_code == 1
    assert "not both" in result.output


def test_study_and_trade_take_options_or_a_find_id_not_both(home: Path) -> None:
    both = RUNNER.invoke(setup_cmds.setup_app, ["study", "0" * 16, "--when", "volume == 1"])
    assert both.exit_code == 1 and "not both" in both.output
    none = RUNNER.invoke(setup_cmds.setup_app, ["trade"])
    assert none.exit_code == 1 and "Give a find id" in none.output


def test_study_runs_a_find_first_when_given_options(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(home)
    monkeypatch.setattr(setup_cmds, "draw_sheet", lambda *a, **k: b"png")
    result = RUNNER.invoke(setup_cmds.setup_app, ["study", "--when", "volume == 1", "--json"])
    assert result.exit_code == 0, result.output
    assert len(list((home / "setups").glob("*/manifest.json"))) == 1
    assert list((home / "setup-studies").glob("*/manifest.json"))


def test_an_edited_quick_spec_is_refused_not_used(home: Path) -> None:
    from alpha_cli._setup_spec_build import direct_spec

    path = direct_spec(home, SpecOptions(name="quick"))
    path.write_text(path.read_text().replace("20", "21"))
    with pytest.raises(SpineError) as caught:
        direct_spec(home, SpecOptions(name="quick"))
    assert "edited" in str(caught.value)
    assert "21" in path.read_text()


def test_recheck_with_options_writes_nothing(home: Path) -> None:
    result = RUNNER.invoke(setup_cmds.setup_app, ["study", "--when", "volume == 1", "--recheck"])
    assert result.exit_code == 1 and "--recheck needs a find id" in result.output
    assert not (home / "specs").exists()


def test_accept_bad_data_reaches_the_first_find(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str | None] = []

    def fake(
        home: Path, options: SpecOptions, *, accept_bad_data: str | None = None, **kw: object
    ) -> dict[str, str]:
        seen.append(accept_bad_data)
        raise SpineError("STOP", "stop", "stop")

    monkeypatch.setattr(setup_cmds, "_find_from_options", fake)
    for kind in ("study", "trade"):
        RUNNER.invoke(
            setup_cmds.setup_app, [kind, "--when", "volume == 1", "--accept-bad-data", "why"]
        )
    assert seen == ["why", "why"]
