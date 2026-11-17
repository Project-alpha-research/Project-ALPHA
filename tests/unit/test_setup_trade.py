"""Trade publication, costs, controls and citable counted trials."""

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import results_cmds, setup_cmds
from alpha_cli.spine import setup_trade
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.facts import METRIC_UNITS
from alpha_cli.spine.setup_costs import setup_costs
from alpha_cli.spine.stores import ResolvedAsset
from alpha_cli.spine.trial_reader import spine_snapshot
from tests.unit.test_setup_study import make_find, snapshot


def make_trade_find(
    home: Path, exits: str = 'time_bars=2\nstop="5 %"\ntarget="10 %"'
) -> dict[str, Any]:
    make_find(home)
    path = home / "spec.toml"
    path.write_text(path.read_text() + "[exit]\n" + exits + "\n")
    return setup_cmds.run_find(path, home=home)


def test_publication_costs_facts_repeat_and_exit_identity(tmp_path: Path) -> None:
    found = make_trade_find(tmp_path)
    before = snapshot(Path(found["folder"]))
    out = setup_trade.run_trade(found["find_id"], home=tmp_path)
    assert (
        out["trade_id"]
        == hashlib.sha256((found["find_id"] + "|setup-trade-1").encode()).hexdigest()[:16]
    )
    assert out["pooled"]["trades"] == 4
    assert out["pooled"]["mean"] == pytest.approx(0.1 - 0.0006)
    assert out["pooled"]["hit_rate"] == pytest.approx(1)
    assert out["pooled"]["profit_factor"] is None
    assert out["pooled"]["reasons"]["profit_factor"] == "no losses"
    assert out["reading"].startswith("Too few trades (4)")
    assert out["pooled"]["drift_mean"] == pytest.approx(out["pooled"]["mean"])
    assert out["pooled"]["random_date_p"] == pytest.approx(1)
    rows = pl.read_parquet(Path(out["folder"]) / "trades.parquet")
    assert rows.height == 4 and rows["reason"].to_list() == ["target"] * 4
    assert rows["r_multiple"].to_list() == pytest.approx([1.988] * 4)
    prior = snapshot(Path(out["folder"]))
    repeat = setup_trade.run_trade(found["find_id"], home=tmp_path)
    assert "repeat" in repeat["labels"] and prior == snapshot(Path(out["folder"]))
    viewed = setup_cmds.run_find(tmp_path / "spec.toml", home=tmp_path)
    assert "outcomes-viewed" in viewed["labels"] and "outcomes-not-viewed" not in viewed["labels"]
    assert before == snapshot(Path(found["folder"]))
    for metric, unit in (
        ("setup_trades", "count"),
        ("setup_trade_mean_net_return", "fraction"),
        ("setup_trade_hit_rate", "fraction"),
        ("setup_trade_mean_bars_held", "ratio"),
        ("setup_trade_excess_over_drift", "fraction"),
        ("setup_trade_random_date_p", "fraction"),
        ("setup_trade_mean_r", "ratio"),
    ):
        assert METRIC_UNITS[metric] == unit
        assert (
            results_cmds.fact_lookup(tmp_path)(out["trade_id"], metric)["run_id"] == out["trade_id"]
        )
    path = tmp_path / "spec.toml"
    path.write_text(path.read_text().replace("time_bars=2", "time_bars=3"))
    changed = setup_cmds.run_find(path, home=tmp_path)
    next_out = setup_trade.run_trade(changed["find_id"], home=tmp_path)
    assert next_out["trade_id"] != out["trade_id"]
    trials = [r for r in spine_snapshot(tmp_path).records if r.kind == "setup_trade"]
    assert [r.counts_for_deflation for r in trials] == [True, False, True]
    assert {r.family_id for r in trials} == {"setup:inspect matches"}


def test_market_costs(tmp_path: Path) -> None:
    stock = setup_costs(ResolvedAsset("SPY", "home", tmp_path, "alpaca", False))
    crypto = setup_costs(ResolvedAsset("BTC/USDT", "home", tmp_path, "binance", False))
    assert (stock.fee_bps, stock.slippage_bps) == pytest.approx((1, 2))
    assert (crypto.fee_bps, crypto.slippage_bps) == pytest.approx((10, 5))
    unknown = setup_costs(ResolvedAsset("X", "home", tmp_path, "unknown", False))
    assert unknown == crypto


@pytest.mark.parametrize("code", ["FIND_NOT_FOUND", "SPEC_HAS_NO_EXIT", "DATA_CHANGED_SINCE_FIND"])
def test_errors(tmp_path: Path, code: str) -> None:
    found = make_find(tmp_path) if code == "SPEC_HAS_NO_EXIT" else make_trade_find(tmp_path)
    if code == "DATA_CHANGED_SINCE_FIND":
        from alpha_data.store import ParquetStore

        store = ParquetStore(tmp_path / "store")
        store.write_bars(
            "SPY", store.read_bars("SPY").with_columns((pl.col("volume") + 1).alias("volume"))
        )
    with pytest.raises(SpineError) as caught:
        setup_trade.run_trade(
            "missing" if code == "FIND_NOT_FOUND" else found["find_id"], home=tmp_path
        )
    assert caught.value.payload["code"] == code


def test_command_and_manifest_last(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alpha_core.atomic import write_text

    found = make_trade_find(tmp_path)
    writes: list[str] = []

    def record(path: Path, text: str) -> None:
        if path.name == "manifest.json":
            assert {p.name for p in path.parent.iterdir()} == {
                "trades.parquet",
                "summary.json",
                "trades.png",
            }
        writes.append(path.name)
        write_text(path, text)

    monkeypatch.setattr(setup_trade, "write_text", record)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(setup_cmds.setup_app, ["trade", found["find_id"], "--json"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    assert writes == ["summary.json", "manifest.json"]
    for command in (
        ["cite", out["trade_id"], "setup_trade_mean_net_return", "--json"],
        ["show", out["trade_id"], "--json"],
    ):
        result = runner.invoke(results_cmds.results_app, command)
        assert result.exit_code == 0, result.output


def test_seeded_null_calibration_and_planted_effect() -> None:
    from alpha_cli.spine.setup_trade import trade_controls

    rng = np.random.default_rng(141)
    values = rng.normal(0, 0.01, 300)
    cache = {
        "X": {
            i: dict(
                entry_index=i + 1,
                exit_index=i + 1,
                net_return=float(v),
                complete=True,
                reason="time",
            )
            for i, v in enumerate(values)
        }
    }
    ps = []
    for i in range(150):
        value = float(values[rng.integers(len(values))])
        result = trade_controls(cache, {"X": [value]}, {"X": 1}, f"null-{i}", tested=True)
        ps.append(result["pooled"]["random_date_p"])
    # Binomial(150, .10): mean 15, SD sqrt(13.5); a loose four-SD count interval.
    assert 1 <= sum(p <= 0.1 for p in ps) <= 30
    planted = trade_controls(cache, {"X": [0.2] * 5}, {"X": 5}, "planted", tested=True)
    assert planted["pooled"]["random_date_p"] <= 0.01


@pytest.mark.parametrize(
    "n,p,excess,labels,outcome",
    [
        (29, 0.001, 0.01, [], "inconclusive"),
        (30, 0.05, 0.01, [], "supported (exploratory, not confirmed)"),
        (30, 0.05, 0.01, ["halves-disagree"], "not supported"),
        (30, None, None, ["no-random-control"], "not supported"),
        (30, 0.1, 0.01, [], "not supported"),
        (30, 0.01, -0.01, [], "not supported"),
    ],
)
def test_readings(
    n: int, p: float | None, excess: float | None, labels: list[str], outcome: str
) -> None:
    from alpha_cli.spine.setup_controls import trade_reading

    sentence, result = trade_reading(
        dict(
            trades=n,
            mean=0.02,
            drift_mean=0.01,
            random_date_p=p,
            excess=excess,
            hit_rate=0.6,
            mean_bars_held=5,
        ),
        labels,
    )
    assert result == outcome
    assert not any(word in sentence for word in ("edge", "profitable", "works", "signal"))
    if outcome == "not supported":
        assert sentence.endswith("No evidence the setup adds anything with these exits.")
    if outcome.startswith("supported"):
        assert "not confirmed on reserved data" in sentence


def test_control_occupancy_weights_and_unavailable_pattern_levels() -> None:
    from alpha_cli.spine.setup_exits import PATTERN_LEVEL_REASON
    from alpha_cli.spine.setup_trade import _draw_means, trade_controls

    cache = {
        "X": {
            i: dict(
                entry_index=i + 1,
                exit_index=1000,
                net_return=float(i),
                complete=True,
                reason="time",
            )
            for i in range(30)
        }
    }
    means = _draw_means(cache["X"], 2, "occupancy")
    # First of a spaced pair must be <=18; later entries are skipped even if higher-returning.
    assert means.max() <= 18
    result = trade_controls(
        cache, {"X": [1.0]}, {"X": 2}, "levels", tested=True, control_reason=PATTERN_LEVEL_REASON
    )
    assert result["pooled"]["random_date_p"] is None
    assert result["pooled"]["drift_mean"] is None
    assert result["pooled"]["reasons"]["random_date_p"] == PATTERN_LEVEL_REASON
    cache["Y"] = {
        i: dict(entry_index=i + 1, exit_index=i + 1, net_return=0.0, complete=True, reason="time")
        for i in range(30)
    }
    cache["X"] = {
        i: dict(entry_index=i + 1, exit_index=i + 1, net_return=1.0, complete=True, reason="time")
        for i in range(30)
    }
    result = trade_controls(
        cache, {"X": [1.0], "Y": [0.0, 0.0]}, {"X": 1, "Y": 2}, "weights", tested=True
    )
    assert result["pooled"]["drift_mean"] == pytest.approx(1 / 3)
    assert result["pooled"]["random_date_50"] == pytest.approx(1 / 3)


def test_empty_exit_rejected_and_empty_trades(tmp_path: Path) -> None:
    found = make_trade_find(tmp_path, "")
    with pytest.raises(SpineError) as caught:
        setup_trade.run_trade(found["find_id"], home=tmp_path)
    assert caught.value.payload["code"] == "SPEC_HAS_NO_EXIT"
    found = make_trade_find(tmp_path, 'stop="100"')
    out = setup_trade.run_trade(found["find_id"], home=tmp_path)
    assert out["pooled"]["invalid"] == 4
    assert out["pooled"]["trades"] == 0
    assert {"no-time-exit", "no-random-control"} <= set(out["labels"])
    assert all(f["value"] is not None or f["reason"] for f in out["facts"])


def test_trade_failure_does_not_publish_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli.spine import setup_trade_figure

    found = make_trade_find(tmp_path)

    def broken(**kwargs: Any) -> bytes:
        raise OSError("figure failed")

    monkeypatch.setattr(setup_trade_figure, "draw_trades", broken)
    with pytest.raises(SpineError) as caught:
        setup_trade.run_trade(found["find_id"], home=tmp_path)
    assert caught.value.payload["code"] == "TRADE_FAILED"
    assert not list((tmp_path / "setup-trades").glob("*/manifest.json"))


def test_halves_have_own_drift_and_labels() -> None:
    from alpha_cli.spine.setup_controls import trade_labels, trade_report
    from tests.unit.test_setup_exits import spec

    rows = [
        dict(
            asset="X",
            candidate_id=i,
            entry_ts=i,
            net_return=v,
            complete=True,
            bars_held=1,
            r_multiple=None,
            reason="time",
            both_touched=0,
        )
        for i, v in [(20, 0.05), (50, -0.05)]
    ]
    cache = {
        "X": {
            i: dict(
                entry_index=i,
                entry_ts=i,
                exit_index=i,
                net_return=0.0 if i < 50 else 0.1,
                complete=True,
                reason="time",
            )
            for i in range(100)
        }
    }
    result = trade_report(rows, cache, "halves")
    halves = result["pooled"]["stability"]
    assert halves["first"]["drift_mean"] == pytest.approx(0)
    assert halves["second"]["drift_mean"] == pytest.approx(0.1)
    assert halves["first"]["random_date_p"] is None
    result["pooled"]["skipped"] = 1
    labels = trade_labels(
        {"labels": ["exploratory", "daily-only", "outcomes-not-viewed"]},
        result["pooled"],
        spec(stop="5 %"),
        1,
        2,
    )
    assert {
        "halves-disagree",
        "many-skipped",
        "no-time-exit",
        "single-asset",
        "too-few-occurrences",
        "daily-only",
    } <= set(labels)
    assert "outcomes-not-viewed" not in labels


def test_named_reference_levels_are_frozen_at_trigger_close(tmp_path: Path) -> None:
    found = make_trade_find(tmp_path, 'time_bars=2\nstop="base"\ntarget="10 %"')
    out = setup_trade.run_trade(found["find_id"], home=tmp_path)
    rows = pl.read_parquet(Path(out["folder"]) / "trades.parquet")
    assert rows["stop"].to_list() == pytest.approx([99.0] * 4)
    assert rows["reason"].to_list() == ["stop"] * 4
    assert out["pooled"]["drift_mean"] == pytest.approx(-0.01 - 0.0006)
    path = tmp_path / "spec.toml"
    path.write_text(path.read_text().replace('stop="base"', 'stop="low"'))
    assert setup_cmds.run_find(path, home=tmp_path)["find_id"] != found["find_id"]


@pytest.mark.parametrize(
    "source,expected", [("alpaca", 0.0994), ("binance", 0.097), ("unknown", 0.097)]
)
def test_actual_market_net_returns(tmp_path: Path, source: str, expected: float) -> None:
    from alpha_cli.spine.setup_costs import asset_costs, round_trip
    from alpha_cli.spine.setup_exits import prepare_exits, simulate
    from alpha_data.store import ParquetStore
    from tests.unit.test_setup_exits import bars, spec

    ParquetStore(tmp_path / "store").write_provenance(
        "X", source=source, adapter_version="1", parser_version="1"
    )
    used, labels = asset_costs(tmp_path, ["X"])
    assert labels == (["costs-assumed-high"] if source == "unknown" else [])
    costs = setup_costs(ResolvedAsset("X", "home", tmp_path, source, False))
    assert used["X"] == costs.model_dump()
    prepared = prepare_exits(spec(target="10 %"), bars([(100, 101, 99, 100), (100, 111, 99, 105)]))
    assert simulate(prepared, 1, round_trip(costs.model_dump()))["net_return"] == pytest.approx(
        expected
    )
