"""Investigation tools: outputs outside the run directory, sourced facts, counted ledger rows."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import typer
from typer.testing import CliRunner

from alpha_cli.results_cmds import results_app
from alpha_cli.spine import tool_inputs, tools
from alpha_cli.spine.errors import SpineError, tool_error
from alpha_cli.spine.ledger import append_trial, read_trials
from alpha_cli.tool_cmds import tool_app
from alpha_core import DataError

RUN = "0123456789abcdef"
START = datetime(2020, 1, 1, tzinfo=UTC)


def _series(home: Path, n: int = 700, always_long: bool = False) -> tool_inputs.RunSeries:
    """A long/flat strategy on a market with a calm half and a turbulent half."""
    rng = np.random.default_rng(5)
    market = np.r_[rng.normal(0.0008, 0.005, n // 2), rng.normal(0.0, 0.03, n - n // 2)]
    held = ((np.arange(n) // 25) % 2 == 0) | always_long
    closes = 100.0 * np.cumprod(1.0 + np.r_[0.0, market])
    equity = 1e6 * np.cumprod(1.0 + np.r_[0.0, np.where(held, market, 0.0)])
    dates = tuple(START + timedelta(days=i) for i in range(n + 1))
    rdir = home / "runs" / RUN
    rdir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "command": "validate",
        "metadata": {"symbol": "SPY"},
        "spine": {"test_id": "t1", "name": "demo", "store": "home", "labels": ["all-in", "quick"]},
    }
    (rdir / "manifest.json").write_text(json.dumps(manifest))
    return tool_inputs.RunSeries(
        home=home,
        run_id=RUN,
        manifest=manifest,
        asset="SPY@home",
        ppy=365,
        dates=dates,
        equity=tuple(float(v) for v in equity),
        closes=dict(zip(dates, (float(v) for v in closes), strict=True)),
    )


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    series = _series(tmp_path)
    monkeypatch.setattr(tools, "load_run", lambda home, run_id: series)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    return tmp_path


def _other_asset(monkeypatch: pytest.MonkeyPatch, home: Path, keep: int) -> None:
    """A second asset, QQQ, with bars on every ``keep``-th day only."""
    series = _series(home)
    monkeypatch.setattr(
        tool_inputs,
        "resolve_asset",
        lambda asset, data_dir: SimpleNamespace(symbol="QQQ", store_name="home", data_dir=home),
    )
    seen: dict[str, Any] = {}

    def load_bars(symbol: str, *, data_dir: Path, as_of: datetime) -> tuple[list[Any], None]:
        seen.update(symbol=symbol, as_of=as_of)
        return [
            SimpleNamespace(ts=date, close=series.closes[date] * 2) for date in series.dates[::keep]
        ], None

    monkeypatch.setattr(tool_inputs._runner, "load_bars", load_bars)
    monkeypatch.setattr(tool_inputs, "_seen", seen, raising=False)


def test_attribution_is_stored_outside_the_run_and_counted(home: Path) -> None:
    before = sorted(path.name for path in (home / "runs" / RUN).iterdir())
    output = tools.attribution(home, RUN)
    assert sorted(path.name for path in (home / "runs" / RUN).iterdir()) == before
    assert output["file"].startswith(f"diagnostics/{RUN}/attribution-")
    folder = home / "diagnostics" / RUN
    assert [path.name for path in folder.iterdir()] == [Path(output["file"]).name]  # no temp file
    stored = json.loads((home / output["file"]).read_text())
    assert stored == {k: v for k, v in output.items() if k not in ("file", "trials_total")}
    assert stored["tool"] == "attribution"
    assert stored["params"] == {"benchmark": "SPY@home", "risk_free": 0.0}
    assert stored["labels"] == ["all-in", "quick", "benchmark-is-same-asset"]
    assert datetime.fromisoformat(stored["recorded_at"]).tzinfo is not None
    assert 0.3 < stored["result"]["beta"] < 0.7  # held about half of the time
    assert stored["result"]["join"]["run_bars_dropped"] == 0
    assert stored["result"]["periods_per_year"] == 365
    assert [fact["metric"] for fact in stored["facts"]] == [
        "market_beta",
        "market_alpha_annual",
        "market_alpha_p",
        "market_r_squared",
    ]
    for fact in stored["facts"]:
        assert set(fact) == {"metric", "value", "run_id", "basis", "source", "labels", "reason"}
        assert fact["run_id"] == RUN
        assert fact["source"].startswith(output["file"] + ":result.")
        assert fact["reason"] is None
        assert fact["labels"] == stored["labels"]
        assert "Newey-West" in fact["basis"]
        assert fact["value"] == stored["result"][fact["source"].rsplit(".", 1)[1]]
    row = read_trials(home)[-1]
    assert row["kind"] == "tool:attribution"
    assert (row["run_id"], row["test_id"], row["verdict"]) == (RUN, "t1", None)
    assert row["tool_output"] == output["file"]
    assert row["total_trials"] == output["trials_total"] == 1
    again = tools.attribution(home, RUN)
    assert again["file"] == output["file"]
    assert again["trials_total"] == 2  # every look counts
    assert "repeat" in read_trials(home)[-1]["labels"]


def test_cross_asset_join_reports_dropped_bars(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _other_asset(monkeypatch, home, keep=2)
    output = tools.attribution(home, RUN, "QQQ")
    assert output["params"]["benchmark"] == "QQQ@home"
    assert "benchmark-is-same-asset" not in output["labels"]
    assert output["result"]["join"] == {
        "run_bars": 701,
        "other_bars_in_run_window": 351,
        "shared_bars": 351,
        "run_bars_dropped": 350,
        "other_bars_dropped": 0,
    }
    assert output["result"]["n"] == 350
    assert output["result"]["periods_per_year"] == 183  # every second day, inferred from dates
    assert tool_inputs._seen == {"symbol": "QQQ", "as_of": _series(home).dates[-1]}
    assert output["file"] != tools.attribution(home, RUN)["file"]


def test_too_few_shared_bars(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _other_asset(monkeypatch, home, keep=12)
    with pytest.raises(SpineError) as caught:
        tools.attribution(home, RUN, "QQQ")
    assert caught.value.payload["code"] == "TOO_FEW_BARS"
    assert "share 59 bar timestamps; 61 are needed" in caught.value.payload["message"]
    assert not (home / "diagnostics").exists()
    assert read_trials(home) == []


def test_regimes_split_is_causal_with_a_hindsight_section(home: Path) -> None:
    output = tools.regimes(home, RUN)
    result = output["result"]
    assert output["labels"] == [
        "all-in",
        "quick",
        "parameters-fit-in-sample",
        "benchmark-is-same-asset",
    ]
    assert output["params"] == {"market": "SPY@home", "k": 2, "seed": 0}
    assert result["hindsight"]["labels"] == ["hindsight"]
    assert "smoothed" in result["hindsight"]["basis"]
    assert "bar before it" in result["split"]["basis"]
    assert (result["split"]["unlabelled_bars"], result["hindsight"]["unlabelled_bars"]) == (1, 0)
    calm, turbulent = result["split"]["regimes"]
    assert (calm["name"], turbulent["name"]) == ("calm", "turbulent")
    assert turbulent["share_of_time"] == pytest.approx(0.5, abs=0.05)
    assert result["model"]["annual_volatility"][1] == pytest.approx(0.03 * 365**0.5, rel=0.2)
    series = result["series"]
    assert len(series["dates"]) == len(series["causal_state"]) == 700
    assert series["dates"][0] == (START + timedelta(days=1)).isoformat()
    assert series["causal_state"][0] == -1
    assert np.mean(np.array(series["hindsight_state"])[:350] == 0) > 0.95
    facts = {fact["metric"]: fact for fact in output["facts"]}
    assert facts["regime_turbulent_share_of_time"]["value"] == turbulent["share_of_time"]
    assert facts["regime_turbulent_share_of_return"]["value"] == turbulent["share_of_log_return"]
    assert read_trials(home)[-1]["kind"] == "tool:regimes"


def test_regime_flags_and_null_fact() -> None:
    rows = [
        {"name": "calm", "share_of_time": 0.3, "share_of_log_return": 0.85},
        {"name": "turbulent", "share_of_time": 0.7, "share_of_log_return": 0.15},
    ]
    assert tool_inputs.regime_flags(rows) == [
        {
            "flag": "return-concentrated-in-regime",
            "detail": "85% of the strategy's total log return was earned in the calm regime, "
            "which covers 30% of bars.",
        }
    ]
    lopsided = [
        {"name": "calm", "share_of_time": 0.04, "share_of_log_return": None},
        {"name": "turbulent", "share_of_time": 0.96, "share_of_log_return": None},
    ]
    assert [flag["flag"] for flag in tool_inputs.regime_flags(lopsided)] == ["one-regime-dominates"]
    assert tool_inputs.regime_flags([{**rows[1], "share_of_log_return": 0.79}]) == []


def test_regimes_that_do_not_converge(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tools.regime_model,
        "volatility_regimes",
        lambda returns, k, seed: {"converged": False, "reason": "the optimiser did not converge"},
    )
    result = CliRunner().invoke(tool_app, ["regimes", RUN, "--k", "3", "--json"])
    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "MODEL_DID_NOT_CONVERGE"
    assert "3-regime model did not converge on SPY@home" in error["message"]
    assert "--k 2" in error["next"]
    assert read_trials(home) == []


@pytest.mark.parametrize("on", ["returns", "equity"])
def test_changepoints_map_back_to_dates(
    home: Path, monkeypatch: pytest.MonkeyPatch, on: str
) -> None:
    # Always in the market: a long/flat rule's own entries and exits are change points too.
    series = _series(home, always_long=True)
    monkeypatch.setattr(tools, "load_run", lambda home, run_id: series)
    output = tools.changepoints(home, RUN, on)
    result = output["result"]
    assert output["labels"] == ["all-in", "quick", "hindsight"]
    assert output["params"] == {"model": "rbf", "min_size": 20, "max_points": 8, "on": on}
    assert output["facts"][0]["value"] == len(result["breaks"]) >= 1
    for item in result["breaks"]:
        assert item["date"] == series.dates[item["index"] + (on == "returns")].isoformat()
    segments = result["segments"]
    assert segments[0]["start_date"] == series.dates[on == "returns"].isoformat()
    assert segments[-1]["end_date"] == series.dates[-1].isoformat()
    assert [later["start_date"] for later in segments[1:]] == [b["date"] for b in result["breaks"]]
    assert sum(segment["bars"] for segment in segments) == 700 + (on == "equity")
    if on == "returns":  # the planted volatility shift at the middle of the sample
        assert any(abs(item["index"] - 350) <= 30 for item in result["breaks"])
        returns = np.diff(series.equity) / np.array(series.equity[:-1])
        first = returns[: result["breaks"][0]["index"]]
        assert segments[0]["annual_return"] == pytest.approx(first.mean() * 365)
        assert segments[0]["annual_volatility"] == pytest.approx(first.std(ddof=1) * 365**0.5)
        assert segments[-1]["annual_volatility"] > 2 * segments[0]["annual_volatility"]


def test_command_output_and_structured_errors(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    printed = runner.invoke(tool_app, ["regimes", RUN, "--json"])
    assert printed.exit_code == 0, printed.output
    payload = json.loads(printed.stdout)
    assert "series" not in payload["result"]
    assert "series" in json.loads((home / payload["file"]).read_text())["result"]
    text = runner.invoke(tool_app, ["attribution", RUN]).stdout
    assert "market_beta = " in text
    assert "How much the strategy moves" in text
    assert "Saved: diagnostics/" in text
    bad = runner.invoke(tool_app, ["changepoints", RUN, "--on", "price", "--json"])
    assert bad.exit_code == 1
    assert json.loads(bad.stdout)["error"]["known"] == ["returns", "equity"]

    def missing(home: Path, run_id: str) -> None:
        raise DataError("asset 'NOPE' not found; stores searched: home")

    monkeypatch.setattr(tools, "load_run", missing)
    unknown = runner.invoke(tool_app, ["attribution", RUN, "--json"])
    assert unknown.exit_code == 1
    error = json.loads(unknown.stdout)["error"]
    assert (error["code"], error["known"]) == ("UNKNOWN_ASSET", ["home"])
    assert error["next"].startswith("Run alpha tool")


def test_tool_error_codes() -> None:
    assert tool_error(ValueError("needs at least 60 aligned bars, got 5")).payload["code"] == (
        "TOO_FEW_BARS"
    )
    assert tool_error(ValueError("unknown store 'x'"), ["home"]).payload["known"] == ["home"]
    assert tool_error(ValueError("the strategy returns do not vary")).payload["code"] == (
        "TOOL_FAILED"
    )
    original = SpineError("UNKNOWN_RUN", "m", "n")
    assert tool_error(original) is original


def test_unknown_run_and_runs_that_are_not_rule_tests(tmp_path: Path) -> None:
    with pytest.raises(SpineError) as caught:
        tool_inputs.load_run(tmp_path, RUN)
    assert caught.value.payload["code"] == "UNKNOWN_RUN"
    rdir = tmp_path / "runs" / RUN
    rdir.mkdir(parents=True)
    (rdir / "manifest.json").write_text(json.dumps({"command": "validate"}))
    with pytest.raises(SpineError) as caught:
        tool_inputs.load_run(tmp_path, RUN)
    assert caught.value.payload["code"] == "NOT_A_RULE_TEST"
    assert "alpha results" in caught.value.payload["next"]


def test_show_lists_outputs_and_cite_needs_a_choice_between_two(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = typer.Typer()
    app.add_typer(results_app, name="results")
    runner = CliRunner()
    none = runner.invoke(app, ["results", "cite", RUN, "market_beta", "--json"])
    assert json.loads(none.stdout)["error"]["code"] == "NO_TOOL_OUTPUT"
    assert f"alpha tool attribution {RUN}" in json.loads(none.stdout)["error"]["next"]
    own = tools.attribution(home, RUN)
    one = runner.invoke(app, ["results", "cite", RUN, "market_beta", "--json"])
    assert one.exit_code == 0, one.output
    assert json.loads(one.stdout) == own["facts"][0]
    plain = runner.invoke(app, ["results", "cite", RUN, "market_beta"]).stdout
    assert plain.startswith(f"{own['result']['beta']} [{RUN}:market_beta] (")
    _other_asset(monkeypatch, home, keep=2)
    other = tools.attribution(home, RUN, "QQQ")
    tools.changepoints(home, RUN)
    ids = [Path(item["file"]).stem.rsplit("-", 1)[1] for item in (own, other)]
    ambiguous = runner.invoke(app, ["results", "cite", RUN, "market_beta", "--json"])
    assert ambiguous.exit_code == 1
    error = json.loads(ambiguous.stdout)["error"]
    assert error["code"] == "AMBIGUOUS_TOOL_OUTPUT"
    assert sorted(error["known"]) == sorted(ids)
    assert "--tool-output" in error["next"]
    chosen = runner.invoke(
        app, ["results", "cite", RUN, "market_beta", "--tool-output", ids[1], "--json"]
    )
    assert json.loads(chosen.stdout)["value"] == other["result"]["beta"]
    wrong = runner.invoke(
        app, ["results", "cite", RUN, "market_beta", "--tool-output", "ffffffff", "--json"]
    )
    assert json.loads(wrong.stdout)["error"]["code"] == "NO_TOOL_OUTPUT"
    assert sorted(json.loads(wrong.stdout)["error"]["known"]) == sorted(ids)
    count = runner.invoke(app, ["results", "cite", RUN, "changepoint_count", "--json"])
    assert json.loads(count.stdout)["metric"] == "changepoint_count"
    shown = json.loads(runner.invoke(app, ["results", "show", RUN, "--json"]).stdout)["runs"][0]
    assert [item["tool"] for item in shown["tools"]] == [
        "attribution",
        "attribution",
        "changepoints",
    ]
    assert set(shown["tools"][0]) == {"tool", "id", "params", "recorded_at", "file", "labels"}
    assert [item["file"] for item in shown["tools"][:2]] == [own["file"], other["file"]]
    listing = json.loads(runner.invoke(app, ["results", "--json"]).stdout)
    assert [item["kind"] for item in listing["items"]] == [
        "tool:changepoints",
        "tool:attribution",
        "tool:attribution",
    ]
    assert "investigation-tool row" in listing["items"][0]["reasons"]["oos_sharpe"]


def test_old_ledger_rows_without_kind_read_as_rule_tests(tmp_path: Path) -> None:
    path = tmp_path / "ledger" / "trials.jsonl"
    path.parent.mkdir()
    old = {"schema": "AlphaTrialV1", "trial_index": 1, "total_trials": 1, "run_id": RUN}
    path.write_text(json.dumps({**old, "labels": []}) + "\n")
    assert read_trials(tmp_path)[0]["kind"] == "rule_test"
    tool = append_trial(
        tmp_path, {"kind": "tool:regimes", "run_id": RUN, "tool_output": "a.json", "labels": []}
    )
    assert (tool["trial_index"], tool["labels"]) == (2, [])  # a first tool look is not a repeat
    rule = append_trial(tmp_path, {"run_id": RUN, "labels": []})
    assert (rule["kind"], rule["labels"], rule["total_trials"]) == ("rule_test", ["repeat"], 3)
    other = append_trial(
        tmp_path, {"kind": "tool:regimes", "run_id": RUN, "tool_output": "b.json", "labels": []}
    )
    assert other["labels"] == []
    assert [row["kind"] for row in read_trials(tmp_path)] == [
        "rule_test",
        "tool:regimes",
        "rule_test",
        "tool:regimes",
    ]
