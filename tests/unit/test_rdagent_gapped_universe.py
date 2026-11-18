"""Hand-built gap, causal membership and waiting-position contracts."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import polars as pl
import pytest

from alpha_cli import _rdagent_judge as judge
from alpha_cli import _rdagent_universe as universes
from alpha_core import DataError
from tests.unit._rdagent_support import judge_namespace, universe_run
from tests.unit.test_rdagent_factor_judge import data


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


def test_worker_frame_has_null_gaps_and_pre_listing_rows_but_none_after_last_bar(
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
    # Pre-listing (2020-12-01) and inside-span (2020-12-04) days are null rows; C0's last bar is
    # 2020-12-09, so no row follows it even though other coins trade on 2020-12-10.
    assert len(frame) == 9
    for day in ("2020-12-01", "2020-12-04"):
        assert frame.loc[day].isna().all()
    assert frame.index.min() == pd.Timestamp("2020-12-01")
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


def walk_panel(n: int = 120, names: int = 9, seed: int = 11) -> pl.DataFrame:
    """Random-walk bars with distinct open and close, from 2020-12-01."""
    rng = np.random.default_rng(seed)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, size=(n, names)), axis=0))
    opens = closes * np.exp(rng.normal(0, 0.01, size=(n, names)))
    return pl.DataFrame(
        [
            {
                "date": date(2020, 12, 1) + timedelta(days=i),
                "instrument": f"C{j}",
                "open": float(opens[i, j]),
                "close": float(closes[i, j]),
                "high": float(max(opens[i, j], closes[i, j]) * 1.01),
                "low": float(min(opens[i, j], closes[i, j]) * 0.99),
                "volume": 100.0,
                "quote_volume": 10000.0,
            }
            for i in range(n)
            for j in range(names)
        ]
    )


def _poisoned(bars: pl.DataFrame, cutoff: date, ended: str) -> pl.DataFrame:
    """Every price after the cutoff changes, and one instrument's series ends at the cutoff."""
    changed = bars.with_columns(
        [
            pl.when(pl.col("date") > cutoff)
            .then(pl.col(c) * (1.7 + pl.col("instrument").str.slice(1).cast(pl.Float64) / 10))
            .otherwise(pl.col(c))
            .alias(c)
            for c in ("open", "close", "high", "low")
        ]
    )
    return changed.filter(~((pl.col("instrument") == ended) & (pl.col("date") > cutoff)))


@pytest.mark.parametrize("clock", ["daily", "weekly"])
def test_future_poison_on_a_held_coin_leaves_everything_up_to_t_unchanged(clock: str) -> None:
    """Mutating bars after t, and ending a coin held at t, changes nothing dated at or before t.

    Covers membership, ranks (targets), fills, positions, realised P&L and closed periods; the
    poison has power, because it changes what happens after t.
    """
    bars = walk_panel()
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(70)]
    symbols = [f"C{j}" for j in range(9)]
    scores = np.random.default_rng(5).normal(size=(70, 9))
    cutoff = date(2021, 1, 30)
    clean: dict[str, Any] = {}
    judge.replay(bars, scores, days, 1, clock=clock, series=clean, gap_policy=True)
    held_at_cutoff = next(p for p in clean["positions"] if p["date"] == cutoff)["quantities"]
    ended = symbols[int(np.argmax(held_at_cutoff))]
    assert max(held_at_cutoff) > 0
    poison_bars = _poisoned(bars, cutoff, ended)
    poisoned: dict[str, Any] = {}
    judge.replay(poison_bars, scores, days, 1, clock=clock, series=poisoned, gap_policy=True)
    for key in ("events", "positions"):
        assert [e for e in clean[key] if e["date"] <= cutoff] == [
            e for e in poisoned[key] if e["date"] <= cutoff
        ]
    assert [t for t in clean["targets"] if t.origin_ts.date() <= cutoff] == [
        t for t in poisoned["targets"] if t.origin_ts.date() <= cutoff
    ]
    assert [p for p in clean["periods"] if p.exit_ts.date() <= cutoff] == [
        p for p in poisoned["periods"] if p.exit_ts.date() <= cutoff
    ]
    clean_members = judge.panel_membership(bars, days, symbols)
    poison_members = judge.panel_membership(poison_bars, days, symbols)
    through = days.index(cutoff) + 1
    assert np.array_equal(clean_members[:through], poison_members[:through])
    # Power: the ended coin leaves membership the next day and is written off 30 days later.
    assert not poison_members[through:, symbols.index(ended)].any()
    writeoffs = [e for e in poisoned["events"] if e["basis"] == "writeoff"]
    assert writeoffs and writeoffs[0]["instrument"] == ended
    assert writeoffs[0]["date"] == cutoff + timedelta(days=30)


def test_write_off_waits_exactly_thirty_calendar_days_everywhere() -> None:
    """Day 29 without a bar keeps waiting; a bar on day 30 is an exit, not a write-off."""
    from alpha_cli import _rdagent_membership as membership

    start = date(2021, 1, 1)
    days = [start + timedelta(days=i) for i in range(60)]
    for resume, haircut in ((30, False), (31, True)):
        prices = np.full((60, 1), 100.0)
        prices[1:resume] = np.nan
        prices[resume:] = 50.0
        account = membership.Account(["A"], fee_bps=0, slippage_bps=0)
        account.trade(0, 1.0, 100.0, start, "open")
        for day, row in zip(days, prices, strict=True):
            account.observe(day, row)
            if day == start + timedelta(days=29):
                assert account.quantities[0] == 1.0 and account.haircuts == 0
        assert account.haircuts == int(haircut)
        assert account.events[-1]["price"] == pytest.approx(70.0 if haircut else 50.0)
        assert account.events[-1]["date"] == start + timedelta(days=30)
        held, held_counts = membership.holding_returns(prices, prices, days, [0], [10])
        assert held[0, 0] == pytest.approx(-0.3 if haircut else -0.5)
        assert held_counts["haircuts_applied"] == int(haircut)


def test_gap_free_replay_first_period_is_hand_computed() -> None:
    """A gap-free panel: hand-computed first period, no haircut, no wait."""
    rows = []
    for i in range(40):
        for j in range(5):
            price = 100.0 + (i if j == 0 else 0.0)
            rows.append(
                {
                    "date": date(2020, 12, 1) + timedelta(days=i),
                    "instrument": f"C{j}",
                    "open": price,
                    "close": price,
                    "high": price,
                    "low": price,
                    "volume": 1.0,
                    "quote_volume": 1.0,
                }
            )
    bars = pl.DataFrame(rows)
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(5)]
    scores = np.tile(np.array([5.0, 1.0, 2.0, 3.0, 4.0]), (5, 1))  # C0 is the only top name
    series: dict[str, Any] = {}
    metrics, net = judge.replay(bars, scores, days, 1, series=series, gap_policy=True)
    assert metrics["haircuts_applied"] == 0 and metrics["unrankable_instrument_rebalances"] == 0
    # Decide on the 2021-01-01 close: k = round(5/3) = 2 names, C0 (close 131) and C4 (100), half
    # each, sized at that close. Fill at the 2021-01-02 open (C0 132) with 6 bps slippage and
    # 10 bps fee, buys scaled pro rata to the cash; value at the 2021-01-03 open (C0 133).
    q0, q4 = 500_000 / 131, 500_000 / 100
    net_return = (q0 * 133 + q4 * 100) / ((q0 * 132 + q4 * 100) * 1.0006 * 1.001) - 1
    benchmark = (133 / 132 - 1) / 5
    first = series["periods"][0]
    assert first.gross_return == pytest.approx(0.5 * (133 / 132 - 1), rel=1e-12)
    assert first.benchmark_return == pytest.approx(benchmark, rel=1e-12)
    assert net[0] == pytest.approx(net_return - benchmark, rel=1e-9)


def test_frozen_universe_reloads_after_its_store_is_gone(tmp_path: Path) -> None:
    """The store is read once, at freeze; evaluating a frozen run must not need it mounted."""
    store = tmp_path / "store"
    store.mkdir()
    spec = {**universes.DEFAULT, "data_dir": str(store)}
    panel_dir = tmp_path / "panel"
    panel_dir.mkdir()
    (panel_dir / "universe.json").write_text(json.dumps(spec))
    store.rmdir()
    assert universes.frozen(panel_dir)["data_dir"] == str(store)
    with pytest.raises(DataError, match="data_dir"):
        judge.freeze(tmp_path / "unused", tmp_path / "out", panel_dir / "universe.json")


@pytest.mark.parametrize(("warnings", "accepted"), [(["cadence_gap"], True), (["other"], False)])
def test_freeze_accepts_a_month_whose_only_warning_is_its_gap(
    tmp_path: Path, warnings: list[str], accepted: bool
) -> None:
    """A real store marks a month with missing days `warning: cadence_gap`; that is the gap
    this policy records, so it must not block the freeze. Any other warning still does."""
    from unittest.mock import patch

    from tests.unit.test_rdagent_factor_eval import _bulk_store, _publish

    store = _bulk_store(tmp_path)
    _publish(store, "BTCUSDT", (10.0, 11.0, 12.0, 13.0), skip=1)
    read = store.read_verified_normalized

    def warned(manifest_id: str, *, max_bytes: int) -> tuple[dict[str, Any], bytes]:
        verified, payload = read(manifest_id, max_bytes=max_bytes)
        original = verified["quality"]
        assert isinstance(original, dict)
        quality = {**original, "state": "warning", "warnings": warnings}
        return {**verified, "quality": quality}, payload

    with (
        patch.object(judge, "configured_crypto_bulk_store", lambda _: store),
        patch.object(store, "read_verified_normalized", warned),
    ):
        if accepted:
            receipt = judge.freeze(tmp_path / "control", tmp_path / "out")
            assert receipt["missing_instrument_days"] == 1
        else:
            with pytest.raises(DataError, match="unqualified"):
                judge.freeze(tmp_path / "control", tmp_path / "out")


def test_label_fallback_counts_only_names_that_were_ranked() -> None:
    """Counts describe ranked names; a coin not yet listed is not an 'unfilled entry'."""
    from alpha_cli._rdagent_clocks import clock_samples

    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(5)]
    open_days = [date(2021, 1, 1) + timedelta(days=i) for i in range(8)]
    opens = np.full((8, 6), 100.0)
    opens[:, 5] = np.nan  # listed after the window: never ranked, never counted
    opens[4:, 4] = np.nan  # ranked on day 3, then stops: its entry on day 4 cannot fill
    signal = np.tile(np.arange(6.0), (5, 1))
    signal[:, 5] = np.nan
    signal[4:, 4] = np.nan
    data = clock_samples(signal, opens, days, open_days, "daily", closes=opens, gap_policy=True)
    assert data["gap_counts"]["unfilled_entries"] == 1


def test_replay_output_names_missing_rank_observations() -> None:
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(50)]
    scores = np.tile(np.arange(9.0), (50, 1))
    scores[:, 0] = np.nan
    metrics, _ = judge.replay(walk_panel(), scores, days, 1, clock="weekly", gap_policy=True)
    assert "missing_coin_days" not in metrics
    assert metrics["unrankable_instrument_rebalances"] == metrics["rebalances"]


def test_missing_universe_information_refuses_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPHA_FACTOR_RUN_DIR", raising=False)
    monkeypatch.delenv("ALPHA_FACTOR_UNIVERSE_TEXT", raising=False)
    with pytest.raises(ValueError, match="universe"):
        judge_namespace()["append_swing_context"]({"hypothesis_and_feedback": ""}, None)


@pytest.fixture(name="saved")
def record_hdf_frames(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, pd.DataFrame]:
    saved: dict[str, pd.DataFrame] = {}

    def write(frame: pd.DataFrame, path: Path, *, key: str, mode: str) -> None:
        saved[str(path.relative_to(tmp_path / "out"))] = frame.copy()
        path.write_bytes(b"hdf boundary")

    monkeypatch.setattr(pd.DataFrame, "to_hdf", write)
    return saved


@pytest.mark.parametrize("first", ["2020-12-30", "2021-01-01"])
def test_cut_copies_keep_not_yet_listed_instruments(
    tmp_path: Path, saved: dict[str, pd.DataFrame], first: str
) -> None:
    frame = pd.DataFrame({"date": pd.to_datetime([first, "2021-01-02"]), "instrument": ["A", "B"]})
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = [1.0, 2.0]
    frame.to_parquet(tmp_path / "panel.parquet")
    data.prepare(tmp_path / "panel.parquet", tmp_path / "out")
    cut = saved["cuts/2020-12-31/daily_pv.h5"]
    assert set(cut.index.get_level_values("instrument")) == {"A", "B"}
    assert cut.xs("B", level="instrument").isna().all().all()


def test_padding_adds_only_pre_listing_rows_never_rows_after_the_last_bar(
    tmp_path: Path, saved: dict[str, pd.DataFrame]
) -> None:
    """The span rule of the gapped universe still holds after its last bar: no rows at all."""
    # A trades 2020-12-29..2021-01-03 with a gap on 2021-01-01 and then stops trading;
    # B lists on 2021-01-02 and trades to the panel end, 2021-04-05.
    a_days = ["2020-12-29", "2020-12-30", "2020-12-31", "2021-01-02", "2021-01-03"]
    b_days = [str(d.date()) for d in pd.date_range("2021-01-02", "2021-04-05")]
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(a_days + b_days),
            "instrument": ["A"] * len(a_days) + ["B"] * len(b_days),
        }
    )
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = 1.0
    frame.to_parquet(tmp_path / "panel.parquet")
    data.prepare(tmp_path / "panel.parquet", tmp_path / "out")
    full = saved["full/daily_pv.h5"]
    a = full.xs("A", level="instrument")
    b = full.xs("B", level="instrument")
    assert a.index.max() == pd.Timestamp("2021-01-03")
    assert a.loc["2021-01-01"].isna().all()
    assert b.index.min() == pd.Timestamp("2020-12-29")
    assert b.loc[:"2021-01-01"].isna().all().all()
    assert b.loc["2021-01-02":].notna().all().all()
    for name, cut in saved.items():
        if name.startswith("cuts/"):
            assert set(cut.index.get_level_values("instrument")) == {"A", "B"}, name
            prefix = full.loc[full.index.get_level_values(0) <= name.split("/")[1]]
            pd.testing.assert_frame_equal(cut, prefix)


def test_universe_receipt_binding_is_checked_before_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe_run(tmp_path, monkeypatch)
    path = tmp_path / "panel/panel-receipt.json"
    receipt = json.loads(path.read_text())
    receipt["universe_sha256"] = "0" * 64
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="universe.*differs"):
        data.current_universe()
