"""`alpha lookalike` and `alpha unusual` in-process, on a seeded store."""

import json
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from alpha_cli.lookalike_cmds import lookalike, unusual
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store


def app() -> typer.Typer:
    root = typer.Typer()
    root.command("lookalike")(lookalike)
    root.command("unusual")(unusual)
    return root


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    seed_store(data, symbol="SPY", n=400)
    ParquetStore(data / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    monkeypatch.setenv("ALPHA_DATA_DIR", str(data))
    return data


def run(*args: str, ok: bool = True) -> Any:
    result = CliRunner().invoke(app(), [*args, "--json"])
    assert (result.exit_code == 0) is ok, result.stdout
    return json.loads(result.stdout)


def test_lookalike_writes_one_labelled_result_and_one_trial(home: Path) -> None:
    ran = run("lookalike", "--asset", "SPY", "--last", "20", "--max-distance", "1e6")
    assert ran["schema"] == "AlphaLookalikeV1"
    assert "exploratory" in ran["labels"]
    folder = Path(ran["result_dir"])
    stored = json.loads((folder / "result.json").read_text())
    assert stored["facts"] == ran["facts"]
    assert (folder / "figure.png").read_bytes()[:4] == b"\x89PNG"
    trials = (home / "ledger" / "trials.jsonl").read_text().splitlines()
    assert json.loads(trials[-1])["rule"] == "lookalike"
    again = run("lookalike", "--asset", "SPY", "--last", "20", "--max-distance", "1e6")
    assert "repeat" in again["labels"]
    assert again["trial"]["looks"] == 2


def test_lookalike_with_the_declared_default_and_text_output(home: Path) -> None:
    ran = run("lookalike", "--asset", "SPY", "--last", "20")
    assert ran["search"]["max_distance_basis"].startswith("declared default")
    text = CliRunner().invoke(app(), ["lookalike", "--asset", "SPY", "--last", "20"])
    assert text.exit_code == 0
    assert "What happened next" in text.stdout and "Figure:" in text.stdout


def test_unusual_scores_the_latest_window(home: Path) -> None:
    ran = run("unusual", "--asset", "SPY", "--window", "20")
    assert ran["schema"] == "AlphaUnusualV1"
    assert 0.0 <= ran["novelty"]["percentile"] <= 100.0
    assert (Path(ran["result_dir"]) / "figure.png").exists()
    text = CliRunner().invoke(app(), ["unusual", "--asset", "SPY", "--window", "20"])
    assert text.exit_code == 0 and text.stdout.strip()


@pytest.mark.parametrize(
    "args,code",
    [
        (["lookalike", "--asset", "NOPE"], "UNKNOWN_ASSET"),
        (["unusual", "--asset", "NOPE"], "UNKNOWN_ASSET"),
        (["lookalike", "--asset", "SPY", "--last", "5000"], "LOOKALIKE_FAILED"),
    ],
)
def test_bad_inputs_fail_with_a_stable_error(home: Path, args: list[str], code: str) -> None:
    error = run(*args, ok=False)["error"]
    assert error["code"] == code
    assert "alpha " in error["next"]


@pytest.mark.parametrize("bad", ["0", "a,b", ","])
def test_horizons_must_be_positive_whole_numbers(home: Path, bad: str) -> None:
    result = CliRunner().invoke(app(), ["lookalike", "--asset", "SPY", "--horizons", bad])
    assert result.exit_code != 0


def test_a_single_horizon_is_reported(home: Path) -> None:
    ran = run(
        "lookalike", "--asset", "SPY", "--last", "20", "--horizons", "3", "--max-distance", "1e6"
    )
    assert ran["settings"]["horizons"] == [3]
