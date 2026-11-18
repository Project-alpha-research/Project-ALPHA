"""Facts quote stored fields and explicitly explain missing artifacts."""

import json
from pathlib import Path

import pytest

from alpha_cli.spine.facts import METRICS, build_facts
from alpha_cli.toolbox.registry import METRIC_OUTPUTS


def test_facts_are_stored_values_and_missing_file_is_null(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"oos_metrics": {"sharpe": 1.23456789}, "spine": {"labels": ["quick"]}})
    )
    (tmp_path / "diagnostics.json").write_text(
        json.dumps({"benchmark": {"sharpe": 2.345, "basis": "buy and hold, same bars, no costs"}})
    )
    facts = {item["metric"]: item for item in build_facts(tmp_path)}
    # Run facts are every documented metric except those the investigation tools store.
    assert set(facts) == set(METRICS) - set(METRIC_OUTPUTS)
    assert set(METRIC_OUTPUTS) < set(METRICS)
    assert facts["oos_sharpe"]["value"] == pytest.approx(1.23456789)
    assert facts["oos_sharpe"]["source"] == "manifest.json:oos_metrics.sharpe"
    assert facts["oos_sharpe"]["reason"] is None
    assert facts["benchmark_sharpe"]["value"] == pytest.approx(2.345)
    (tmp_path / "diagnostics.json").unlink()
    facts = {item["metric"]: item for item in build_facts(tmp_path)}
    assert facts["benchmark_sharpe"]["value"] is None
    assert facts["benchmark_sharpe"]["reason"]
    assert facts["oos_sharpe"]["labels"] == ["quick"]


def test_older_ledger_has_explained_unknown_flag_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from alpha_cli.results_cmds import results_app
    from alpha_cli.spine.ledger import append_trial

    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    append_trial(tmp_path, {"run_id": "older", "labels": []})
    result = CliRunner().invoke(results_app, ["--json"])
    row = json.loads(result.stdout)["items"][0]
    assert row["flags_count"] is None
    assert row["reasons"]["flags_count"]
    assert row["reasons"]["benchmark_sharpe"]


def test_corrupt_store_registry_has_json_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import typer
    from typer.testing import CliRunner

    from alpha_cli.test_cmds import test_rule

    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    (tmp_path / "stores.toml").write_text("broken = 42")
    root = typer.Typer()
    root.command()(test_rule)
    result = CliRunner().invoke(
        root, ["--rule", "breakout", "--param", "window=20", "--asset", "SPY", "--json"]
    )
    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "TEST_FAILED"
    assert "alpha test" in error["next"]


def test_trial_count_basis_is_ledger_not_returns(tmp_path: Path) -> None:
    (tmp_path / "diagnostics.json").write_text(
        json.dumps(
            {"trials": {"basis": "walk-forward returns and sensitivity Sharpes", "total_trials": 3}}
        )
    )
    count = next(f for f in build_facts(tmp_path) if f["metric"] == "total_trials")
    assert count["basis"] == "ledger at the time of the run"


@pytest.mark.parametrize("dsr", [None, 0.97, "n/a", [1]])
def test_null_or_bare_number_in_place_of_an_object_is_a_null_fact(
    tmp_path: Path, dsr: object
) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"dsr": dsr, "verdict": None, "oos_metrics": 1.5, "spine": {"labels": []}})
    )
    (tmp_path / "diagnostics.json").write_text(
        json.dumps({"benchmark": {"sharpe": None, "reasons": "broken"}, "trials": 3})
    )
    facts = {item["metric"]: item for item in build_facts(tmp_path)}
    for metric in ("dsr", "verdict", "oos_sharpe", "benchmark_sharpe", "trial_dsr"):
        assert facts[metric]["value"] is None
        assert "is unavailable" in facts[metric]["reason"]
    assert facts["dsr"]["reason"] == "manifest.json:dsr.dsr is unavailable"
