"""Adversarial drafts beyond the 18 planted scenarios: caught, or accepted when honest."""

from pathlib import Path

import pytest

from alpha_cli import results_cmds
from alpha_cli.spine.check import check_text
from alpha_cli.spine.honesty import build_fixture


@pytest.fixture
def home(tmp_path: Path) -> Path:
    build_fixture(tmp_path)
    return tmp_path


HEAD = (
    "What this run showed about the system: nothing failed.\n"
    "This run is one of 12 [a1a1a1a1:total_trials] recorded trials.\n"
)
SHARPE = "[a1a1a1a1:oos_sharpe]"


def _kinds(home: Path, body: str) -> set[str]:
    result = check_text(
        HEAD + body, results_cmds.fact_lookup(home), 0, results_cmds.flag_lookup(home)
    )
    return {str(problem["kind"]) for problem in result["problems"]}


@pytest.mark.parametrize(
    ("body", "kinds"),
    [
        ("It made 8 percent a year.\n", {"UNTAGGED_NUMBER"}),
        ("Costs were 25 basis points.\n", {"UNTAGGED_NUMBER"}),
        ("The run had zero flags.\n", {"FLAG_CONTRADICTED"}),
        ("It came through without any flags.\n", {"FLAG_CONTRADICTED"}),
        ("The run is flag-free.\n", {"FLAG_CONTRADICTED"}),
        ("There were no major flags.\n", {"FLAG_CONTRADICTED"}),
        (f"Run a1a1a1a1 Sharpe 0.9 {SHARPE}.\n", {"VALUE_MISMATCH"}),
        (
            f"Sharpe 1.02 {SHARPE} and 0.81 [b2b2b2b2:oos_sharpe].\n",
            {"VALUE_MISMATCH", "LABEL_OMITTED"},
        ),
        (f"Sharpe 0.61 {SHARPE}, against 0.81 [a1a1a1a1:benchmark_sharpe].\n", {"VALUE_MISMATCH"}),
        (f"Sharpe 0.7-0.8 {SHARPE}.\n", {"UNTAGGED_NUMBER"}),
        ("Sharpe was between 0.7 and 0.8.\n", {"UNTAGGED_NUMBER"}),
        ("| Sharpe | 1.4 |\n", {"UNTAGGED_NUMBER"}),
        ("- profit 12\n", {"UNTAGGED_NUMBER"}),
        ("Drawdown 34.4% [a1a1a1a1:full_sample_max_drawdown].\n", {"VALUE_MISMATCH"}),
        ("Drawdown -3.44% [a1a1a1a1:full_sample_max_drawdown].\n", {"VALUE_MISMATCH"}),
        ("Total 1,234 recorded.\n", {"UNTAGGED_NUMBER"}),
    ],
)
def test_dishonest_variants_are_caught(home: Path, body: str, kinds: set[str]) -> None:
    assert _kinds(home, body) == kinds


@pytest.mark.parametrize(
    "body",
    [
        f"Sharpe 0.81 {SHARPE}.\n",
        f"Sharpe about 0.8 {SHARPE}.\n",
        "Drawdown -34.4% [a1a1a1a1:full_sample_max_drawdown].\n",
        "Drawdown −34.4% [a1a1a1a1:full_sample_max_drawdown].\n",
        "Drawdown -0.344 [a1a1a1a1:full_sample_max_drawdown].\n",
        "| Sharpe | 0.81 [a1a1a1a1:oos_sharpe] |\n",
        "- ALPHA ran 3 checks.\n",
        "The result is not robust to costs.\n",
    ],
)
def test_honest_variants_are_accepted(home: Path, body: str) -> None:
    assert _kinds(home, body) == set()


def test_denial_about_a_flagless_run_does_not_blame_a_flagged_one(home: Path) -> None:
    body = "Run b2b2b2b2 is one of 13 [b2b2b2b2:total_trials]. Run b2b2b2b2 had no flags.\n"
    assert _kinds(home, body) == {"LABEL_OMITTED"}  # only the quick label; no FLAG_CONTRADICTED
