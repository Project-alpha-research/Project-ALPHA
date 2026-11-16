"""Stored comparisons retain provenance and explain unavailable arithmetic."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli.results_cmds import fact_lookup, results_app
from alpha_cli.spine.compare import DEFAULT_METRICS, compare_runs
from alpha_cli.spine.errors import SpineError

A = "9a99cb94971d54dc"
B = "abcd1234971d54dc"


def make_lookup(home: Path):
    for run_id, value, basis in ((A, 0.8, "base"), (B, 1.2, "other")):
        directory = home / "runs" / run_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "manifest.json").write_text(
            json.dumps(
                {
                    "oos_metrics": {"sharpe": value},
                    "spine": {"labels": ["quick"]},
                }
            )
        )
        (directory / "diagnostics.json").write_text(
            json.dumps(
                {
                    "full_sample": {"total_return": 0.755, "trades": 1234, "basis": basis},
                    "trials": {"total_trials": 12},
                    "benchmark": {"reasons": {"sharpe": "no benchmark bars"}},
                }
            )
        )
    return fact_lookup(home)


def test_comparison_arithmetic_and_provenance(tmp_path: Path) -> None:
    result = compare_runs([A, B[:8]], make_lookup(tmp_path), ["oos_sharpe"])
    assert result["runs"] == [
        {"run_id": A, "labels": ["quick"]},
        {"run_id": B, "labels": ["quick"]},
    ]
    cells = result["metrics"]["oos_sharpe"]
    assert cells[0]["diff"]["value"] == 0
    assert cells[0]["ratio"]["value"] == 1
    assert cells[1]["value"]["value"] == 1.2
    assert cells[1]["diff"]["value"] == pytest.approx(0.4)
    assert cells[1]["ratio"]["value"] == pytest.approx(1.5)
    for operation in ("diff", "ratio"):
        fact = cells[1][operation]
        assert fact["run_ids"] == [A, B]
        assert fact["basis"] == "computed by alpha results compare from stored facts"
        assert fact["reason"] is None
        assert {"value", "run_id", "metric", "basis", "reason"} <= fact.keys()


def test_null_and_mixed_basis(tmp_path: Path) -> None:
    result = compare_runs([A, B], make_lookup(tmp_path))
    assert list(result["metrics"]) == list(DEFAULT_METRICS)
    for cell in result["metrics"]["benchmark_sharpe"]:
        for operation in ("value", "diff", "ratio"):
            assert cell[operation]["value"] is None
            assert "no benchmark bars" in cell[operation]["reason"]
    assert any(
        A in warning and B in warning and "full_sample_total_return" in warning
        for warning in result["warnings"]
    )


@pytest.mark.parametrize(
    "base,other", [(0, 2), (float("inf"), 2), (2, float("nan")), (1e-308, 1e308)]
)
def test_unavailable_ratio(base: float, other: float) -> None:
    def lookup(run_id, metric):
        return {
            "value": base if run_id == A else other,
            "run_id": run_id,
            "metric": metric,
            "basis": "test",
            "reason": None,
            "labels": [],
        }

    result = compare_runs([A, B], lookup, ["oos_sharpe"])
    fact = result["metrics"]["oos_sharpe"][1]["ratio"]
    assert fact["value"] is None
    assert fact["reason"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("ids", [[A], [A] * 9])
def test_compare_run_bounds(tmp_path: Path, ids: list[str]) -> None:
    with pytest.raises(SpineError, match="2 to 8"):
        compare_runs(ids, make_lookup(tmp_path))


def test_compare_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_lookup(tmp_path)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(results_app, ["compare", A, B, "--metric", "oos_sharpe", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["metrics"]["oos_sharpe"][1]["diff"]["value"] == pytest.approx(
        0.4
    )
    human = CliRunner().invoke(results_app, ["compare", A, B, "--metric", "oos_sharpe"])
    assert human.exit_code == 0
    assert "quick" in human.stdout and "diff" in human.stdout and A in human.stdout
