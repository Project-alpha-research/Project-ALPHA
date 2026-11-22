"""Known answers: holding periods, weekdays and the worst drawdown."""

from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from tests.unit.risk_sizing_support import put_equity, put_trades, read, stored

REL, ABS = 1e-9, 1e-12


def test_hold_period(tmp_path: Path) -> None:
    stored(tmp_path)
    hold = [1, 3, 5, 6, 10, 20, 21, 40, 2, 4]
    pnl = [2.0, -1.0, 3.0, 5.0, -2.0, 1.0, 4.0, 8.0, -3.0, 0.0]
    put_trades(tmp_path, pnl, hold_days=hold, entry_days=[50 * i for i in range(10)])
    values = read(tmp_path, "attribution.hold_period")["values"]
    # Short is 5 days or less: pnl 2, -1, 3, -3, 0 (five trades, two wins).
    assert values["short_count"] == 5
    assert values["short_win_rate"] == pytest.approx(2 / 5, rel=REL, abs=ABS)
    assert values["short_average_pnl"] == pytest.approx(0.2, rel=REL, abs=ABS)
    # Medium is 6 to 20 days: pnl 5, -2, 1.
    assert values["medium_count"] == 3
    assert values["medium_average_pnl"] == pytest.approx(4 / 3, rel=REL, abs=ABS)
    # Long is over 20 days: pnl 4, 8.
    assert values["long_count"] == 2
    assert values["long_win_rate"] == pytest.approx(1.0, rel=REL, abs=ABS)
    assert values["long_average_pnl"] == pytest.approx(6.0, rel=REL, abs=ABS)


def test_hold_period_names_an_empty_bucket(tmp_path: Path) -> None:
    stored(tmp_path)
    put_trades(tmp_path, [1.0] * 12, hold_days=[2] * 12)
    doc = read(tmp_path, "attribution.hold_period")
    assert doc["values"]["long_average_pnl"] is None
    assert "No closed trades" in doc["reasons"]["long_average_pnl"]
    assert doc["values"]["short_count"] == 12


def test_hold_period_rejects_swapped_limits(tmp_path: Path) -> None:
    stored(tmp_path)
    put_trades(tmp_path, [1.0] * 12)
    with pytest.raises(ValueError, match="long_days"):
        read(tmp_path, "attribution.hold_period", "short_days=30", "long_days=10")


def test_weekday(tmp_path: Path) -> None:
    stored(tmp_path)
    # 2022-01-01 was a Saturday, so entry day d falls on weekday (d + 5) % 7 (Monday is 0).
    days = [2, 9, 16, 3, 10, 17, 4, 11, 18, 5, 12, 19]
    pnl = [5.0, 4.0, 6.0, -1.0, 0.0, 1.0, 2.0, 1.0, 0.0, -3.0, -2.0, -4.0]
    put_trades(tmp_path, pnl, entry_days=days)
    doc = read(tmp_path, "attribution.weekday")
    values = doc["values"]
    assert values["monday_count"] == 3
    assert values["monday_average_pnl"] == pytest.approx(5.0, rel=REL, abs=ABS)
    assert values["tuesday_average_pnl"] == pytest.approx(0.0, rel=REL, abs=ABS)
    assert values["wednesday_average_pnl"] == pytest.approx(1.0, rel=REL, abs=ABS)
    assert values["thursday_average_pnl"] == pytest.approx(-3.0, rel=REL, abs=ABS)
    assert values["friday_count"] == 0
    assert values["friday_average_pnl"] is None
    assert values["best_weekday"] == "Monday"
    groups = [pnl[0:3], pnl[3:6], pnl[6:9], pnl[9:12]]
    assert values["p_value"] == pytest.approx(stats.kruskal(*groups).pvalue, rel=REL, abs=ABS)


def test_weekday_says_when_all_profits_are_equal(tmp_path: Path) -> None:
    stored(tmp_path)
    put_trades(tmp_path, [1.0] * 12, entry_days=list(range(2, 14)))
    doc = read(tmp_path, "attribution.weekday")
    assert doc["values"]["p_value"] is None
    assert "identical" in doc["reasons"]["p_value"]


def test_drawdown_causes(tmp_path: Path) -> None:
    stored(tmp_path)
    equity = np.r_[[100.0, 110, 120, 108, 96, 102, 118, 125, 130], np.linspace(131, 142, 12)]
    put_equity(tmp_path, equity)
    # Trades close on days 1, 3, 4 (inside the fall from day 2 to day 4) and on day 6.
    put_trades(
        tmp_path,
        [10.0, -12.0, -12.0, 16.0],
        entry_days=[0, 2, 3, 5],
        hold_days=[1, 1, 1, 1],
    )
    values = read(tmp_path, "attribution.drawdown_causes")["values"]
    assert values["drawdown"] == pytest.approx(96 / 120 - 1, rel=REL, abs=ABS)
    assert values["peak_date"] == "2022-01-03"
    assert values["trough_date"] == "2022-01-05"
    assert values["recovery_date"] == "2022-01-08"
    assert values["bars_down"] == 2
    assert values["equity_loss"] == pytest.approx(24.0, rel=REL, abs=ABS)
    assert values["trades_closed"] == 2
    assert values["closed_pnl"] == pytest.approx(-24.0, rel=REL, abs=ABS)
    assert values["worst_trade_pnl"] == pytest.approx(-12.0, rel=REL, abs=ABS)


def test_drawdown_causes_without_recovery_or_trades(tmp_path: Path) -> None:
    stored(tmp_path)
    put_equity(tmp_path, np.r_[[100.0, 120, 90, 95], np.full(18, 95.0)])
    put_trades(tmp_path, [1.0] * 3, entry_days=[40, 41, 42])
    doc = read(tmp_path, "attribution.drawdown_causes")
    assert doc["values"]["recovery_date"] is None
    assert "not regained" in doc["reasons"]["recovery_date"]
    assert doc["values"]["closed_pnl"] is None
    assert doc["values"]["trades_closed"] == 0


def test_drawdown_causes_when_equity_never_falls(tmp_path: Path) -> None:
    stored(tmp_path)
    put_equity(tmp_path, np.linspace(100, 120, 25))
    put_trades(tmp_path, [1.0] * 3)
    doc = read(tmp_path, "attribution.drawdown_causes")
    assert all(v is None for v in doc["values"].values())
    assert "never fell" in doc["reasons"]["drawdown"]
