"""The tries paragraph says what each count is and why they differ."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alpha_cli.spine.tries import reading_count_sentence

FAMILY = {
    "n_trials_used": 12,
    "this_run": 1,
    "variants_scored": 5,
    "unknown_rows": 0,
    "prior_trials": 6,
    "same_asset_tests": 4,
    "family_id": "spine:ma_cross",
}


def test_each_count_says_what_it_counts() -> None:
    text = reading_count_sentence(dict(FAMILY), "SPY")
    assert text is not None
    assert "5 ideas on SPY, counting this asset alone" in text
    assert "7 times across all assets, which can be more than the first count" in text
    assert "5 nearby settings tried inside this test" in text
    assert text.endswith("which makes 12 tries in all.")
    assert "plus these" not in text


def _reading(
    word: str, because: list[str], sharpe: float, lower: float, dsr: float
) -> dict[str, Any]:
    return {
        "sentence": "x.",
        "evidence": {"word": word, "because": because},
        "measures": [
            {"name": "out-of-sample Sharpe", "value": sharpe, "interval_95": [lower, 2.0]},
            {"name": "deflated Sharpe", "value": dsr, "interval_95": None},
        ],
    }


def test_the_bridge_names_the_random_price_tests_when_they_decided() -> None:
    from alpha_cli.spine.reading import deciding_sentence

    found = _reading(
        "not clear of chance",
        ["Random-data tests held: 1 of 3.", "Sharpe interval 0.10 to 2.00 (95%)."],
        1.0,
        0.1,
        0.999,
    )
    text = deciding_sentence(found)
    assert text is not None
    assert "random-price tests" in text and "1 of 3" in text
    assert "deflated Sharpe" not in text


def test_the_bridge_names_the_trade_count_when_it_decided() -> None:
    from alpha_cli.spine.reading import deciding_sentence

    found = _reading(
        "too little to read", ["8 closed trades (fewer than 30 make too few to judge)."], 1, 1, 1
    )
    assert deciding_sentence(found) == (
        "What decided it: 8 closed trades (fewer than 30 make too few to judge)."
    )


def test_the_bridge_is_absent_for_a_reading_without_evidence() -> None:
    from alpha_cli.spine.reading import deciding_sentence

    assert deciding_sentence({"sentence": "x."}) is None


def test_heartbeat_names_the_stage(capsys: pytest.CaptureFixture[str]) -> None:
    import time

    from alpha_cli._progress import heartbeat

    stage = ["testing SPY (1 of 2)"]
    with heartbeat(lambda: f"alpha test: {stage[0]}", every=0.05, expected=480):
        time.sleep(0.2)
    err = capsys.readouterr().err
    assert "alpha test: testing SPY (1 of 2): still running" in err and "of about 480" in err


def test_run_idea_reports_each_asset_stage(tmp_path: Path) -> None:
    from alpha_cli.spine.run import run_idea
    from alpha_cli.spine.spec import load_spec
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    seed_store(tmp_path, symbol="SPY", n=300)
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    seen: list[str] = []
    spec = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    run_idea(spec, home=tmp_path, quick=True, no_diagnose=True, stage=seen.append)
    assert seen == ["reading the data for SPY (1 of 1)", "testing SPY (1 of 1)"]


def test_alpha_test_prints_the_expected_time_first(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from alpha_cli.main import app
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    seed_store(tmp_path, symbol="SPY", n=300)
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    out = CliRunner().invoke(
        app,
        [
            "test",
            "--rule",
            "ma_cross",
            "--param",
            "fast=5",
            "--param",
            "slow=20",
            "--asset",
            "SPY",
            "--quick",
            "--no-diagnose",
            "--json",
        ],
        env={"ALPHA_DATA_DIR": str(tmp_path)},
    )
    assert out.exit_code == 0, out.output
    assert "alpha test: no time estimate yet" in out.output  # nothing timed on this computer yet


def test_the_deciding_sentence_has_one_heading_for_every_reading() -> None:
    from alpha_cli.spine.reading import deciding_sentence

    found = _reading(
        "some evidence", ["Sharpe interval 0.1 to 2.0.", "Only 3 years of data."], 1, 1, 1
    )
    text = deciding_sentence(found)
    assert text is not None and text.startswith("What decided it: ")


def test_the_tries_paragraph_is_three_short_sentences() -> None:
    from alpha_cli.spine.tries import reading_count_sentence

    said = reading_count_sentence(
        {
            "n_trials_used": 17,
            "prior_trials": 11,
            "this_run": 1,
            "same_asset_tests": 5,
            "variants_scored": 5,
            "family_id": "spine:ma_cross",
        },
        "SPY",
    )
    assert said is not None
    assert len([s for s in said.split(". ") if s]) == 4  # the first count, then three
    assert all(len(s) < 160 for s in said.split(". "))
