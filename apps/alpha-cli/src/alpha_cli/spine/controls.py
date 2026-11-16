"""Research-only opposite-direction execution and descriptive walk-forward efficiency."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import numpy as np

from alpha_cli.spine import diagnostics as d
from alpha_core import ActionType, Bar, CorporateAction, DataError
from alpha_validation.metrics import FloatSeq, cagr, to_returns

if TYPE_CHECKING:
    from alpha_backtest.results import BacktestResult
    from alpha_cli._runner import RunSpec


# The control's book starts this many times larger than the rule's. Instruments trade in whole
# units (one share, one coin), so a short book that loses most of its capital would otherwise
# round to zero units and stop trading (seen on BTC/USDT daily). Every reported control figure is
# a ratio (Sharpe, total return) or a count, so the scale changes nothing else.
CONTROL_CAPITAL_SCALE = 1000.0
_WFE_BASIS = "annualised OOS / IS return; a practitioner rule of thumb, not a statistical test"


def run_inverted_backtest(
    bars: Sequence[Bar],
    spec: RunSpec,
    original: BacktestResult,
    *,
    dividends: Sequence[CorporateAction] = (),
) -> BacktestResult:
    """Replay causal rule signals with opposite all-in targets, using the ordinary engine.

    The rule-test vocabulary has no price stops or short entries. Negative raw signals mean
    flat in that lane, and remain flat here; only executable long entries become shorts.
    Sizing uses the control's own equity with the same entry reserve and lot rounding, re-sized
    to 100% of equity on every decision bar (the long side's exposure by construction); those
    small re-sizing trades pay the same fee and slippage.
    MARGIN is needed solely to execute the hypothetical short control on CASH markets.
    """
    from nautilus_trader.model.data import Bar as NautilusBar
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.enums import AccountType

    from alpha_backtest.engine import run_backtest
    from alpha_backtest.feed import bar_type_for, to_execution_feed
    from alpha_backtest.instruments import instrument_for
    from alpha_strategies.base import VolTargetStrategy

    if (
        spec.sizing != "all_in"
        or spec.allow_short
        or spec.strategy_name not in {"ma_crossover", "breakout", "ts_momentum"}
        or spec.halt_drawdown is not None
    ):
        raise DataError("inverted control requires a supported long/flat all-in rule-test spec")
    signals = {row.ts: row.signal for row in original.decision_trace}
    if not signals:
        raise DataError("inverted control requires the original close-time decision signals")

    pending = sorted(
        (item.ex_date, item.pay_date or item.ex_date, float(item.amount))
        for item in dividends
        if item.action_type is ActionType.DIVIDEND and item.amount is not None
    )

    class InvertedRule(VolTargetStrategy):
        # The engine debits a short's dividends in its equity curve, but the shared sizing reads
        # equity without dividend cash. Left alone, a short re-sized from that figure keeps
        # growing against an unseen and mounting debit until recorded equity turns negative.
        # Track the same cash here, by the engine's rule (pre-fill holding at the first session
        # on or after the ex-date; cash from the first session on or after the pay date).
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._dividend_cash = 0.0
            self._due = list(pending)
            self._payable: list[tuple[date, float]] = []

        def on_quote_tick(self, quote: QuoteTick) -> None:
            session = datetime.fromtimestamp(int(quote.ts_event) / 1e9, tz=UTC).date()
            while self._due and self._due[0][0] <= session:
                _, pay, amount = self._due.pop(0)
                if self.net_units != 0.0:
                    self._payable.append((pay, amount * self.net_units))
            self._dividend_cash += sum(cash for pay, cash in self._payable if pay <= session)
            self._payable = [(pay, cash) for pay, cash in self._payable if pay > session]
            super().on_quote_tick(quote)

        def _net_liq(self) -> float:
            return super()._net_liq() + self._dividend_cash

        def _signal(self) -> int:
            ts = self._history_ts[-1]
            signal = signals.get(ts)
            if signal is None:
                raise DataError(f"original rule signal is unavailable at {ts}")
            return signal

        def _all_in_target(self) -> float:
            # An all-in long held in fixed units stays ~100% of equity as the price moves; a
            # short held in fixed units does not (its exposure grows as it loses, past 100% of
            # equity and into negative equity on a long trend). Re-size the short to 100% of
            # current equity on every decision bar so both sides carry the same exposure. The
            # base method re-sizes from equity whenever no long is held.
            return -super()._all_in_target()

        def _record_decision(
            self, bar: NautilusBar, *, signal: int | None, target_quantity: float, reason: str
        ) -> None:
            super()._record_decision(
                bar,
                signal=-signal if signal is not None and signal > 0 else 0,
                target_quantity=target_quantity,
                reason=f"inverted_control:{reason}",
            )

    instrument = instrument_for(bars[0].symbol)
    bar_type = bar_type_for(bars[0].symbol)
    strategy = InvertedRule(
        instrument_id=instrument.id,
        bar_type=bar_type,
        min_history=spec.min_train,
        capital=spec.starting_cash * CONTROL_CAPITAL_SCALE,
        max_leverage=spec.max_leverage,
        rebalance_every=spec.rebalance_every,
        periods_per_year=spec.periods_per_year,
        allow_short=False,
        sizing="all_in",
    )
    strategy.configure_sizing_costs(fee_bps=spec.fee_bps, slippage_bps=spec.slippage_bps)
    feed = to_execution_feed(
        bars,
        bar_type,
        price_precision=instrument.price_precision,
        size_precision=instrument.size_precision,
        slippage_bps=spec.slippage_bps,
    )
    result = run_backtest(
        instrument,
        feed,
        strategy,
        starting_cash=spec.starting_cash * CONTROL_CAPITAL_SCALE,
        account_type=AccountType.MARGIN,
        leverage=spec.max_leverage,
        fee_bps=spec.fee_bps,
        dividends=dividends,
    )
    if result.rejected:
        raise DataError(f"inverted control had {result.rejected} rejected orders")
    return result


def control_label(
    original: float | None, inverted: float | None, original_trades: int, inverted_trades: int
) -> str:
    if min(original_trades, inverted_trades) < 30 or original is None or inverted is None:
        return "inconclusive"
    if original > 0 and inverted > 0 and inverted >= original / 2:
        return "control failed"
    if inverted < 0:
        return "control passed"
    return "inconclusive"


def _fmt(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.2f}"


def _reading(
    label: str, original: Mapping[str, Any], sharpe: float | None, trades: int, market: float | None
) -> str:
    """One plain sentence for the label; never more than the evidence says."""
    rule, opposite = _fmt(original["sharpe"]), _fmt(sharpe)
    pair = f"Sharpe {opposite} against {rule} for the rule"
    if min(original["trades"], trades) < 30:
        return (
            "This check cannot tell either way: fewer than 30 closed trades "
            f"(rule {original['trades']}, opposite {trades})."
        )
    if sharpe is None or original["sharpe"] is None:
        return "This check cannot tell either way: a Sharpe ratio is unavailable."
    if label == "control failed":
        return (
            f"Trading the opposite of this rule also made money on average ({pair}): the result "
            "may come from the market's drift, the data or the costs, not the rule."
        )
    if label == "control passed" and original["sharpe"] <= 0:
        return (
            f"Trading the opposite of this rule lost money (Sharpe {opposite}), but the rule "
            f"itself did not make money either (Sharpe {rule}), so this says nothing about an "
            "edge; both directions losing usually points to trading costs."
        )
    if label == "control passed":
        caveat = (
            f" The market rose over this period (buy and hold {market:+.0%}), so trading against "
            "it was expected to lose; this check is weak here."
            if market is not None and market > 0
            else ""
        )
        return (
            f"Trading the opposite of this rule lost money ({pair}), as a real edge would; "
            f"this alone does not prove an edge.{caveat}"
        )
    if original["sharpe"] <= 0:
        return f"This check cannot tell either way: the rule itself did not make money ({pair})."
    return (
        "This check cannot tell either way: the opposite trade roughly broke even or made a "
        f"little money ({pair})."
    )


def _suffix(se: float | None, hypothetical: bool) -> str:
    text = (
        ""
        if se is None
        else f" The opposite Sharpe has a standard error of about {se:.2f} (a rough estimate "
        "that assumes independent, normally distributed returns)."
    )
    text += " No borrowing or funding cost is charged on the opposite (short) trades."
    if hypothetical:
        text += " Shorts are not tradable here; this is a control only."
    return text


def inverted_summary(
    original: Mapping[str, Any],
    equity: FloatSeq,
    trades: int,
    ppy: int,
    *,
    hypothetical: bool,
    market_return: float | None,
) -> dict[str, Any]:
    """Net Sharpe and an IID-normal asymptotic SE (Lo 2002, IID-normal case).

    sqrt((1 + SR_per_period**2 / 2) / n) is scaled by sqrt(ppy), like the Sharpe.
    This descriptive approximation assumes IID normal returns; it never decides the label.
    ``market_return`` is buy and hold over the same bars: a long-only rule's opposite loses on a
    rising market whatever the rule does, so a passed control there is said to be weak.
    """
    performance = d.performance(equity, ppy, "opposite-direction full-sample engine run")
    sharpe = performance["sharpe"]
    se = (
        None if sharpe is None else math.sqrt((ppy + sharpe * sharpe / 2) / len(to_returns(equity)))
    )
    label = control_label(original["sharpe"], sharpe, original["trades"], trades)
    reasons = {f"inverted_{key}": value for key, value in performance["reasons"].items()}
    if se is None:
        reasons["inverted_sharpe_se"] = reasons["inverted_sharpe"]
    return {
        "basis": (
            "opposite-direction full-sample engine run, same bars, costs and next-open fills; "
            "no borrowing or funding cost on shorts; research control only, not a trial"
        ),
        "original_sharpe": original["sharpe"],
        "original_total_return": original["total_return"],
        "original_trades": original["trades"],
        "market_total_return": market_return,
        "inverted_sharpe": sharpe,
        "inverted_sharpe_se": se,
        "inverted_total_return": performance["total_return"],
        "inverted_trades": trades,
        "label": label,
        "sentence": _reading(label, original, sharpe, trades, market_return)
        + _suffix(se, hypothetical),
        "reasons": reasons,
        "se_basis": "IID-normal asymptotic standard error; Lo (2002), IID-normal case; annualised",
        "hypothetical": hypothetical,
    }


def unavailable_control(original: Mapping[str, Any], reason: str) -> dict[str, Any]:
    """A control that could not run is recorded with its reason; it never aborts the rule test."""
    names = ("inverted_sharpe", "inverted_sharpe_se", "inverted_total_return", "inverted_trades")
    return {
        "basis": "opposite-direction full-sample engine run; research control only, not a trial",
        "original_sharpe": original["sharpe"],
        "original_total_return": original["total_return"],
        "original_trades": original["trades"],
        **dict.fromkeys(names),
        "label": None,
        "sentence": (
            "Trading the opposite of this rule lost more than its whole stake (its account went "
            "below zero), so its Sharpe cannot be computed and this check gives no label."
            if "positive finite equity" in reason
            else f"The opposite-direction check could not be run: {reason}."
        ),
        "reasons": {name: reason for name in (*names, "label")},
    }


def in_sample_rows(
    folds: Sequence[Mapping[str, Any]], equity: FloatSeq, ppy: int, *, first_tradable: int
) -> list[dict[str, Any]]:
    """Annualise each fold's recorded train window of the same full-run return series.

    The walk-forward folds index ``to_returns(equity)``; the window starts no earlier than
    ``first_tradable``, the first return the rule could hold a position over (warm-up bars are
    flat by construction and would dilute the in-sample figure). No split is created here.
    """
    returns = to_returns(equity)
    rows = []
    for fold in folds:
        start, end = max(int(fold["train_start"]), first_tradable), int(fold["train_end"])
        if end > returns.size:
            raise DataError("walk-forward fold indexes beyond the full-sample return series")
        row: dict[str, Any] = {
            "index": fold["index"],
            "is_start": start,
            "is_end": end,
            "is_cagr": None,
            "oos_cagr": fold["oos_cagr"],
        }
        segment = np.asarray(returns[start:end], dtype=float)
        path = np.concatenate(([1.0], np.cumprod(1.0 + segment)))
        if segment.size == 0:
            row["is_reason"] = "in-sample window is warm-up only; the rule could not trade yet"
        elif not bool(np.all(path > 0.0)):
            row["is_reason"] = "in-sample equity reached zero"
        else:
            row["is_cagr"] = cagr(path, periods_per_year=ppy)
        rows.append(row)
    return rows


def _fold_reason(fold: Mapping[str, Any]) -> str | None:
    ins, oos = fold.get("is_cagr"), fold.get("oos_cagr")
    if fold.get("is_reason"):
        return str(fold["is_reason"])
    if ins is None:
        return "this run recorded no in-sample segment"
    if not math.isfinite(ins) or ins <= 0:
        return "in-sample return is zero or negative"
    if oos is None or not math.isfinite(oos):
        return "this fold recorded no usable out-of-sample return"
    return None


def walk_forward_efficiency(folds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Median OOS/IS annualised return over the folds where it is defined; never a pass/fail.

    Folds whose ratio is undefined are kept with their reason and left out of the median, and the
    sentence says how many were left out.
    """
    rows = []
    for index, fold in enumerate(folds):
        reason = _fold_reason(fold)
        rows.append(
            {
                "index": fold.get("index", index),
                **{key: fold[key] for key in ("is_start", "is_end") if key in fold},
                "is_cagr": fold.get("is_cagr"),
                "oos_cagr": fold.get("oos_cagr") if reason is None else None,
                "wfe": None if reason else fold["oos_cagr"] / fold["is_cagr"],
                "reason": reason,
            }
        )
    defined = [row["wfe"] for row in rows if row["wfe"] is not None]
    distinct = {row["reason"] for row in rows}
    reason = (
        None
        if defined
        else "this run recorded no in-sample segment"
        if not rows
        else str(next(iter(distinct)))
        if len(distinct) == 1
        else "no fold had both a positive in-sample return and an out-of-sample return"
    )
    median = float(np.median(defined)) if defined else None
    if median is None:
        sentence = f"Walk-forward efficiency is unavailable: {reason}."
    else:
        left_out = len(rows) - len(defined)
        scope = (
            f"median of {len(rows)} folds"
            if not left_out
            else f"median of {len(defined)} of {len(rows)} folds; {left_out} fold"
            f"{'s' if left_out > 1 else ''} left out because the rule was still warming up, its "
            "in-sample return was not positive, or a figure was missing"
        )
        sentence = (
            f"Out of sample the rule's yearly return was {median:.0%} of its in-sample yearly "
            f"return ({scope})."
        )
        if median < 0:
            sentence += " Negative means it lost money out of sample on a typical fold."
    return {
        "basis": _WFE_BASIS,
        "wfe": median,
        "fold_count": len(defined),
        "folds_total": len(rows),
        "folds": rows,
        "reasons": {"wfe": reason} if reason else {},
        "sentence": sentence + " This is a practitioner rule of thumb, not a statistical test.",
    }
