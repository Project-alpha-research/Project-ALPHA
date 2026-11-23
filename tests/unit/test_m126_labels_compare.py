"""Labels print with their meaning everywhere; the compare table has no self-comparison."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_cli.spine.compare import render_compare
from alpha_cli.spine.label_meaning import LABEL_MEANING
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import load_spec
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    root = tmp_path_factory.mktemp("labels")
    seed_store(root, symbol="SPY", n=300)
    ParquetStore(root / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    ids = []
    for fast in ("5", "8"):
        spec = load_spec(None, rule="ma_cross", param=[f"fast={fast}", "slow=20"], asset=["SPY"])
        ids.append(run_idea(spec, home=root, quick=True, no_diagnose=True)["results"][0]["run_id"])
    return root, ids


def _cli(home: Path, *args: str) -> str:
    out = CliRunner().invoke(app, list(args), env={"ALPHA_DATA_DIR": str(home)})
    assert out.exit_code == 0, out.output
    return out.output


def test_report_show_list_and_compare_gloss_the_labels(runs: tuple[Path, list[str]]) -> None:
    home, ids = runs
    meaning = LABEL_MEANING["too-few-trades"]
    assert meaning in _cli(home, "report", ids[0])
    assert meaning in _cli(home, "results", "show", ids[0])
    assert meaning in _cli(home, "results", "compare", ids[0], ids[1])
    assert "Labels:" in _cli(home, "results") and meaning in _cli(home, "results")


def test_compare_prints_each_run_id_once_and_no_self_column() -> None:
    cell = {"value": {"value": 1.0}, "diff": {"value": 0.0}, "ratio": {"value": 1.0}}
    other = {"value": {"value": 2.0}, "diff": {"value": 1.0}, "ratio": {"value": 2.0}}
    text = render_compare(
        {
            "runs": [{"run_id": "aaa", "labels": []}, {"run_id": "bbb", "labels": []}],
            "metrics": {"sharpe": [cell, other]},
            "warnings": [],
        }
    )
    header = text.splitlines()[0]
    assert header.count("aaa") == header.count("bbb") == 1
    assert "1.00x" not in text and text.splitlines()[1].count("\t") == 4


def test_report_and_show_print_what_decided_the_reading(runs: tuple[Path, list[str]]) -> None:
    home, ids = runs
    assert "What decided it: 8 closed trades" in _cli(home, "report", ids[0])
    assert "What decided it: 8 closed trades" in _cli(home, "results", "show", ids[0])
