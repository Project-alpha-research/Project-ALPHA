"""Cash entries must execute on the intended next open despite an overnight gap."""

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model.enums import AccountType
from nautilus_trader.model.objects import Money

from alpha_backtest.engine import run_backtest
from alpha_backtest.feed import daily_bar_type, to_execution_feed
from alpha_backtest.instruments import crypto_instrument, equity_instrument
from alpha_backtest.results import AccountingTrace, BacktestResult
from alpha_cli.spine.facts import build_facts
from alpha_core import Bar
from alpha_strategies.ma_crossover import MovingAverageCrossover


def _run_gap(
    fee_bps: float,
    *,
    prices: list[float] | None = None,
    opens: list[float] | None = None,
    margin: bool = False,
    short: bool = False,
    equity_sizing: bool = False,
    fractional: bool = False,
    slippage_bps: float = 0,
) -> tuple[BacktestResult, list[AccountingTrace]]:
    prices = prices or [99.0, 100.0, 103.0, 103.0, 100.0, 100.0]
    symbol = "BTC/USD" if fractional else "SPY"
    bars = [
        Bar(
            symbol=symbol,
            ts=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i),
            open=opens[i] if opens else price,
            high=max(opens[i], price) if opens else price,
            low=min(opens[i], price) if opens else price,
            close=price,
            volume=1_000_000,
        )
        for i, price in enumerate(prices)
    ]
    instrument = (
        crypto_instrument(symbol, size_precision=3, size_increment=0.005)
        if fractional
        else equity_instrument(symbol)
    )
    bar_type = daily_bar_type(symbol)
    strategy = MovingAverageCrossover(
        instrument_id=instrument.id,
        bar_type=bar_type,
        fast=1,
        slow=2,
        vol_window=2,
        target_vol=10,
        capital=10_000,
        rebalance_every=1,
        allow_short=short,
        sizing="vol_target" if short or equity_sizing else "all_in",
        size_on_equity=equity_sizing,
    )
    strategy.configure_sizing_costs(fee_bps=fee_bps, slippage_bps=slippage_bps)
    accounting: list[AccountingTrace] = []
    result = run_backtest(
        instrument,
        to_execution_feed(
            bars,
            bar_type,
            price_precision=instrument.price_precision,
            size_precision=instrument.size_precision,
            slippage_bps=slippage_bps,
        ),
        strategy,
        starting_cash=10_000,
        account_type=AccountType.MARGIN if margin else AccountType.CASH,
        leverage=2 if margin else 1,
        fee_bps=fee_bps,
        accounting_trace=None if margin else accounting,
    )
    return result, accounting


def _execution_bytes(result: BacktestResult) -> bytes:
    return json.dumps(
        {
            key: value
            for key, value in asdict(result).items()
            if key in {"fill_trace", "trades", "equity_curve"}
        },
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


@pytest.mark.parametrize(("fee_bps", "expected_quantity"), [(0.0, 97), (10.0, 96)])
def test_gap_entry_fills_on_intended_bar_with_affordable_quantity(
    fee_bps: float, expected_quantity: int
) -> None:
    result, accounting = _run_gap(fee_bps)
    entry = result.fill_trace[0]
    assert entry.ts.date().isoformat() == "2020-01-03"
    assert entry.quantity == expected_quantity
    assert entry.price == 103
    assert result.rejected == 0
    assert result.resized_entries == 1
    assert result.decision_trace[0].target_quantity == 99
    assert min(row.cash for row in accounting) >= 0
    assert min(row.cash_free for row in accounting) >= 0


def test_future_poison_cannot_change_entry_size_or_time() -> None:
    base, _ = _run_gap(10)
    poison, _ = _run_gap(10, prices=[99, 100, 103, 200, 20, 300])
    assert base.fill_trace[0] == poison.fill_trace[0]
    assert base.fill_trace[0].ts.day == 3


@pytest.mark.parametrize("slippage_bps", [0.0, 15.0])
def test_fractional_entry_uses_largest_affordable_size_step(slippage_bps: float) -> None:
    result, accounting = _run_gap(10, fractional=True, slippage_bps=slippage_bps)
    entry = result.fill_trace[0]
    currency = crypto_instrument("BTC/USD").quote_currency

    def cost(quantity: float) -> float:
        notional = quantity * entry.price
        return float((Money(notional, currency) + Money(notional * 0.001, currency)).as_double())

    assert entry.ts.day == 3
    assert round(entry.quantity * 1000) % 5 == 0
    assert cost(entry.quantity) <= 10_000 < cost(entry.quantity + 0.005)
    assert result.resized_entries == 1
    assert result.rejected == 0
    assert min(row.cash_free for row in accounting) >= 0


def test_equity_share_entry_is_resized() -> None:
    # Exit at the next decision, isolating the entry from later equity rebalancing.
    result, accounting = _run_gap(
        10,
        prices=[98, 99, 100, 99, 98, 97],
        opens=[98, 99, 100, 103, 99, 98],
        equity_sizing=True,
    )
    assert result.fill_trace[0].ts.day == 4
    assert result.fill_trace[0].quantity == 96
    assert result.resized_entries == 1
    assert result.rejected == 0
    assert min(row.cash_free for row in accounting) >= 0


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {"opens": [99, 99, 100, 103, 103, 100]},
            "dc102054077485241e368614e912b8e578b904423ce9942bbd72bf574779ae2b",
        ),
        ({"margin": True}, "18ee46f5beaec2437f4d766551fe3d0d0b65df17509fed87b8f43934f3ec360f"),
        (
            {"margin": True, "short": True, "prices": [103, 102, 100, 103, 100, 99]},
            "2b6cbcf022230a8ca0746ba838a573b8846d54611f52a1811449682de949c977",
        ),
    ],
)
def test_unchanged_paths_have_identical_execution_bytes(
    kwargs: dict[str, Any], expected: str
) -> None:
    # Digests captured from the unmodified engine before the gap fix.
    result, _ = _run_gap(10, **kwargs)
    assert result.rejected == 0
    assert hashlib.sha256(_execution_bytes(result)).hexdigest() == expected
    assert result.resized_entries == 0


def test_old_result_and_stored_run_remain_readable(tmp_path: Path) -> None:
    assert BacktestResult(orders=0, fills=0, trades=[], equity_curve=[]).resized_entries == 0
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    facts = {row["metric"]: row for row in build_facts(tmp_path)}
    assert facts["resized_entries"]["value"] is None
    assert facts["resized_entries"]["reason"]
    (tmp_path / "manifest.json").write_text('{"resized_entries":2}', encoding="utf-8")
    facts = {row["metric"]: row for row in build_facts(tmp_path)}
    assert facts["resized_entries"]["value"] == 2


@pytest.mark.parametrize("count", [None, 0, 2])
def test_repeat_summary_reads_recorded_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    count: int | None,
) -> None:
    from unittest.mock import Mock

    from alpha_cli import _artifacts, _gauntlet
    from alpha_cli.spine import run
    from alpha_cli.spine.spec import load_spec

    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    manifest = {} if count is None else {"resized_entries": count}
    monkeypatch.setattr(_artifacts, "read_manifest", lambda path: manifest)
    result: dict[str, Any] = {"run_dir": str(tmp_path), "labels": [], "asset": "SPY"}
    idea = load_spec(None, rule="ma_cross", param=["fast=1", "slow=2"], asset=["SPY"])
    run._execute(
        idea, Mock(spec=run.Prepared), tmp_path, _gauntlet.GauntletParams(), "test", result
    )
    assert result["resized_entries"] == (count or 0)
    expected = (
        "SPY: 2 entries were made smaller, because the cash did not cover the full order at the "
        "next open plus fees. The result already uses the smaller size.\n"
        if count
        else ""
    )
    assert capsys.readouterr().out == expected


@pytest.mark.parametrize("fee_bps", [0.0, 10.0])
def test_no_affordable_lot_remains_a_counted_refusal(fee_bps: float) -> None:
    result, accounting = _run_gap(fee_bps, prices=[99, 100, 20000, 20000])
    assert result.rejected == 1
    assert result.resized_entries == 0
    assert not result.fill_trace
    assert len(result.execution_rejections) == (1 if fee_bps else 0)
    assert all(row.cash == 10000 for row in accounting)


def test_fixed_quantity_still_refuses_the_whole_unaffordable_order() -> None:
    from alpha_strategies.base import VolTargetStrategy

    class FixedLong(VolTargetStrategy):
        def _signal(self) -> int:
            return 1

    instrument = equity_instrument("SPY")
    bar_type = daily_bar_type("SPY")
    strategy = FixedLong(
        instrument_id=instrument.id,
        bar_type=bar_type,
        min_history=1,
        capital=10000,
        fixed_quantity=99,
        allow_short=False,
        rebalance_every=1,
    )
    bars = [
        Bar(
            symbol="SPY",
            ts=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i),
            open=price,
            high=price,
            low=price,
            close=price,
            volume=1_000_000,
        )
        for i, price in enumerate([100, 103, 103])
    ]
    result = run_backtest(
        instrument,
        to_execution_feed(bars, bar_type),
        strategy,
        starting_cash=10000,
        fee_bps=10,
    )
    assert result.rejected == 2
    assert result.resized_entries == 0
    assert not result.fill_trace
    assert len(result.execution_rejections) == 2
    for rejection in result.execution_rejections:
        assert rejection.requested_quantity == 99
        assert rejection.required_cash == 10207.2
        assert rejection.reason == "cash_notional_exceeds_free_balance"


def test_long_top_up_is_not_resized_and_stays_a_counted_refusal() -> None:
    # Equity sizing raises an open long twice beyond free cash; only the flat entry is resized.
    result, accounting = _run_gap(
        10,
        prices=[100.0, 100.34, 101.45, 103.54, 105.55, 106.47, 110.45, 111.52, 112.66, 112.08],
        opens=[100.0, 100.01, 102.58, 101.51, 102.99, 107.98, 104.69, 109.86, 113.99, 110.66],
        equity_sizing=True,
    )
    assert result.resized_entries == 1
    assert result.rejected == 2
    assert all(row.requested_quantity < 10 for row in result.execution_rejections)
    assert min(row.cash_free for row in accounting) >= 0
