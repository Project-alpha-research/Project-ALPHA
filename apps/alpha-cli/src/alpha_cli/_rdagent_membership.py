"""Point-in-time membership and causal missing-bar accounting for the factor judge.

Span summaries describe the frozen input only; trading never consults an instrument's last
future bar. Haircuts are conservative assumptions, not measured delisting recoveries.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import numpy as np
import polars as pl

from alpha_backtest.portfolio_replay import ReplayPeriod, WeightTarget
from alpha_core import DataError

REENTRY_BARS = 20
WRITE_OFF_AFTER_DAYS = 30
DELISTING_HAIRCUT = 0.30
RESERVED_DAY = date(2024, 1, 1)
POLICY = {
    "schema": "AlphaRdagentGapPolicyV1",
    "reentry_bars": REENTRY_BARS,
    "write_off_after_days": WRITE_OFF_AFTER_DAYS,
    "delisting_haircut": DELISTING_HAIRCUT,
    "assumption": "The 30% haircut is a conservative assumption, not a measured recovery.",
}


def panel_summary(panel: pl.DataFrame) -> dict[str, Any]:
    last = max(panel["date"].to_list())
    instruments = {}
    for key, group in panel.partition_by("instrument", as_dict=True).items():
        days = sorted(group["date"].to_list())
        gaps = [(b - a).days - 1 for a, b in zip(days, days[1:], strict=False)]
        instruments[str(key[0])] = {
            "rows": len(days),
            "first_day": days[0].isoformat(),
            "last_day": days[-1].isoformat(),
            "missing_days": sum(gaps),
            "longest_gap": max(gaps, default=0),
            "ends_early": days[-1] < last,
        }
    return {
        "instruments": instruments,
        "missing_instrument_days": sum(v["missing_days"] for v in instruments.values()),
        "instruments_ended_early": sum(v["ends_early"] for v in instruments.values()),
        "longest_gap": max(v["longest_gap"] for v in instruments.values()),
        "gap_policy": POLICY,
    }


def membership(prices: np.ndarray, price_days: list[date], days: list[date]) -> np.ndarray:
    """Twenty consecutive daily bars, including today; never consult a future bar."""
    if len(price_days) != len(prices) or any(
        (b - a).days != 1 for a, b in zip(price_days, price_days[1:], strict=False)
    ):
        raise DataError("membership requires consecutive dated price rows")
    streak = np.zeros(prices.shape[1], dtype=int)
    masks = {}
    for day, row in zip(price_days, prices, strict=True):
        streak = np.where(np.isfinite(row), streak + 1, 0)
        masks[day] = streak >= REENTRY_BARS
    return np.array([masks.get(day, np.zeros(prices.shape[1], dtype=bool)) for day in days])


def forward_returns(
    opens: np.ndarray,
    closes: np.ndarray,
    days: list[date],
    starts: list[int],
    ends: list[int],
    *,
    counted: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, int]]:
    """Keep normal open-to-open windows; unresolved exits use the waiting rule's close.

    An order without its next open never entered (cash return zero). For a missing exit, use
    the first close through endpoint + 30 days, or last close times 0.7. An unresolved label
    whose search would enter the reserved window stays null. Counts cover ``counted`` cells
    (the names ranked that day) when given.
    """
    if (
        opens.shape != closes.shape
        or len(days) != len(opens)
        or any(d >= RESERVED_DAY for d in days)
    ):
        raise DataError("forward labels require aligned pre-reserved matrices")
    result = np.full((len(starts), opens.shape[1]), np.nan)
    counts = {"gap_forward_returns": 0, "haircut_forward_returns": 0, "unfilled_entries": 0}
    for row, (start, end) in enumerate(zip(starts, ends, strict=True)):
        for j in range(opens.shape[1]):
            count = int(counted is None or counted[row, j])
            if not math.isfinite(opens[start, j]):
                result[row, j] = 0.0
                counts["unfilled_entries"] += count
                continue
            if math.isfinite(opens[end, j]):
                result[row, j] = opens[end, j] / opens[start, j] - 1
                continue
            deadline = days[end] + timedelta(days=WRITE_OFF_AFTER_DAYS)
            resumed = next(
                (
                    k
                    for k in range(end, len(days))
                    if days[k] <= deadline and math.isfinite(closes[k, j])
                ),
                None,
            )
            if resumed is not None:
                result[row, j] = closes[resumed, j] / opens[start, j] - 1
                counts["gap_forward_returns"] += count
            elif deadline < RESERVED_DAY and deadline <= days[-1]:
                known = [k for k in range(end) if math.isfinite(closes[k, j])]
                if known:
                    result[row, j] = (
                        closes[known[-1], j] * (1 - DELISTING_HAIRCUT) / opens[start, j] - 1
                    )
                    counts["haircut_forward_returns"] += count
    return result, counts


class Account:
    """One long-only cash ledger. Missing holdings cannot finance new buys."""

    def __init__(self, symbols: list[str], *, fee_bps: float, slippage_bps: float) -> None:
        self.symbols = symbols
        self.cash = 1_000_000.0
        self.quantities = np.zeros(len(symbols))
        self.average_entry = np.zeros(len(symbols))
        self.last = np.full(len(symbols), np.nan)
        self.last_days: list[date | None] = [None] * len(symbols)
        self.waiting = np.zeros(len(symbols), dtype=bool)
        self.fee_rate, self.slippage_rate = fee_bps / 10000, slippage_bps / 10000
        self.haircuts = 0
        self.written_off_at_panel_end = 0
        self.events: list[dict[str, Any]] = []
        self.fees = self.slippage = self.notional = 0.0

    def equity(self, marks: np.ndarray) -> float:
        prices = np.where(np.isfinite(marks), marks, self.last)
        total = self.cash + sum(
            float(q * p) for q, p in zip(self.quantities, prices, strict=True) if q > 0
        )
        if not math.isfinite(total) or total <= 0:
            raise DataError("replay net liquidation became non-positive")
        return total

    def trade(self, j: int, delta: float, raw: float, day: date, basis: str) -> None:
        if abs(delta) <= 1e-12:
            return
        if not math.isfinite(raw) or raw <= 0 or self.quantities[j] + delta < -1e-12:
            raise DataError("invalid long-only gap replay fill")
        delta, raw = float(delta), float(raw)
        price = raw * (1 + math.copysign(self.slippage_rate, delta))
        fee = abs(delta) * price * self.fee_rate
        notional = abs(delta) * price
        self.cash += notional - fee if delta < 0 else -(notional + fee)
        previous = float(self.quantities[j])
        realized = -delta * (price - self.average_entry[j]) if delta < 0 else 0.0
        if delta > 0:
            self.average_entry[j] = (previous * self.average_entry[j] + delta * price) / (
                previous + delta
            )
        self.quantities[j] = max(0.0, previous + delta)
        self.fees += fee
        self.slippage += abs(delta) * abs(price - raw)
        self.notional += abs(delta) * raw
        self.events.append(
            {
                "date": day,
                "instrument": self.symbols[j],
                "quantity": delta,
                "price": price,
                "basis": basis,
                "fee": fee,
                "realized_pnl_before_fees": float(realized),
            }
        )

    def execute(self, deltas: np.ndarray, opens: np.ndarray, day: date) -> None:
        permitted = np.isfinite(opens) & ~self.waiting
        for j in range(len(opens)):
            if permitted[j] and deltas[j] < 0:
                self.trade(j, -min(-deltas[j], self.quantities[j]), float(opens[j]), day, "open")
        buys = [j for j in range(len(opens)) if permitted[j] and deltas[j] > 0]
        required = sum(
            float(deltas[j] * opens[j]) * (1 + self.slippage_rate) * (1 + self.fee_rate)
            for j in buys
        )
        scale = min(1.0, max(0.0, self.cash) / required) if required > 0 else 1.0
        for j in buys:
            self.trade(j, float(deltas[j]) * scale, float(opens[j]), day, "open")
        if abs(self.cash) <= 1e-8:
            self.cash = 0.0
        # Pro-rata arithmetic can leave sub-ulp cash on a large book; it cannot finance buys.
        tolerance = max(1e-8, 16 * math.ulp(max(1.0, self.notional)))
        if self.cash < -tolerance:
            raise DataError(f"gap replay attempted to borrow: {self.cash}")

    def write_off(self, j: int, day: date, *, terminal: bool = False) -> None:
        quantity = float(self.quantities[j])
        price = float(self.last[j]) * (1 - DELISTING_HAIRCUT)
        # Administrative write-off, not a tradable fill: no fictional fee or slippage.
        self.cash += quantity * price
        self.quantities[j] = 0.0
        self.waiting[j] = False
        self.haircuts += 1
        self.written_off_at_panel_end += terminal
        self.events.append(
            {
                "date": day,
                "instrument": self.symbols[j],
                "quantity": -quantity,
                "price": price,
                "basis": "panel-end-writeoff" if terminal else "writeoff",
                "fee": 0.0,
                "realized_pnl_before_fees": float(quantity * (price - self.average_entry[j])),
            }
        )

    def observe(self, day: date, closes: np.ndarray, *, terminal: bool = False) -> None:
        for j, close in enumerate(closes):
            if math.isfinite(close):
                if self.waiting[j] and self.quantities[j] > 0:
                    self.trade(j, -float(self.quantities[j]), float(close), day, "resume-close")
                self.waiting[j] = False
                self.last[j], self.last_days[j] = close, day
            elif self.quantities[j] > 0:
                self.waiting[j] = True
                last_day = self.last_days[j]
                if last_day is None:
                    raise DataError("missing last-bar provenance for held position")
                if (day - last_day).days >= WRITE_OFF_AFTER_DAYS:
                    self.write_off(j, day)
                elif terminal:
                    self.write_off(j, day, terminal=True)


def replay_weights(
    scores: np.ndarray,
    closes: np.ndarray,
    base: np.ndarray,
    base_closes: np.ndarray,
    *,
    rebalance: bool,
    direction: int,
    min_names: int,
    fraction: float,
    unseen: np.ndarray | None = None,
) -> np.ndarray:
    """Same thirds and drift as the canonical clock; unavailable weights stay cash."""
    if unseen is not None and unseen.any():
        # Even inserting a zero into a NumPy reduction can change its rounding and create a
        # residual trade. Compute on the original columns until a new identity has a bar.
        weights = np.zeros(len(scores))
        weights[~unseen] = replay_weights(
            scores[~unseen],
            closes[~unseen],
            base[~unseen],
            base_closes[~unseen],
            rebalance=rebalance,
            direction=direction,
            min_names=min_names,
            fraction=fraction,
        )
        return weights
    available = [j for j, value in enumerate(scores) if math.isfinite(value)]
    if len(available) < min_names:
        return np.zeros(len(scores))
    if rebalance:
        selected = sorted(available, key=lambda j: (-direction * scores[j], j))
        k = max(1, round(fraction * len(available)))
        return np.array([1 / k if j in selected[:k] else 0.0 for j in range(len(scores))])
    weights = np.zeros(len(scores))
    active = (base > 0) & np.isfinite(closes) & np.isfinite(base_closes) & np.isfinite(scores)
    weights[active] = base[active] * (closes[active] / base_closes[active])
    if weights.sum() > 0:
        weights /= weights.sum()
    return weights


def _orders(account: Account, weights: np.ndarray, closes: np.ndarray) -> np.ndarray:
    locked = sum(
        float(q * p)
        for q, p, waiting in zip(account.quantities, account.last, account.waiting, strict=True)
        if waiting and q > 0
    )
    investable = account.equity(closes) - locked
    deltas = np.zeros(len(closes))
    for j, close in enumerate(closes):
        if math.isfinite(close) and not account.waiting[j]:
            deltas[j] = float(weights[j]) * investable / float(close) - account.quantities[j]
    return deltas


def _missing_bar_period(opens: np.ndarray, accounts: list[Account], segments: np.ndarray) -> bool:
    # A declared future identity has no history yet. Its empty column cannot switch an
    # earlier ordinary period to the missing-bar diagnostic. Existing receipts are unchanged.
    unseen = segments & ~np.isfinite(accounts[0].last)
    return bool((~np.isfinite(opens) & ~unseen).any() or any(a.waiting.any() for a in accounts))


def run_gap_replay(
    opens: np.ndarray,
    closes: np.ndarray,
    sessions: list[date],
    scores: np.ndarray,
    eligible: np.ndarray,
    symbols: list[str],
    *,
    horizon: int,
    direction: int,
    min_names: int,
    fraction: float,
    fee_bps: float,
    slippage_bps: float,
    identity_segments: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Causal account loop with canonical close-sized orders, sells first and pro-rata buys.

    All paths use the same loop, independent of whether a future bar will be absent. The gross
    diagnostic keeps the canonical target-weight return on ordinary periods. Missing periods
    use actual carried positions, with a separate zero-cost basket subject to the same waits.
    """
    accounts = [
        Account(symbols, fee_bps=fee_bps, slippage_bps=slippage_bps),
        Account(symbols, fee_bps=0, slippage_bps=0),
        Account(symbols, fee_bps=0, slippage_bps=0),
    ]
    pending = [np.zeros(len(symbols)) for _ in accounts]
    weights = base = np.zeros(len(symbols))
    base_closes = closes[0]
    base_scores = np.zeros(len(symbols))
    abnormal: list[bool] = []
    targets: list[WeightTarget] = []
    positions: list[dict[str, Any]] = []
    periods: list[ReplayPeriod] = []
    entries: dict[int, float] = {}
    endpoints: dict[int, list[float]] = {}
    costs: dict[int, list[float]] = {}
    previous = [1_000_000.0] * 3
    rebalances = skipped = missing = 0
    segments = np.array([name in identity_segments for name in symbols])
    equity_curve = [1_000_000.0]
    for i, day in enumerate(sessions):
        abnormal.append(_missing_bar_period(opens[i], accounts, segments))
        opening = [
            account.equity(np.where(account.waiting, np.nan, opens[i])) for account in accounts
        ]
        if i >= 1:
            entries[i] = opening[0]
            if i > 1:
                endpoints[i - 1] = opening
        for account, orders in zip(accounts, pending, strict=True):
            account.execute(orders, opens[i], day)
            account.observe(day, closes[i], terminal=i == len(sessions) - 1)
        final = i >= len(scores) + 1 and not any(a.quantities.any() for a in accounts)
        if (i == len(sessions) - 1 or final) and i > 1:
            endpoints[i - 1] = [a.equity(closes[i]) for a in accounts]
        # Costs on the final flatten belong to the final preceding open-to-open period.
        attribution = i - 1 if final or i == len(sessions) - 1 else i
        cost = costs.setdefault(attribution, [0.0, 0.0, 0.0])
        cost[0] += accounts[0].fees
        cost[1] += accounts[0].slippage
        cost[2] += accounts[0].notional
        for account in accounts:
            account.fees = account.slippage = account.notional = 0.0
        positions.append(
            {
                "date": day,
                "cash": accounts[0].cash,
                "quantities": accounts[0].quantities.tolist(),
                "equity": accounts[0].equity(closes[i]),
            }
        )
        if i > 1:
            current = endpoints[i - 1]
            held = targets[(i - 2) * len(symbols) : (i - 1) * len(symbols)]
            names = (
                np.flatnonzero(eligible[i - 2]) if i - 2 < len(scores) else np.array([], dtype=int)
            )
            periods.append(
                _period(
                    sessions[i - 1 : i + 1],
                    opens[i - 1 : i + 1],
                    held,
                    names,
                    current,
                    previous,
                    costs.get(i - 1, [0.0, 0.0, 0.0]),
                    entries[i - 1],
                    ordinary=bool(held) and not any(abnormal[i - 1 : i + 1]),
                )
            )
            previous = current
            equity_curve.append(current[0])
        if final or i == len(sessions) - 1:
            break
        if i < len(scores):
            skipped += np.isfinite(scores[i]).sum() < min_names
            rebalance = i % horizon == 0
            weights = replay_weights(
                scores[i],
                closes[i],
                base,
                base_closes,
                rebalance=rebalance,
                direction=direction,
                min_names=min_names,
                fraction=fraction,
                unseen=segments & ~np.isfinite(accounts[0].last),
            )
            if rebalance:
                base, base_closes = weights.copy(), closes[i].copy()
                base_scores = np.where(np.isfinite(scores[i]), direction * scores[i], 0.0)
                rebalances += 1
                missing += int((~np.isfinite(scores[i])).sum())
            origin = datetime.combine(day, time(), UTC)
            targets.extend(
                WeightTarget(
                    symbol=name,
                    origin_ts=origin,
                    available_at=origin + timedelta(hours=23),
                    target_ts=origin + timedelta(days=1),
                    target_weight=float(weights[j]),
                    score=float(base_scores[j]),
                    fold=0,
                )
                for j, name in enumerate(symbols)
            )
            basket = eligible[i].astype(float)
            if basket.sum():
                basket /= basket.sum()
        else:
            weights, basket = np.zeros(len(symbols)), np.zeros(len(symbols))
        pending = [
            _orders(account, weight, closes[i])
            for account, weight in zip(accounts, [weights, weights, basket], strict=True)
        ]
    return {
        "periods": periods,
        "targets": targets,
        "positions": positions,
        "events": accounts[0].events,
        "equity_curve": equity_curve,
        "rebalances": rebalances,
        "breadth_skipped_days": int(skipped),
        "missing_coin_days": missing,
        "haircuts_applied": accounts[0].haircuts,
        "written_off_at_panel_end": accounts[0].written_off_at_panel_end,
        "benchmark_haircuts_applied": accounts[2].haircuts,
    }


def holding_returns(
    opens: np.ndarray,
    closes: np.ndarray,
    days: list[date],
    starts: list[int],
    ends: list[int],
    *,
    counted: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, int]]:
    """Hypothetical spread positions obey the same causal wait as replay holdings.

    Counts describe the ordinary tie order's top and bottom legs, not both tie-order checks.
    A missed entry is uninvested cash. A gap inside the hold triggers exit even before its
    scheduled endpoint; an outstanding hold is valued conservatively at panel end.
    """
    if (
        opens.shape != closes.shape
        or len(opens) != len(days)
        or any(d >= RESERVED_DAY for d in days)
    ):
        raise DataError("spread holdings require aligned pre-reserved matrices")
    result = np.full((len(starts), opens.shape[1]), np.nan)
    counts = {
        "haircuts_applied": 0,
        "written_off_at_panel_end": 0,
        "gap_exits": 0,
        "unfilled_entries": 0,
    }
    for row, (start, end) in enumerate(zip(starts, ends, strict=True)):
        for j in range(opens.shape[1]):
            count = int(counted is None or counted[row, j])
            if not math.isfinite(opens[start, j]):
                result[row, j] = 0.0
                counts["unfilled_entries"] += count
                continue
            gap = next(
                (k for k in range(start + 1, end + 1) if not math.isfinite(opens[k, j])), None
            )
            if gap is None:
                result[row, j] = opens[end, j] / opens[start, j] - 1
                continue
            last = gap - 1
            deadline = days[last] + timedelta(days=WRITE_OFF_AFTER_DAYS)
            resumed = next(
                (
                    k
                    for k in range(gap, len(days))
                    if days[k] <= deadline and math.isfinite(closes[k, j])
                ),
                None,
            )
            if resumed is not None:
                exit_price = closes[resumed, j]
                counts["gap_exits"] += count
            else:
                exit_price = closes[last, j] * (1 - DELISTING_HAIRCUT)
                counts["haircuts_applied"] += count
                counts["written_off_at_panel_end"] += count * (deadline > days[-1])
            result[row, j] = exit_price / opens[start, j] - 1
    return result, counts


def _period(
    days: list[date],
    opens: np.ndarray,
    held: list[WeightTarget],
    names: np.ndarray,
    current: list[float],
    previous: list[float],
    paid: list[float],
    entry: float,
    *,
    ordinary: bool,
) -> ReplayPeriod:
    gross, benchmark = current[1] / previous[1] - 1, current[2] / previous[2] - 1
    if ordinary:
        gross = sum(
            t.target_weight * (opens[1, j] / opens[0, j] - 1)
            for j, t in enumerate(held)
            if t.target_weight or np.isfinite(opens[:, j]).all()
        )
        if len(names):
            benchmark = sum(opens[1, j] / opens[0, j] - 1 for j in names) / len(names)
    net = current[0] / previous[0] - 1
    return ReplayPeriod(
        fold=0,
        target_ts=datetime.combine(days[0], time(), UTC),
        exit_ts=datetime.combine(days[1], time(), UTC),
        gross_return=float(gross),
        net_return=float(net),
        benchmark_return=float(benchmark),
        excess_return=float(net - benchmark),
        turnover=paid[2] / entry,
        fees=paid[0],
        slippage_cost=paid[1],
    )
