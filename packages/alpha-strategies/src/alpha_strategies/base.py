"""Shared nautilus wiring for vol-targeted long/flat/short strategies (spec §7).

``VolTargetStrategy`` factors out the execution lifecycle every signal-based strategy in ALPHA
shares: accumulate OHLC history, rebalance on a fixed cadence, turn a ``{-1,0,1}`` signal into a
vol-targeted position, decide on the close of bar ``t`` and fill at the open of ``t+1`` (the
look-ahead-free convention enforced by ``alpha_backtest.feed`` + ``bar_execution=False``). CASH
buys in backtests are checked against free cash plus fees at the opening quote after the close-time
target is fixed. Concrete strategies implement only the pure ``_signal`` hook.
(``TimeSeriesMomentum`` predates this base and remains the standalone reference implementation;
this base is the template for the rest.)
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any

from nautilus_trader.model.data import Bar as NautilusBar
from nautilus_trader.model.data import BarType, QuoteTick
from nautilus_trader.model.enums import AccountType, OrderSide, TimeInForce
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Money, Quantity
from nautilus_trader.trading.strategy import Strategy

from alpha_core import (
    Bar,
    ChartAnnotationTrace,
    DataError,
    DecisionTrace,
    ExecutionRejectionTrace,
    IndicatorTrace,
    bps_rate,
)
from alpha_strategies.sizing import realized_volatility, vol_target_size


def _sum_money(pnls: Any) -> float:
    """Sum a nautilus per-currency PnL dict to a float (single base currency in v1)."""
    return float(sum(money.as_double() for money in pnls.values()))


def normalize_order_quantity(
    delta: float, *, size_precision: int, size_increment: float
) -> Quantity | None:
    """Return a valid venue quantity without changing the legacy integer-lot SIM path.

    Existing simulations round to the nearest integer, so that exact behavior is retained when
    the instrument advertises precision ``0`` and increment ``1``.  Fractional live quantities
    are rounded down to the nearest positive venue increment to avoid exceeding the target.
    """
    magnitude = abs(delta)
    if size_precision == 0 and size_increment == 1.0:
        lots = round(magnitude)
        return Quantity.from_int(lots) if lots > 0 else None
    if size_increment <= 0.0:
        raise DataError(f"instrument size_increment must be > 0, got {size_increment}")
    raw = Decimal(str(magnitude))
    increment = Decimal(str(size_increment))
    steps = (raw / increment).to_integral_value(rounding=ROUND_DOWN)
    normalized = steps * increment
    if normalized <= 0:
        return None
    return Quantity(float(normalized), size_precision)


class VolTargetStrategy(Strategy):  # type: ignore[misc]  # nautilus Strategy is untyped (Cython)
    """Base for vol-targeted signal strategies: decide on close of t, fill at open of t+1.

    Subclasses set ``min_history`` (closes needed before the first decision) and implement
    ``_signal() -> int`` over ``self._closes`` / ``self._highs`` / ``self._lows``. Holds its own
    ``net_units`` (updated from fills) so the target→order delta is self-contained + deterministic.
    """

    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        bar_type: BarType,
        min_history: int,
        vol_window: int = 63,
        target_vol: float = 0.15,
        capital: float = 1_000_000.0,
        max_leverage: float = 1.0,
        rebalance_every: int = 21,
        periods_per_year: int = 252,
        allow_short: bool = True,
        sizing: str = "vol_target",
        size_on_equity: bool = False,
        halt_drawdown: float | None = None,
        fixed_quantity: float | None = None,
        fixed_entry_once: bool = False,
    ) -> None:
        super().__init__()
        if sizing not in ("vol_target", "all_in"):
            raise DataError(f"unknown sizing {sizing!r}; expected vol_target or all_in")
        if sizing == "all_in" and allow_short:
            raise DataError("all_in sizing is incompatible with allow_short=True")
        if sizing == "all_in" and fixed_quantity is not None:
            raise DataError("all_in sizing is incompatible with fixed_quantity")
        self._sizing = sizing
        self._all_in_cost_factor = 1.0
        if type(fixed_entry_once) is not bool or (fixed_entry_once and fixed_quantity is None):
            raise DataError("single entry attempt requires explicit fixed quantity")
        if fixed_quantity is not None and (
            type(fixed_quantity) not in (int, float)
            or not math.isfinite(fixed_quantity)
            or fixed_quantity <= 0
            or allow_short is not False
            or size_on_equity is not False
            or halt_drawdown is not None
            or type(rebalance_every) is not int
            or rebalance_every != 1
        ):
            raise DataError("fixed quantity requires positive finite units, daily long/flat sizing")
        self._fixed_quantity = fixed_quantity
        self._fixed_entry_once = fixed_entry_once
        self._fixed_entry_attempted = False
        if halt_drawdown is not None and not 0.0 < halt_drawdown < 1.0:
            raise DataError(f"halt_drawdown must be in (0, 1) or None, got {halt_drawdown}")
        self._iid = instrument_id
        self._bar_type = bar_type
        self._vol_window = vol_window
        self._target_vol = target_vol
        self._capital = capital
        self._max_leverage = max_leverage
        self._rebalance_every = rebalance_every
        self._periods_per_year = periods_per_year
        self._allow_short = allow_short  # spec §7: equities long-flat (False), crypto/FX long-short
        # risk controls (both opt-in; defaults preserve the fixed-capital, no-halt behavior):
        # size_on_equity re-bases the vol-target notional on CURRENT net-liq each rebalance, so
        # exposure de-levers in drawdowns instead of silently gearing up; halt_drawdown is a
        # kill-switch - once net-liq breaches peak*(1-halt_drawdown) the book goes flat for good.
        self._size_on_equity = size_on_equity
        self._halt_drawdown = halt_drawdown
        self._peak_equity = capital
        self.halted = False
        self._min_history = (
            min_history
            if fixed_quantity is not None or sizing == "all_in"
            else max(min_history, vol_window + 1)
        )
        self._closes: list[float] = []
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._history_ts: list[datetime] = []
        self._eligible_bars = 0  # bars seen once history suffices; drives the rebalance cadence
        self._target_units: float | None = None
        self.net_units = 0.0
        self.fills = 0
        self.resized_entries = 0
        self.rejections = 0  # orders denied (risk/buying-power) or rejected by the venue
        self.execution_rejections: list[ExecutionRejectionTrace] = []
        self._cash_fee_rate: float | None = None
        self._backtest_account_type: AccountType | None = None
        self._decision_trace: list[DecisionTrace] = []
        self._indicator_trace: list[IndicatorTrace] = []
        self._chart_annotations: list[ChartAnnotationTrace] = []

    @property
    def history_size(self) -> int:
        """Number of bars currently held by the strategy (including warmup bars)."""
        return len(self._closes)

    @property
    def eligible_bars(self) -> int:
        """Number of post-warmup bars counted by the rebalance cadence."""
        return self._eligible_bars

    @property
    def pending_target(self) -> float | None:
        """The next-open target, exposed read-only."""
        return self._target_units

    @property
    def decision_trace(self) -> tuple[DecisionTrace, ...]:
        """Observed close-time decisions; indicators/patterns are intentionally not inferred."""
        return tuple(self._decision_trace)

    @property
    def indicator_trace(self) -> tuple[IndicatorTrace, ...]:
        """Causal indicator values captured by the strategy at each decision."""
        return tuple(self._indicator_trace)

    @property
    def chart_annotations(self) -> tuple[ChartAnnotationTrace, ...]:
        """Deterministic vector annotations captured from the same trailing decision prefix."""
        return tuple(self._chart_annotations)

    def _indicator_snapshot(self) -> Mapping[str, tuple[float, str]]:
        """Named values visible at the current decision; subclasses add strategy indicators."""
        return {"close": (self._closes[-1], "price")}

    def _annotation_snapshot(self, decision_ts: datetime) -> Sequence[ChartAnnotationTrace]:
        """Vector evidence for the current decision; most strategies need no annotation."""
        del decision_ts
        return ()

    def _record_decision(
        self,
        bar: NautilusBar,
        *,
        signal: int | None,
        target_quantity: float,
        reason: str,
    ) -> None:
        decision_ts = datetime.fromtimestamp(int(bar.ts_event) / 1_000_000_000, tz=UTC)
        self._decision_trace.append(
            DecisionTrace(
                ts=decision_ts,
                instrument_id=str(self._iid),
                signal=signal,
                target_quantity=target_quantity,
                reason=reason,
            )
        )
        for name, (value, unit) in sorted(self._indicator_snapshot().items()):
            self._indicator_trace.append(
                IndicatorTrace(
                    ts=decision_ts,
                    instrument_id=str(self._iid),
                    name=name,
                    value=value,
                    unit=unit,
                )
            )
        self._chart_annotations.extend(self._annotation_snapshot(decision_ts))

    def configure_cash_execution(self, *, fee_bps: float, account_type: AccountType) -> None:
        """Configure the backtest-only fee-aware order affordability check."""
        self._cash_fee_rate = bps_rate(fee_bps)
        self._backtest_account_type = account_type

    def configure_sizing_costs(self, *, fee_bps: float, slippage_bps: float) -> None:
        """Reserve entry frictions in a close-time all-in target."""
        self._all_in_cost_factor = (1.0 + bps_rate(fee_bps)) * (1.0 + bps_rate(slippage_bps))

    def _all_in_target(self) -> float:
        """Hold existing units; on entry reserve fees, slippage and a 0.2% gap buffer."""
        if self.net_units > 0.0:
            return self.net_units
        instrument = self.cache.instrument(self._iid)
        if instrument is None:
            raise DataError(f"all_in sizing requires instrument {self._iid}")
        equity = self._net_liq()
        if not math.isfinite(equity):
            raise DataError("all_in sizing requires finite net liquidation equity")
        units = max(0.0, equity) * 0.998 / (self._closes[-1] * self._all_in_cost_factor)
        increment = Decimal(str(instrument.size_increment))
        steps = (Decimal(str(units)) / increment).to_integral_value(rounding=ROUND_DOWN)
        return float(steps * increment)

    def _append_history(self, ts: datetime, close: float, high: float, low: float) -> bool:
        """Append one bar and advance cadence; return whether this bar may rebalance."""
        self._closes.append(close)
        self._highs.append(high)
        self._lows.append(low)
        self._history_ts.append(ts)
        if len(self._closes) < self._min_history:
            return False
        rebalance_due = self._eligible_bars % self._rebalance_every == 0
        self._eligible_bars += 1
        return rebalance_due

    def prime_history(self, bars: Sequence[Bar]) -> None:
        """Warm indicators and cadence from PIT bars without creating targets or orders.

        The caller must first enforce the snapshot's provenance and knowledge cutoff.  This method
        additionally requires strictly increasing timestamps and intentionally performs only the
        history/cadence portion of :meth:`on_bar`; historical decisions cannot leak into the live
        session as a pending order.
        """
        previous = None
        for bar in bars:
            if previous is not None and bar.ts <= previous:
                raise ValueError("warmup bars must have strictly increasing timestamps")
            self._append_history(bar.ts, bar.close, bar.high, bar.low)
            previous = bar.ts
        self._target_units = None

    def _net_liq(self) -> float:
        """Current net-liquidation equity (same formula as the engine's recorder)."""
        venue = self._iid.venue
        return (
            self._capital
            + _sum_money(self.portfolio.realized_pnls(venue))
            + _sum_money(self.portfolio.unrealized_pnls(venue))
        )

    def _signal(self) -> int:
        """Return the {-1, 0, 1} signal from the accumulated history. Implemented by subclasses."""
        raise NotImplementedError

    def on_start(self) -> None:
        self.subscribe_bars(self._bar_type)
        self.subscribe_quote_ticks(self._iid)

    def on_bar(self, bar: NautilusBar) -> None:
        # Decide on the close of t; the order is placed at the next open (see on_quote_tick).
        decision_ts = datetime.fromtimestamp(int(bar.ts_event) / 1_000_000_000, tz=UTC)
        rebalance_due = self._append_history(
            decision_ts, float(bar.close), float(bar.high), float(bar.low)
        )
        if not rebalance_due:
            return
        capital = self._capital
        if self._size_on_equity or self._halt_drawdown is not None:
            equity = self._net_liq()
            self._peak_equity = max(self._peak_equity, equity)
            if self._halt_drawdown is not None and (
                self.halted or equity <= self._peak_equity * (1.0 - self._halt_drawdown)
            ):
                self.halted = True  # kill-switch: flatten at the next open, never re-enter
                self._target_units = 0.0
                self._record_decision(bar, signal=None, target_quantity=0.0, reason="drawdown_halt")
                return
            if self._size_on_equity:
                if equity <= 0.0:
                    self._target_units = 0.0  # blown-up book cannot be vol-sized; stay flat
                    self._record_decision(
                        bar, signal=None, target_quantity=0.0, reason="nonpositive_equity"
                    )
                    return
                capital = equity
        signal = self._signal()
        if signal == 0 or (signal < 0 and not self._allow_short):
            self._target_units = 0.0  # flat: no signal, or a short we are not permitted to take
            reason = "flat_signal" if signal == 0 else "short_disallowed"
            self._record_decision(bar, signal=signal, target_quantity=0.0, reason=reason)
            return
        if self._sizing == "all_in":
            self._target_units = self._all_in_target()
            self._record_decision(
                bar, signal=signal, target_quantity=self._target_units, reason="all_in_target"
            )
            return
        if self._fixed_quantity is not None:
            complete = self._fixed_entry_once and self._fixed_entry_attempted
            self._target_units = self.net_units if complete else self._fixed_quantity
            self._record_decision(
                bar,
                signal=signal,
                target_quantity=self._target_units,
                reason="control_entry_attempt_complete" if complete else "fixed_quantity_target",
            )
            return
        annualized_vol = realized_volatility(
            self._closes[-(self._vol_window + 1) :], periods_per_year=self._periods_per_year
        )
        if annualized_vol <= 0.0:
            self._target_units = 0.0  # no realized volatility to target this window -> hold flat
            self._record_decision(bar, signal=signal, target_quantity=0.0, reason="zero_volatility")
            return
        self._target_units = vol_target_size(
            signal,
            self._closes[-1],
            annualized_vol,
            target_vol=self._target_vol,
            capital=capital,
            max_leverage=self._max_leverage,
        )
        self._record_decision(
            bar, signal=signal, target_quantity=self._target_units, reason="target"
        )

    def on_quote_tick(self, quote: QuoteTick) -> None:
        # execute the pending target at the session open (t+1)
        if self._target_units is None:
            return
        target = self._target_units
        self._target_units = None
        if self._fixed_entry_once and target > 0.0:
            self._fixed_entry_attempted = True
        delta = target - self.net_units
        instrument = self.cache.instrument(self._iid)
        if instrument is None:
            self.rejections += 1
            return
        side = OrderSide.BUY if delta > 0.0 else OrderSide.SELL
        quantity = normalize_order_quantity(
            delta,
            size_precision=int(instrument.size_precision),
            size_increment=float(instrument.size_increment),
        )
        if quantity is None:
            return
        if side == OrderSide.BUY:
            quantity = self._cash_buy_quantity(quantity, quote, instrument)
            if quantity is None:
                return
        order = self.order_factory.market(
            instrument_id=self._iid,
            order_side=side,
            quantity=quantity,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)

    def _cash_buy_quantity(
        self, quantity: Quantity, quote: QuoteTick, instrument: Instrument
    ) -> Quantity | None:
        """Keep affordable targets; fit equity-sized CASH entries from flat to the opening ask.

        Raising an open long and covering a short keep the whole-order refusal.
        """
        can_resize = (
            self._fixed_quantity is None
            and self.net_units == 0.0
            and (self._sizing == "all_in" or self._size_on_equity)
        )
        if (
            self._backtest_account_type != AccountType.CASH
            or self._cash_fee_rate is None
            or (self._cash_fee_rate == 0.0 and not can_resize)
        ):
            return quantity
        price = float(quote.ask_price)
        notional = float(quantity) * price
        currency = instrument.quote_currency
        principal = Money(notional, currency)
        commission = Money(notional * self._cash_fee_rate, currency)
        account = self.portfolio.account(self._iid.venue)
        available = account.balance_free(currency) if account is not None else None
        if available is None:
            raise DataError(
                f"CASH fee affordability requires a free {currency} balance for {self._iid}"
            )
        required_cash_money = principal + commission
        available_cash = available.as_double()
        if required_cash_money > available:
            if can_resize:
                resized = self._affordable_entry(quantity, instrument, price, available)
                if resized is not None:
                    self.resized_entries += 1
                    return resized
            # With no affordable lot, retain the previous refusal path, including venue denial
            # for zero-fee orders. Fixed-unit orders and short covers keep their old behavior.
            if self._cash_fee_rate == 0.0:
                return quantity
            reason = (
                "cash_notional_exceeds_free_balance"
                if principal > available
                else "cash_plus_commission_exceeds_free_balance"
            )
            self.rejections += 1
            required_cash = required_cash_money.as_double()
            self.execution_rejections.append(
                ExecutionRejectionTrace(
                    ts=datetime.fromtimestamp(int(quote.ts_event) / 1_000_000_000, tz=UTC),
                    instrument_id=str(self._iid),
                    side="BUY",
                    requested_quantity=float(quantity),
                    reference_price=price,
                    available_cash=available_cash,
                    estimated_fee=commission.as_double(),
                    required_cash=required_cash,
                    reason=reason,
                )
            )
            return None
        return quantity

    def _affordable_entry(
        self, requested: Quantity, instrument: Instrument, price: float, available: Money
    ) -> Quantity | None:
        """Largest whole size step affordable under the existing rounded principal/fee model.

        Quote-quantity market orders convert notional to units without reserving commission.
        Search the size steps instead: both currency rounding and non-unit increments matter.
        Only the current quote and account balance enter this calculation.
        """
        assert self._cash_fee_rate is not None
        increment = Decimal(str(instrument.size_increment))
        low, high = 0, int(Decimal(str(requested)) / increment)
        while low < high:
            steps = (low + high + 1) // 2
            notional = float(steps * increment) * price
            cost = Money(notional, instrument.quote_currency) + Money(
                notional * self._cash_fee_rate, instrument.quote_currency
            )
            if cost <= available:
                low = steps
            else:
                high = steps - 1
        return Quantity(float(low * increment), instrument.size_precision) if low else None

    def on_stop(self) -> None:
        """Cancel this strategy's open orders; safe stop intentionally never flattens positions."""
        self.cancel_all_orders(self._iid)

    def on_order_filled(self, event: OrderFilled) -> None:
        self.fills += 1
        qty = float(event.last_qty)
        self.net_units += qty if event.order_side == OrderSide.BUY else -qty

    def on_order_denied(self, event: object) -> None:
        # pre-trade risk denial (e.g. notional exceeds CASH buying power) — count, never swallow
        self.rejections += 1

    def on_order_rejected(self, event: object) -> None:
        self.rejections += 1
