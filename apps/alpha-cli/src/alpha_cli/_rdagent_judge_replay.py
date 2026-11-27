"""The replay half of the RD-Agent judge: ALPHA weight replay, gap replay, panel membership.

Split out of `_rdagent_judge` unchanged; `rdagent_factor_eval` re-exports `replay` and
`panel_membership` from here."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import numpy as np
import polars as pl

from alpha_backtest.portfolio_replay import run_weight_replay
from alpha_cli import _rdagent_membership as membership
from alpha_cli._rdagent_clocks import CLOCKS, clock_targets
from alpha_cli._rdagent_costs import judge_costs
from alpha_cli._rdagent_judge import ANNUAL_DAYS, EXPLORATION, MIN_NAMES, TOP_FRACTION, matrix
from alpha_cli.toolbox.reserve import RESERVED_DAY
from alpha_core import Bar, DataError


def _return_metrics(values: np.ndarray) -> dict[str, float]:
    sd = float(values.std(ddof=1))
    if not np.isfinite(values).all() or sd <= 0:
        raise DataError("degenerate replay excess return series")
    curve = np.concatenate(([1.0], np.cumprod(1 + values)))
    return {
        "annualized_return": float(values.mean()) * ANNUAL_DAYS,
        "compounded_return": float(curve[-1] - 1),
        "sharpe": float(values.mean()) / sd * math.sqrt(ANNUAL_DAYS),
        "per_observation_sharpe": float(values.mean()) / sd,
        "max_drawdown": float(np.min(curve / np.maximum.accumulate(curve) - 1)),
    }


def replay(
    panel: pl.DataFrame,
    signal: np.ndarray,
    days: list[date],
    direction: int,
    *,
    clock: str = "daily",
    series: dict[str, Any] | None = None,
    gap_policy: bool = False,
    identity_segments: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any], np.ndarray]:
    if gap_policy:
        return _gap_replay(
            panel,
            signal,
            days,
            direction,
            clock=clock,
            series=series,
            identity_segments=identity_segments,
        )
    sessions = [days[0] + timedelta(days=n) for n in range((days[-1] - days[0]).days + 3)]
    if sessions[-1] >= RESERVED_DAY or (panel["date"] >= RESERVED_DAY).any():
        raise DataError("replay reaches reserved window")
    rows = panel.filter(pl.col("date").is_between(sessions[0], sessions[-1]))
    symbols = sorted(panel["instrument"].unique().to_list())
    bars = {}
    for name in symbols:
        group = rows.filter(pl.col("instrument") == name).sort("date")
        if group["date"].to_list() != sessions:
            raise DataError("replay requires a complete daily session rectangle")
        bars[name] = [
            Bar(
                symbol=name,
                ts=datetime.combine(r["date"], time(), UTC),
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
            )
            for r in group.iter_rows(named=True)
        ]
    targets, missing, cash_days, rebalances = clock_targets(
        signal,
        matrix(panel, "close", days, symbols),
        days,
        symbols,
        direction,
        clock,
        top_fraction=TOP_FRACTION,
        min_names=MIN_NAMES,
    )
    costs = judge_costs()
    result = run_weight_replay(
        bars, targets, fee_bps=costs["fee_bps"], slippage_bps=costs["slippage_bps"]
    )
    if series is not None:
        series.update(periods=result.periods, targets=targets)
    net = np.array([p.excess_return for p in result.periods])
    gross = np.array([p.gross_return - p.benchmark_return for p in result.periods])
    return {
        "net": _return_metrics(net),
        "gross": _return_metrics(gross),
        "mean_turnover": float(np.mean([p.turnover for p in result.periods])),
        "turnover_per_rebalance": sum(p.turnover for p in result.periods) / rebalances,
        "annual_cost": (
            sum(p.fees + p.slippage_cost for p in result.periods)
            / float(np.mean([equity for _, equity in result.backtest.equity_curve]))
            * ANNUAL_DAYS
            / len(result.periods)
        ),
        "rebalances": rebalances,
        "unrankable_instrument_rebalances": missing,
        "cash_days": cash_days,
        "tie_break": "equal fractional boundary weights",
        "available_at": (
            "origin session + 23h (ALPHA canonical daily close stamp; bar d contains the full "
            "UTC day)"
        ),
    }, net


def panel_membership(panel: pl.DataFrame, days: list[date], symbols: list[str]) -> np.ndarray:
    start = min(panel["date"].to_list())
    history = [start + timedelta(days=i) for i in range((days[-1] - start).days + 1)]
    return membership.membership(matrix(panel, "close", history, symbols), history, days)


def _gap_replay(
    panel: pl.DataFrame,
    signal: np.ndarray,
    days: list[date],
    direction: int,
    *,
    clock: str,
    series: dict[str, Any] | None,
    identity_segments: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any], np.ndarray]:
    if (panel["date"] >= RESERVED_DAY).any() or days[-1] + timedelta(days=2) >= RESERVED_DAY:
        raise DataError("replay reaches reserved window")
    if days[0] != date.fromisoformat(EXPLORATION[0]) or any(
        (b - a).days != 1 for a, b in zip(days, days[1:], strict=False)
    ):
        raise DataError("replay needs consecutive days from the exploration phase")
    symbols = sorted(panel["instrument"].unique().to_list())
    last = max(panel["date"].to_list())
    if last < days[-1] + timedelta(days=2):
        raise DataError("replay needs two trailing panel days")
    sessions = [days[0] + timedelta(days=i) for i in range((last - days[0]).days + 1)]
    eligible = panel_membership(panel, days, symbols)
    costs = judge_costs()
    scores = np.where(eligible, signal, np.nan)
    data = membership.run_gap_replay(
        matrix(panel, "open", sessions, symbols),
        matrix(panel, "close", sessions, symbols),
        sessions,
        scores,
        eligible,
        symbols,
        horizon=CLOCKS[clock],
        direction=direction,
        min_names=MIN_NAMES,
        fraction=TOP_FRACTION,
        fee_bps=costs["fee_bps"],
        slippage_bps=costs["slippage_bps"],
        identity_segments=identity_segments,
    )
    periods = data["periods"]
    net = np.array([p.excess_return for p in periods])
    gross = np.array([p.gross_return - p.benchmark_return for p in periods])
    if series is not None:
        series.update({key: data[key] for key in ("periods", "targets", "positions", "events")})
    metrics = {
        "net": _return_metrics(net),
        "gross": _return_metrics(gross),
        "mean_turnover": float(np.mean([p.turnover for p in periods])),
        "turnover_per_rebalance": sum(p.turnover for p in periods) / data["rebalances"],
        "annual_cost": sum(p.fees + p.slippage_cost for p in periods)
        / float(np.mean(data["equity_curve"]))
        * ANNUAL_DAYS
        / len(periods),
        "gap_policy": membership.POLICY,
        "unrankable_instrument_rebalances": data["missing_coin_days"],
        "writeoff_instruments": sorted(
            {
                e["instrument"]
                for e in data["events"]
                if e["basis"] in ("writeoff", "panel-end-writeoff")
            }
        ),
        **{
            key: data[key]
            for key in (
                "rebalances",
                "breadth_skipped_days",
                "haircuts_applied",
                "written_off_at_panel_end",
                "benchmark_haircuts_applied",
            )
        },
    }
    return metrics, net
