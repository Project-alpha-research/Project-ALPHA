"""Known answers: Kelly, fractional Kelly, optimal f, loss streaks and volatility targeting."""

import math
from itertools import product
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from tests.unit.risk_sizing_support import put_returns, put_trades, read, stored
from tests.unit.test_spine_tools import RUN

REL, ABS = 1e-9, 1e-12
GAINS = [0.2, -0.1] * 10


def with_trades(home: Path, ret: list[float]) -> None:
    stored(home)
    put_trades(home, [r * 1000 for r in ret])


def test_kelly(tmp_path: Path) -> None:
    with_trades(tmp_path, GAINS)
    values = read(tmp_path, "risk.kelly")["values"]
    # Kelly (1956): p - q / b = 0.5 - 0.5 / 2. The growth-optimal stake solves
    # 0.2 / (1 + 0.2 f) = 0.1 / (1 - 0.1 f), so f = 2.5 of equity for trades that move 0.2 / -0.1.
    assert values["trades"] == 20
    assert values["win_rate"] == pytest.approx(0.5, rel=REL, abs=ABS)
    assert values["payoff_ratio"] == pytest.approx(2.0, rel=REL, abs=ABS)
    assert values["kelly_simple"] == pytest.approx(0.25, rel=REL, abs=ABS)
    assert values["kelly_growth"] == pytest.approx(2.5, rel=REL, abs=ABS)
    assert values["growth_at_kelly"] == pytest.approx(math.log(1.125) / 2, rel=REL, abs=ABS)


def test_kelly_uses_after_cost_profit_not_the_price_return(tmp_path: Path) -> None:
    stored(tmp_path)
    # The stored price return says every trade gained; after commissions they lost money.
    put_trades(tmp_path, [-1.0, -2.0] * 10)
    folder = tmp_path / "runs" / RUN
    frame = pl.read_parquet(folder / "trades.parquet")
    frame.with_columns(pl.lit(0.05).alias("realized_return")).write_parquet(
        folder / "trades.parquet"
    )
    doc = read(tmp_path, "risk.kelly")
    assert doc["values"]["kelly_growth"] is None
    assert "winning" in doc["reasons"]["kelly_growth"]


def test_kelly_without_an_edge_is_zero(tmp_path: Path) -> None:
    with_trades(tmp_path, [0.1, -0.2] * 10)
    values = read(tmp_path, "risk.kelly")["values"]
    assert values["kelly_growth"] == 0.0
    assert values["kelly_simple"] == pytest.approx(0.5 - 0.5 / 0.5, rel=REL, abs=ABS)
    assert values["growth_at_kelly"] == 0.0


def test_kelly_needs_a_loss(tmp_path: Path) -> None:
    with_trades(tmp_path, [0.1] * 25)
    doc = read(tmp_path, "risk.kelly")
    assert doc["values"]["kelly_growth"] is None
    assert "losing" in doc["reasons"]["kelly_growth"]


def test_fractional_kelly(tmp_path: Path) -> None:
    with_trades(tmp_path, GAINS)
    values = read(tmp_path, "risk.fractional_kelly")["values"]
    # Thorp (1969): stake the fractions 1, 1/2 and 1/4 of Kelly (f = 2.5, 1.25, 0.625).
    assert values["kelly_growth"] == pytest.approx(2.5, rel=REL, abs=ABS)
    for name, f, drop in (
        ("full", 2.5, -0.25),
        ("half", 1.25, -0.125),
        ("quarter", 0.625, -0.0625),
    ):
        growth = (math.log(1 + 0.2 * f) + math.log(1 - 0.1 * f)) / 2
        assert values[f"growth_{name}"] == pytest.approx(growth, rel=REL, abs=ABS)
        assert values[f"drawdown_{name}"] == pytest.approx(drop, rel=REL, abs=ABS)


def test_fractional_kelly_without_an_edge(tmp_path: Path) -> None:
    with_trades(tmp_path, [0.1, -0.2] * 10)
    doc = read(tmp_path, "risk.fractional_kelly")
    assert doc["values"]["growth_half"] is None
    assert "no positive edge" in doc["reasons"]["growth_half"].lower()


def test_optimal_f(tmp_path: Path) -> None:
    with_trades(tmp_path, GAINS)
    values = read(tmp_path, "risk.optimal_f")["values"]
    # Vince (1990): HPR = 1 + f * r / |worst|; wins give 1 + 2f, losses 1 - f; the best f is 0.25.
    assert values["optimal_f"] == pytest.approx(0.25, rel=REL, abs=ABS)
    assert values["largest_loss"] == pytest.approx(0.1, rel=REL, abs=ABS)
    assert values["terminal_multiple"] == pytest.approx(1.125**10, rel=REL, abs=ABS)
    assert values["geometric_hpr"] == pytest.approx(math.sqrt(1.125), rel=REL, abs=ABS)


def test_optimal_f_without_an_edge_is_zero(tmp_path: Path) -> None:
    with_trades(tmp_path, [0.1, -0.2] * 10)
    values = read(tmp_path, "risk.optimal_f")["values"]
    assert values["optimal_f"] == 0.0
    assert values["terminal_multiple"] == pytest.approx(1.0, rel=REL, abs=ABS)


def test_optimal_f_needs_a_loss(tmp_path: Path) -> None:
    with_trades(tmp_path, [0.1] * 25)
    doc = read(tmp_path, "risk.optimal_f")
    assert doc["values"]["optimal_f"] is None
    assert "losing" in doc["reasons"]["optimal_f"]


def streak_probability(n: int, p: float, longest: int) -> float:
    """Brute force over every order of n trades: chance of a losing streak of the given length."""
    total = 0.0
    for flags in product((True, False), repeat=n):
        run = best = 0
        for lost in flags:
            run = run + 1 if lost else 0
            best = max(best, run)
        weight = p ** sum(flags) * (1 - p) ** (n - sum(flags))
        total += weight * (best >= longest)
    return total


def test_loss_streaks(tmp_path: Path) -> None:
    stored(tmp_path)
    pnl = [-1.0, -1.0, -1.0, 1.0, 1.0, -1.0, 1.0, -1.0, 1.0, 1.0]
    put_trades(tmp_path, pnl)
    values = read(tmp_path, "risk.loss_streaks", "streak=4")["values"]
    assert values["trades"] == 10
    assert values["loss_rate"] == pytest.approx(0.5, rel=REL, abs=ABS)
    assert values["longest_losing_streak"] == 3
    assert values["p_observed_or_longer"] == pytest.approx(
        streak_probability(10, 0.5, 3), rel=REL, abs=ABS
    )
    assert values["p_streak"] == pytest.approx(streak_probability(10, 0.5, 4), rel=REL, abs=ABS)
    expected = sum(streak_probability(10, 0.5, k) for k in range(1, 11))
    assert values["expected_longest"] == pytest.approx(expected, rel=REL, abs=ABS)


def test_loss_streaks_on_many_trades_stays_fast(tmp_path: Path) -> None:
    stored(tmp_path)
    pnl = [-1.0 if i % 3 else 2.0 for i in range(900)]
    put_trades(tmp_path, pnl, entry_days=list(range(900)), hold_days=[1] * 900)
    values = read(tmp_path, "risk.loss_streaks")["values"]
    assert values["longest_losing_streak"] == 2
    assert 0.0 < values["expected_longest"] < 900


def test_loss_streaks_ends_a_streak_at_a_flat_trade(tmp_path: Path) -> None:
    stored(tmp_path)
    put_trades(tmp_path, [-1.0, -1.0, 0.0, -1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    assert read(tmp_path, "risk.loss_streaks")["values"]["longest_losing_streak"] == 2


def test_vol_target(tmp_path: Path) -> None:
    stored(tmp_path)
    r = np.where(np.arange(120) % 2 == 0, 0.01, -0.01)
    put_returns(tmp_path, r)
    values = read(tmp_path, "risk.vol_target", "target_vol=0.1", "lookback=20")["values"]
    ppy = 365
    window_sd = 0.01 * math.sqrt(20 / 19)
    weight = 0.1 / (window_sd * math.sqrt(ppy))
    after = r[20:]
    scaled = weight * after
    assert values["bars"] == 100
    assert values["average_leverage"] == pytest.approx(weight, rel=REL, abs=ABS)
    assert values["raw_vol"] == pytest.approx(after.std(ddof=1) * math.sqrt(ppy), rel=REL, abs=ABS)
    assert values["scaled_vol"] == pytest.approx(
        scaled.std(ddof=1) * math.sqrt(ppy), rel=REL, abs=ABS
    )
    assert values["raw_sharpe"] == pytest.approx(
        after.mean() / after.std(ddof=1) * math.sqrt(ppy), rel=1e-6, abs=1e-9
    )
    assert values["scaled_sharpe"] == pytest.approx(values["raw_sharpe"], rel=1e-6, abs=1e-9)
    equity = np.r_[1.0, np.cumprod(1 + scaled)]
    drop = (equity / np.maximum.accumulate(equity) - 1).min()
    assert values["scaled_max_drawdown"] == pytest.approx(drop, rel=REL, abs=ABS)


def test_vol_target_caps_the_leverage(tmp_path: Path) -> None:
    stored(tmp_path)
    r = np.where(np.arange(100) % 2 == 0, 0.0001, -0.0001)
    put_returns(tmp_path, r)
    values = read(tmp_path, "risk.vol_target", "max_leverage=1.5")["values"]
    assert values["average_leverage"] == pytest.approx(1.5, rel=REL, abs=ABS)
