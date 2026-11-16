"""Hand-built gap, causal membership and waiting-position contracts."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from alpha_cli import _rdagent_judge as judge
from alpha_cli import _rdagent_universe as universes
from alpha_core import DataError


def panel(n: int = 80) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "date": date(2020, 12, 1) + timedelta(days=i),
                "instrument": f"C{j}",
                "open": 100.0 + i + j,
                "close": 100.0 + i + j,
                "high": 200.0 + i,
                "low": 1.0,
                "volume": 100.0,
                "quote_volume": 10000.0,
            }
            for i in range(n)
            for j in range(6)
        ]
    )


def test_gap_is_valid_but_disorder_and_duplicates_are_not() -> None:
    bars = panel().filter(
        ~(
            (pl.col("instrument") == "C0")
            & pl.col("date").is_between(date(2021, 1, 2), date(2021, 1, 4))
        )
    )
    assert judge.validate_panel(bars).height == bars.height
    with pytest.raises(DataError, match="disordered"):
        judge.validate_panel(bars.reverse())
    with pytest.raises(DataError, match="overlapping"):
        judge.validate_panel(pl.concat([bars, bars.head(1)]))


def test_membership_resets_and_ignores_future() -> None:
    from alpha_cli import _rdagent_membership as membership

    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(80)]
    prices = np.ones((80, 6))
    prices[25:28, 0] = np.nan
    eligible = membership.membership(prices, days, days)
    assert not eligible[:19].any()
    assert eligible[19:25].all()
    assert not eligible[25:47, 0].any()
    assert eligible[47, 0]
    poisoned = prices.copy()
    poisoned[50:, 0] = np.nan
    assert np.array_equal(membership.membership(poisoned, days, days)[:50], eligible[:50])


def test_panel_receipt_counts_spans_without_using_them_for_membership() -> None:
    from alpha_cli import _rdagent_membership as membership

    bars = panel(50).filter(
        ~((pl.col("instrument") == "C0") & (pl.col("date") >= date(2021, 1, 1)))
    )
    bars = bars.filter(
        ~(
            (pl.col("instrument") == "C1")
            & pl.col("date").is_between(date(2020, 12, 5), date(2020, 12, 7))
        )
    )
    summary = membership.panel_summary(bars)
    assert summary["instruments"]["C1"]["missing_days"] == 3
    assert summary["instruments"]["C1"]["longest_gap"] == 3
    assert summary["instruments"]["C0"]["ends_early"] is True
    assert summary["missing_instrument_days"] == 3
    assert summary["instruments_ended_early"] == 1
    assert summary["gap_policy"]["delisting_haircut"] == pytest.approx(0.30)


def test_forward_gap_and_writeoff_labels_and_reserved_boundary() -> None:
    from alpha_cli import _rdagent_membership as membership

    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(50)]
    values = np.full((50, 2), 100.0)
    values[3:6, 0] = np.nan
    values[6:, 0] = 40.0
    values[3:, 1] = np.nan
    outcome, counts = membership.forward_returns(values, values, days, [1], [3])
    assert outcome[0] == pytest.approx([-0.6, -0.3])
    assert counts["gap_forward_returns"] == 1
    assert counts["haircut_forward_returns"] == 1
    end_days = [date(2023, 12, 20) + timedelta(days=i) for i in range(12)]
    ending = np.full((12, 1), 100.0)
    ending[4:] = np.nan
    outcome, _ = membership.forward_returns(ending, ending, end_days, [1], [4])
    assert np.isnan(outcome[0, 0])


def test_optional_universe_data_dir(tmp_path: Path) -> None:
    spec = {**universes.DEFAULT, "data_dir": str(tmp_path)}
    path = tmp_path / "universe.json"
    path.write_text(json.dumps(spec))
    assert universes.load(path)["data_dir"] == str(tmp_path)
    assert "data_dir" not in universes.validate(dict(universes.DEFAULT))
    for value in (None, 5, "", "relative/path"):
        with pytest.raises(DataError, match="data_dir"):
            universes.validate({**spec, "data_dir": value})


def test_thin_days_are_skipped_under_gap_policy() -> None:
    scores = np.tile(np.arange(6.0), (8, 1))
    outcomes = np.array([np.roll(np.arange(6.0), i % 3) for i in range(8)])
    scores[3, 2:] = np.nan
    result = judge.screen(scores, outcomes, "a" * 64, n_resamples=20, gap_policy=True)
    assert result["status"] == "OK"
    assert result["breadth_skipped_days"] == 1
    assert result["n"] == 7


def test_waiting_position_takes_resume_close_and_haircut_once() -> None:
    from alpha_cli import _rdagent_membership as membership

    account = membership.Account(["A"], fee_bps=10, slippage_bps=6)
    account.trade(0, 10.0, 100.0, date(2021, 1, 1), "open")
    account.observe(date(2021, 1, 1), np.array([100.0]))
    account.observe(date(2021, 1, 2), np.array([np.nan]))
    assert account.quantities[0] == pytest.approx(10)
    account.observe(date(2021, 1, 3), np.array([40.0]))
    assert account.quantities[0] == pytest.approx(0)
    assert account.events[-1]["price"] == pytest.approx(40 * (1 - 0.0006))
    assert account.haircuts == 0
    other = membership.Account(["A"], fee_bps=10, slippage_bps=6)
    other.trade(0, 10.0, 100.0, date(2021, 1, 1), "open")
    other.observe(date(2021, 1, 1), np.array([100.0]))
    for i in range(1, 35):
        other.observe(date(2021, 1, 1) + timedelta(days=i), np.array([np.nan]))
    assert other.haircuts == 1
    assert other.events[-1]["date"] == date(2021, 1, 31)
    assert other.events[-1]["price"] == pytest.approx(70.0)
    assert other.quantities[0] == pytest.approx(0)


def test_replay_future_poison_includes_fills_positions_and_pnl() -> None:
    bars = panel(120).filter(
        ~(
            (pl.col("instrument") == "C5")
            & pl.col("date").is_between(date(2021, 1, 5), date(2021, 1, 9))
        )
    )
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(60)]
    scores = np.tile(np.arange(6.0), (60, 1))
    cutoff = date(2021, 1, 20)
    poison = bars.with_columns(
        [
            pl.when(pl.col("date") > cutoff).then(pl.col(c) * 0.3).otherwise(pl.col(c)).alias(c)
            for c in ("open", "close", "high", "low")
        ]
    ).filter(~((pl.col("instrument") == "C5") & (pl.col("date") > cutoff)))
    clean_series: dict[str, Any] = {}
    poison_series: dict[str, Any] = {}
    judge.replay(bars, scores, days, 1, series=clean_series, gap_policy=True)
    judge.replay(poison, scores, days, 1, series=poison_series, gap_policy=True)
    for key in ("events", "positions"):
        assert [e for e in clean_series[key] if e["date"] <= cutoff] == [
            e for e in poison_series[key] if e["date"] <= cutoff
        ]
    assert [p for p in clean_series["periods"] if p.exit_ts.date() <= cutoff] == [
        p for p in poison_series["periods"] if p.exit_ts.date() <= cutoff
    ]
    # This future poison has power: it changes later fills and removes a later listing span.
    assert clean_series["events"] != poison_series["events"]
    resumed = [e for e in clean_series["events"] if e["basis"] == "resume-close"]
    assert resumed and resumed[0]["date"] == date(2021, 1, 10)


def test_worker_frame_has_null_gap_rows_only_inside_span(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "workers/rdagent/alpha_factor_data.py"
    spec = importlib.util.spec_from_file_location("gapped_data", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import pandas as pd

    # Exercise the exact frame passed to HDF without requiring the isolated worker's PyTables.
    saved: dict[Path, pd.DataFrame] = {}

    def write_hdf(frame: pd.DataFrame, path: Path, *, key: str, mode: str) -> None:
        assert key == "data" and mode == "w"
        saved[path] = frame.copy()
        path.write_bytes(b"serializer boundary")

    def read_hdf(path: Path, *, key: str) -> pd.DataFrame:
        assert key == "data"
        return saved[path]

    monkeypatch.setattr(pd.DataFrame, "to_hdf", write_hdf)
    monkeypatch.setattr(pd, "read_hdf", read_hdf)
    bars = panel(10).filter(
        ~(
            (pl.col("instrument") == "C0")
            & pl.col("date").is_in([date(2020, 12, 1), date(2020, 12, 4), date(2020, 12, 10)])
        )
    )
    source = tmp_path / "panel.parquet"
    bars.write_parquet(source)
    module.prepare(source, tmp_path / "data")
    frame = pd.read_hdf(tmp_path / "data/full/daily_pv.h5", key="data").xs("C0", level="instrument")
    assert len(frame) == 8
    assert frame.loc["2020-12-04"].isna().all()
    assert frame.index.min() == pd.Timestamp("2020-12-02")
    assert frame.index.max() == pd.Timestamp("2020-12-09")


@pytest.mark.parametrize("clock", ["daily", "weekly", "monthly"])
def test_gap_free_replay_matches_retained_legacy_engine_bytes(clock: str) -> None:
    bars = panel(100)
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(50)]
    scores = np.random.default_rng(76).normal(size=(50, 6))
    old, old_returns = judge.replay(bars, scores, days, 1, clock=clock)
    new, new_returns = judge.replay(bars, scores, days, 1, clock=clock, gap_policy=True)
    assert new_returns.tobytes() == old_returns.tobytes()
    for key in ("net", "gross", "mean_turnover", "turnover_per_rebalance", "annual_cost"):
        assert judge.canonical({key: new[key]}) == judge.canonical({key: old[key]})


def test_new_policy_end_to_end_and_old_receipt_loading(tmp_path: Path) -> None:
    from alpha_cli import _rdagent_membership as membership
    from alpha_cli import rdagent_factor_eval as ev
    from tests.unit.test_rdagent_factor_eval import fixture

    run = tmp_path / "run"
    request = fixture(run)
    _, bars, _, _ = ev._inputs(run, request)  # receipt without new fields remains readable
    bars = bars.filter(
        ~(
            (pl.col("instrument") == "C14USDT")
            & pl.col("date").is_between(date(2021, 4, 1), date(2021, 4, 4))
        )
    )
    bars = bars.filter(
        ~((pl.col("instrument") == "C13USDT") & (pl.col("date") >= date(2022, 1, 1)))
    )
    bars.write_parquet(run / "panel/panel.parquet")
    receipt = {
        **membership.panel_summary(bars),
        "panel_sha256": judge.sha((run / "panel/panel.parquet").read_bytes()),
    }
    (run / "panel/panel-receipt.json").write_text(json.dumps(receipt))
    record = ev.evaluate(run, request, run / "result.json", tmp_path / "ledger.jsonl")
    assert record["disclosures"]["missing_bars"]["instruments_ended_early"] == 1
    assert "1 instruments ended early" in record["feedback_text"]
    assert "4 instrument-days" in record["feedback_text"]
    manifest = json.loads((run / "evaluations/iter-0/series/series.json").read_bytes())
    names = [item["name"] for f in manifest["factors"] for item in f["files"]]
    assert any(name.endswith(".events.parquet") for name in names)
    assert any(name.endswith(".positions.parquet") for name in names)
    for trial in record["factors"][0]["clocks"].values():
        assert trial["status"] != "ERROR", trial
        assert trial["screen"]["breadth_skipped_days"] >= 1
        assert trial["screen"]["haircut_forward_returns"] > 0


def test_spread_holding_writes_off_before_a_late_resumption() -> None:
    from alpha_cli import _rdagent_membership as membership

    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(60)]
    prices = np.full((60, 1), 100.0)
    prices[3:40] = np.nan
    prices[40:] = 200.0
    result, counts = membership.holding_returns(prices, prices, days, [1], [45])
    assert result[0, 0] == pytest.approx(-0.3)
    assert counts["haircuts_applied"] == 1


def test_panel_end_writeoff_and_reentry_are_separate_positions() -> None:
    from alpha_cli import _rdagent_membership as membership

    account = membership.Account(["A"], fee_bps=0, slippage_bps=0)
    account.trade(0, 10.0, 100.0, date(2021, 1, 1), "open")
    account.observe(date(2021, 1, 1), np.array([100.0]))
    account.observe(date(2021, 1, 2), np.array([np.nan]), terminal=True)
    assert account.written_off_at_panel_end == 1
    assert account.cash == pytest.approx(999700)
    account.observe(date(2021, 2, 10), np.array([10.0]))
    account.trade(0, 10.0, 10.0, date(2021, 3, 1), "open")
    assert account.quantities[0] == pytest.approx(10)
    assert account.haircuts == 1


def test_gap_free_screen_and_spread_have_hand_computed_values() -> None:
    scores = np.tile(np.arange(6.0), (6, 1))
    outcomes = np.array([np.roll(np.arange(6.0), i % 3) for i in range(6)])
    result = judge.screen(scores, outcomes, "b" * 64, n_resamples=20, gap_policy=True)
    # Spearman = 1 - 6 sum(rank differences squared)/(6*(6**2-1)).
    assert result["mean_ic"] == pytest.approx((1 + 1 / 7 - 13 / 35) / 3)
    returns = np.tile(np.linspace(-0.05, 0.05, 6), (4, 1)) * np.arange(1, 5)[:, None]
    spread = judge.spread(
        scores[:4],
        returns,
        1,
        [f"C{i}" for i in range(6)],
        "b" * 64,
        horizon=7,
        n_resamples=20,
        gap_policy=True,
    )
    assert spread["mean_spread"] == pytest.approx(0.20)
    assert spread["annualized_spread"] == pytest.approx(0.20 * 365 / 7)


def test_future_poison_rejects_a_future_end_membership_twin() -> None:
    from alpha_cli import _rdagent_membership as membership

    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(60)]
    clean = np.ones((60, 6))
    poison = clean.copy()
    poison[40:, 0] = np.nan
    causal = membership.membership(clean, days, days)
    changed = membership.membership(poison, days, days)
    assert np.array_equal(causal[:40], changed[:40])
    leaky = changed & np.isfinite(poison[-1])
    assert not np.array_equal(causal[:40], leaky[:40])


def test_freeze_routes_only_panel_reads_to_universe_store(tmp_path: Path) -> None:
    from unittest.mock import patch

    from tests.unit.test_rdagent_factor_eval import _bulk_store, _publish

    store = _bulk_store(tmp_path)
    for name in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        _publish(store, name, (10.0, 11.0, 12.0, 13.0), skip=1)
    spec = {
        **universes.DEFAULT,
        "data_dir": str(tmp_path / "control"),
        "min_names": 1,
        "min_universe": 3,
    }
    source = tmp_path / "synthetic-universe.json"
    source.write_text(json.dumps(spec))
    with patch.object(judge, "configured_crypto_bulk_store", return_value=store) as reader:
        receipt = judge.freeze(tmp_path / "wrong-global-store", tmp_path / "out", source)
    reader.assert_called_once_with(tmp_path / "control")
    assert receipt["missing_instrument_days"] == 3
    assert receipt["gap_policy"]["reentry_bars"] == 20
    assert json.loads((tmp_path / "out/universe.json").read_bytes()) == spec


def test_thin_non_rebalance_day_cannot_allocate_new_holdings() -> None:
    from alpha_cli import _rdagent_membership as membership

    scores = np.array([1.0, 2.0, 3.0, 4.0, np.nan, np.nan])
    weights = membership.replay_weights(
        scores,
        np.full(6, 100.0),
        np.full(6, 1 / 6),
        np.full(6, 100.0),
        rebalance=False,
        direction=1,
        min_names=5,
        fraction=1 / 3,
    )
    assert not weights.any()

