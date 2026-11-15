"""Known-answer oracle for intraday execution: decide on bar t's close, fill at bar t+1's open.

Back-to-back intraday bars share an instant: bar t closes exactly when bar t+1 opens. The feed
stamps bar t's decision at its close and bar t+1's opening quote one microsecond later, so an
order decided on bar t can only fill at bar t+1's open. These oracles derive the expected fills
and equity from the bar ladder alone (no engine state) for 5-minute stock bars across an overnight
gap and for 24/7 hourly crypto bars, with and without fees.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import AccountType, OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

from alpha_backtest.engine import run_backtest
from alpha_backtest.feed import bar_type_for, to_execution_feed
from alpha_backtest.instruments import instrument_for
from alpha_core import Bar
from alpha_data.timeframe import parse_timeframe
from tests.oracles._reference.pnl import assert_curves_equal, rederive_equity_curve
from tests.oracles._reference.tolerances import ENGINE_MONEY_ABS

pytestmark = pytest.mark.oracle

_CASH = 1_000_000.0  # run_backtest's default starting cash
_QUOTE_DELAY = timedelta(microseconds=1)


def _ladder(symbol: str, stamps: list[datetime]) -> list[Bar]:
    """Distinct opens (100, 110, ...) and close = open + 5 make a wrong-bar fill visible."""
    return [
        Bar(
            symbol=symbol,
            ts=ts,
            open=100.0 + 10.0 * i,
            high=140.0 + 10.0 * i,
            low=90.0 + 10.0 * i,
            close=105.0 + 10.0 * i,
            volume=1_000.0,
        )
        for i, ts in enumerate(stamps)
    ]


def _stock_stamps() -> list[datetime]:
    # Three 5m bars at the end of one session, then three at the next session's open.
    first = datetime(2026, 11, 16, 20, 45, tzinfo=UTC)  # 15:45 New York
    second = datetime(2026, 11, 17, 14, 30, tzinfo=UTC)  # 09:30 New York
    return [first + timedelta(minutes=5 * i) for i in range(3)] + [
        second + timedelta(minutes=5 * i) for i in range(3)
    ]


def _crypto_stamps() -> list[datetime]:
    start = datetime(2026, 10, 1, 22, tzinfo=UTC)
    return [start + timedelta(hours=i) for i in range(6)]


class _TradeOnBars(Strategy):  # type: ignore[misc]  # nautilus Strategy is untyped (Cython)
    """Decide BUY on decision bar ``buy_at`` and SELL on bar ``sell_at``; execute on the next quote.

    This is ALPHA's strategy protocol (``alpha_strategies.base``): decide in ``on_bar`` on the
    close of t, submit on the next opening quote. The only quote after bar t's close is bar t+1's
    open, so the fill must be bar t+1's open; any earlier quote would be a look-ahead.
    """

    def __init__(
        self, bar_type: BarType, iid: InstrumentId, *, buy_at: int, sell_at: int | None
    ) -> None:
        super().__init__()
        self._bar_type = bar_type
        self._iid = iid
        self._buy_at = buy_at
        self._sell_at = sell_at
        self._n = 0
        self._pending: OrderSide | None = None

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_type)
        self.subscribe_quote_ticks(self._iid)

    def on_bar(self, bar: object) -> None:
        self._n += 1
        if self._n == self._buy_at:
            self._pending = OrderSide.BUY
        elif self._n == self._sell_at:
            self._pending = OrderSide.SELL

    def on_quote_tick(self, quote: object) -> None:
        if self._pending is None:
            return
        side, self._pending = self._pending, None
        self.submit_order(
            self.order_factory.market(
                instrument_id=self._iid, order_side=side, quantity=Quantity.from_int(10)
            )
        )


_CASES = [
    pytest.param("AAPL", "5m", _stock_stamps, id="stock-5m-overnight"),
    pytest.param("BTC/USDT", "1h", _crypto_stamps, id="crypto-1h"),
]


@pytest.mark.parametrize(("symbol", "timeframe", "stamps"), _CASES)
@pytest.mark.parametrize("fee_bps", [0.0, 25.0])
@pytest.mark.parametrize(("buy_at", "sell_at"), [(1, None), (2, 3), (3, 4)])
def test_orders_decided_on_bar_close_fill_at_the_next_bar_open(
    symbol: str,
    timeframe: str,
    stamps: Callable[[], list[datetime]],
    fee_bps: float,
    buy_at: int,
    sell_at: int | None,
) -> None:
    tf = parse_timeframe(timeframe)
    instrument = instrument_for(symbol)
    bars = _ladder(symbol, stamps())
    bar_type = bar_type_for(symbol, tf)
    feed = to_execution_feed(
        bars, bar_type, price_precision=instrument.price_precision, timeframe=tf
    )
    strategy = _TradeOnBars(bar_type, instrument.id, buy_at=buy_at, sell_at=sell_at)
    result = run_backtest(
        instrument, feed, strategy, account_type=AccountType.MARGIN, fee_bps=fee_bps
    )
    # Decision bar k (1-based) is bars[k-1]; its order fills at bars[k]'s open, 1 microsecond in.
    expected = [("BUY", bars[buy_at])] + ([("SELL", bars[sell_at])] if sell_at else [])
    observed = sorted(result.fill_trace, key=lambda f: (f.ts, f.sequence_id))
    assert [(f.side, f.ts, f.quantity) for f in observed] == [
        (side, bar.ts + _QUOTE_DELAY, 10.0) for side, bar in expected
    ]
    for fill, (_, bar) in zip(observed, expected, strict=True):
        assert fill.price == pytest.approx(bar.open)
    shifted = [bar.model_copy(update={"ts": bar.ts + _QUOTE_DELAY}) for bar in bars]
    curve = rederive_equity_curve(result, shifted, fee_bps=fee_bps, cash=_CASH)
    assert_curves_equal(list(result.equity_curve), curve)
    assert result.final_equity == pytest.approx(curve[-1][1], abs=ENGINE_MONEY_ABS)
