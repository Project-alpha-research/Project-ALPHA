"""The owner's rule set as a nautilus ``Strategy`` (spec 2026-09-01 §4.2, Phase 5 S4).

Decision logic is ``rules.rule_signal`` over exactly ``spec.history`` trailing bars; this class is
only the vol-target wiring inherited from ``VolTargetStrategy`` (decide on close of ``t``, fill at
open of ``t+1``). The indicator snapshot records every operand's value on the decision bar so the
causal trace shows *why* the rule held.
"""

from __future__ import annotations

from collections.abc import Mapping

from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId

from alpha_patterns import OHLCV
from alpha_strategies.base import VolTargetStrategy
from alpha_strategies.rules import (
    Operand,
    OperandValue,
    RuleSpec,
    evaluate_values,
    last_values,
    trailing_ohlcv,
)


class RuleStrategy(VolTargetStrategy):
    """Be long while every ``long_when`` holds, short while every ``short_when`` holds.

    Explicit ``fixed_quantity`` selects daily long/flat fixed units instead of volatility
    sizing: no quantity changes while long, flatten on a flat signal, same units on re-entry.
    It requires ``allow_short=False`` and keeps the shared next-open affordability checks.
    ``fixed_entry_once`` consumes the first positive entry attempt even if unaffordable;
    subsequent long decisions hold actual units, supporting a strict buy-and-hold control.
    """

    def __init__(
        self,
        *,
        instrument_id: InstrumentId,
        bar_type: BarType,
        spec: RuleSpec,
        vol_window: int = 63,
        target_vol: float = 0.15,
        capital: float = 1_000_000.0,
        max_leverage: float = 1.0,
        rebalance_every: int = 1,
        periods_per_year: int = 252,
        allow_short: bool = True,
        sizing: str = "vol_target",
        size_on_equity: bool = False,
        halt_drawdown: float | None = None,
        fixed_quantity: float | None = None,
        fixed_entry_once: bool = False,
    ) -> None:
        super().__init__(
            instrument_id=instrument_id,
            bar_type=bar_type,
            min_history=spec.history,
            vol_window=vol_window,
            target_vol=target_vol,
            capital=capital,
            max_leverage=max_leverage,
            rebalance_every=rebalance_every,
            periods_per_year=periods_per_year,
            allow_short=allow_short,
            sizing=sizing,
            size_on_equity=size_on_equity,
            halt_drawdown=halt_drawdown,
            fixed_quantity=fixed_quantity,
            fixed_entry_once=fixed_entry_once,
        )
        self._spec = spec
        self._values_bar = -1  # the bar count ``_values`` belongs to (history is append-only)
        self._values: dict[Operand, float] = {}
        self._value_of: OperandValue | None = None

    def _window(self) -> OHLCV:
        return trailing_ohlcv(
            self._highs,
            self._lows,
            self._closes,
            history=self._spec.history,
            symbol=str(self._iid),
        )

    def _bar_values(self) -> OperandValue:
        """Operand values on the current decision bar, each computed once per bar from one window:
        the decision and the indicator trace read the same numbers."""
        if self._values_bar != len(self._closes):
            self._values_bar, self._values, self._value_of = len(self._closes), {}, None
        values = self._values

        def value(operand: Operand) -> float:
            if operand not in values:
                if self._value_of is None:
                    self._value_of = last_values(self._window())
                values[operand] = self._value_of(operand)
            return values[operand]

        return value

    def _signal(self) -> int:
        return evaluate_values(self._spec, self._bar_values(), self._spec.history)

    def _indicator_snapshot(self) -> Mapping[str, tuple[float, str]]:
        values = dict(super()._indicator_snapshot())
        value = self._bar_values()
        for operand in self._spec.operands:
            if operand.kind == "indicator":
                unit = "index" if operand.indicator == "rsi" else "price"
                values[operand.label] = (value(operand), unit)
        return values
