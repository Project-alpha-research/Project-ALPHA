"""Planted answers exercise the installed checker's exact problem kinds."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import results_cmds
from alpha_cli.spine.check import check_text
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.honesty import build_fixture
from alpha_cli.spine.honesty_more import SCENARIOS
from alpha_cli.spine.honesty_scenarios import H1, A, Scenario


@pytest.fixture
def home(tmp_path: Path) -> Path:
    build_fixture(tmp_path)
    return tmp_path


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.id)
def test_every_scenario_behaves(home: Path, scenario: Scenario) -> None:
    result = check_text(
        scenario.draft, results_cmds.fact_lookup(home), 0, results_cmds.flag_lookup(home)
    )
    assert {p["kind"] for p in result["problems"]} == scenario.expected
    assert result["ok"] is scenario.honest


def test_unicode_minus_keeps_value_and_offsets(home: Path) -> None:
    draft = H1.replace("-34.4%", "−34.4%")
    assert check_text(draft, results_cmds.fact_lookup(home))["ok"]
    result = check_text(draft.replace("−34.4%", "−35.4%"), results_cmds.fact_lookup(home))
    assert result["problems"][0]["line"] == 4
    assert "−35.4%" in result["problems"][0]["excerpt"]


@pytest.mark.parametrize(
    "word",
    [
        "Sharpe",
        "DSR",
        "CAGR",
        "return",
        "returns",
        "drawdown",
        "drawdowns",
        "beta",
        "exposure",
        "profit",
        "profits",
        "volatility",
    ],
)
def test_small_financial_integers_need_tags(home: Path, word: str) -> None:
    result = check_text(f"The {word} was 3.", results_cmds.fact_lookup(home))
    assert [p["kind"] for p in result["problems"]] == ["UNTAGGED_NUMBER"]


@pytest.mark.parametrize(
    "draft,checked",
    [
        ("We made 3 trades.", 1),
        ("We made 1 trade.", 1),
        ("trial 3 of the set; ALPHA 2", 0),
        ("Sharpen 3", 0),
        ("Sharpe\n3 assets", 0),
        ("Sharpe" + " " * 40 + "3", 1),
        ("Sharpe" + " " * 41 + "3", 0),
        ("`Sharpe` 3 assets", 0),
        ("Sharpe 2026", 0),
    ],
)
def test_small_integer_context_boundaries(home: Path, draft: str, checked: int) -> None:
    assert check_text(draft, results_cmds.fact_lookup(home))["checked_numbers"] == checked


@pytest.mark.parametrize("metric", ["dsr", "trial_dsr"])
@pytest.mark.parametrize("written", ["0.95", "95%"])
def test_rounding_cannot_cross_pass_line(home: Path, metric: str, written: str) -> None:
    def lookup(run: str, name: str) -> dict[str, Any]:
        fact = results_cmds.fact_lookup(home)(run, name)
        return {**fact, "value": 0.946} if name == metric else fact

    result = check_text(f"Score {written} [{A}:{metric}]. 12 [{A}:total_trials]", lookup)
    (problem,) = result["problems"]
    assert problem["kind"] == "ROUNDED_ACROSS_THRESHOLD"
    assert problem["stored"] == {"value": 0.946, "threshold": 0.95}
    assert "Write at least three decimals." in problem["message"]
    assert check_text(f"Score 0.946 [{A}:{metric}]. 12 [{A}:total_trials]", lookup)["ok"]


@pytest.mark.parametrize(
    "code,sentence",
    [
        ("below-benchmark", "It outperformed the buy-and-hold."),
        ("fragile-to-costs", "It held up when costs doubled."),
        ("fragile-to-parameters", "It is insensitive to settings."),
        ("fragile-to-delay", "It is unaffected by delay."),
        ("concentrated-profit", "Profit was spread over trades."),
        ("drawdown-with-market", "Losses were independent of the market."),
    ],
)
def test_flag_contradictions_and_negation(home: Path, code: str, sentence: str) -> None:
    def flags(run: str) -> list[dict[str, str]]:
        assert run == A
        return [{"flag": code, "detail": "Stored warning."}]

    prefix = f"12 [{A}:total_trials].\n"
    result = check_text(prefix + sentence, results_cmds.fact_lookup(home), flags=flags)
    (problem,) = result["problems"]
    assert problem["kind"] == "FLAG_CONTRADICTED"
    assert problem["stored"] == code and problem["line"] == 2
    assert problem["message"] == f"Run {A} carries the flag {code}: Stored warning."
    for negation in ("not", "never", "no longer", "failed to", "didn't"):
        assert check_text(
            prefix + negation + " " + sentence, results_cmds.fact_lookup(home), flags=flags
        )["ok"]
    assert check_text(prefix + f"`{sentence}`", results_cmds.fact_lookup(home), flags=flags)["ok"]


@pytest.mark.parametrize(
    "sentence",
    [
        "No flags.",
        "No red flags or warnings.",
        "No warnings.",
        "Nothing was flagged.",
        "Nothing flagged.",
        "It never had no warning flags.",
    ],
)
def test_flag_denials_report_each_flag_once(home: Path, sentence: str) -> None:
    result = check_text(
        H1 + sentence, results_cmds.fact_lookup(home), flags=results_cmds.flag_lookup(home)
    )
    assert [p["stored"] for p in result["problems"]] == ["drawdown-with-market", "fragile-to-costs"]


def test_missing_registered_fact_is_actionable(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(results_cmds, "build_facts", lambda folder: [])
    with pytest.raises(SpineError) as caught:
        results_cmds.fact_lookup(home)(A, "dsr")
    assert caught.value.payload["code"] == "METRIC_NOT_STORED"
    assert str(caught.value) == f"Run {A} has no stored fact dsr in its run folder."
    assert (
        caught.value.payload["next"]
        == "Cite tool facts with alpha results cite <run_id> <metric> --tool-output <id>."
    )


def test_flag_lookup_missing_diagnostics(home: Path) -> None:
    (home / "runs" / A / "diagnostics.json").unlink()
    assert results_cmds.flag_lookup(home)(A) == []


def test_results_check_uses_stored_flags(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    path = home / "draft.md"
    path.write_text(H1 + "No flags were raised.\n", encoding="utf-8")
    result = CliRunner().invoke(results_cmds.results_app, ["check", str(path), "--json"])
    assert result.exit_code == 1
    assert '"kind": "FLAG_CONTRADICTED"' in result.stdout


def test_decimal_does_not_split_negated_flag_sentence(home: Path) -> None:
    flags = results_cmds.flag_lookup(home)
    draft = H1 + "It is not, at Sharpe 0.81 [a1a1a1a1:oos_sharpe], robust to costs."
    assert check_text(draft, results_cmds.fact_lookup(home), flags=flags)["ok"]
    result = check_text(
        draft + " It held up to costs.", results_cmds.fact_lookup(home), flags=flags
    )
    assert [p["kind"] for p in result["problems"]] == ["FLAG_CONTRADICTED"]
