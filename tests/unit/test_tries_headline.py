"""One headline count of tries: the distinct tests on an asset the deflated Sharpe counts.

`alpha ledger summary`, `ledger families`, `ledger tries`, `alpha results` and `alpha test` all
state the same number; the summary's parts add up to it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import _runner
from alpha_cli.main import app
from alpha_cli.spine.facts import read_json
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import load_spec
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

HEADLINE = "You have tested 2 ideas on SPY (by rule shape: spine:ma_cross 1, spine:tsmom 1)."


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("tries")
    seed_store(root, symbol="SPY", n=1100)
    ParquetStore(root / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    cross = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    trend = load_spec(None, rule="tsmom", param=["lookback=60", "skip=5"], asset=["SPY"])
    run_idea(cross, home=root, quick=True, no_diagnose=True)
    run_idea(cross, home=root, quick=True, no_diagnose=True)  # an exact repeat: no row
    with pytest.MonkeyPatch.context() as patch:  # a repeat after a code change: a labelled row
        patch.setattr(_runner, "execution_fingerprint", lambda: "f" * 64)
        run_idea(cross, home=root, quick=True, no_diagnose=True)
    run_idea(trend, home=root, quick=True)
    return root


def _cli(home: Path, *args: str) -> tuple[int, str]:
    out = CliRunner().invoke(app, list(args), env={"ALPHA_DATA_DIR": str(home)})
    return out.exit_code, out.output


def _json(home: Path, *args: str) -> dict[str, Any]:
    code, text = _cli(home, *args, "--json")
    assert code == 0, text
    found: dict[str, Any] = json.loads(text)
    return found


def test_the_ledger_has_three_rows_but_two_tries(home: Path) -> None:
    assert len(read_trials(home)) == 3
    counted = _json(home, "ledger", "summary")["tries"]
    assert counted["total"] == 2
    assert sum(counted["by_kind"].values()) == sum(counted["by_family"].values()) == 2
    assert counted["by_kind"] == {"rule_test": 2}
    assert counted["rows_not_counted"] == 1


def test_every_count_states_the_same_headline(home: Path) -> None:
    code, text = _cli(home, "ledger", "tries", "SPY")
    assert code == 0 and text.strip() == HEADLINE
    _, summary = _cli(home, "ledger", "summary")
    assert "You have tested 2 ideas on all assets" in summary and "By kind:" in summary
    assert "by_outcome" not in summary and " trials" not in summary
    _, families = _cli(home, "ledger", "families")
    assert "You have tested 2 ideas on all assets" in families and " trials" not in families
    # No second count beside the headline: the per-family row counts stay in the JSON.
    assert "reader_trials" not in families and "\trows" not in families
    _, results = _cli(home, "results")
    assert "Total trials" not in results and "You have tested 2 ideas on all assets" in results
    _, only = _cli(home, "results", "--symbol", "SPY")
    assert HEADLINE in only


def test_the_headline_is_the_count_the_deflated_sharpe_uses(home: Path) -> None:
    last = read_trials(home)[-1]
    family = read_json(home / "runs" / last["run_id"] / "diagnostics.json")["trials"]["family"]
    # The last test counted the earlier distinct tests on SPY plus itself: the headline now.
    assert family["same_asset_tests"] + 1 == 2
    assert family["n_trials_used"] >= 2


def test_alpha_test_prints_the_headline(home: Path) -> None:
    code, text = _cli(
        home,
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
    )
    assert code == 0, text
    assert HEADLINE in text and "trials total" not in text


def test_an_unknown_ledger_question_lists_the_valid_names(home: Path) -> None:
    code, text = _cli(home, "ledger", "query", "no-such-question")
    assert code == 1
    assert "by-family" in text and "Choose one of these questions:" in text


def test_alpha_test_ties_the_headline_to_the_deflated_sharpe_count(home: Path) -> None:
    code, text = _cli(
        home,
        "test",
        "--rule",
        "tsmom",
        "--param",
        "lookback=60",
        "--param",
        "skip=5",
        "--asset",
        "SPY",
        "--quick",
    )
    assert code == 0, text
    last = read_trials(home)[-1]
    family = read_json(home / "runs" / last["run_id"] / "diagnostics.json")["trials"]["family"]
    used = family["n_trials_used"]
    line = next(x for x in text.splitlines() if x.startswith("You have tested"))
    assert line.endswith(f"which makes {used} tries in all.")
    assert f"{family['variants_scored']} nearby settings" in line
    assert "family counted as" not in text and "Ledger entry" not in text


def test_ledger_query_tries_gives_the_count_per_asset(home: Path) -> None:
    code, text = _cli(home, "ledger", "query", "tries", "--json")
    assert code == 0, text
    assert json.loads(text)["rows"] == [{"asset": "SPY", "tries": 2}]
    code, text = _cli(home, "ledger", "query", "tries", "--asset", "SPY")
    assert code == 1 and "ledger tries" in text


def test_ledger_query_tries_prints_the_count_column(home: Path) -> None:
    code, text = _cli(home, "ledger", "query", "tries")
    assert code == 0, text
    assert text.splitlines()[:2] == ["asset\ttries", "SPY\t2"]


def test_results_show_prints_the_count_paragraph_under_the_reading(home: Path) -> None:
    last = read_trials(home)[-1]
    code, text = _cli(home, "results", "show", last["run_id"])
    assert code == 0, text
    assert "You have tested" in text and "The luck adjustment adds" in text
    assert "family counted as" not in text and "Ledger entry" not in text
