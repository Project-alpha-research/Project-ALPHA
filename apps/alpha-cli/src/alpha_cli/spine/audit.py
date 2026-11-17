"""Mechanical observations over a run's trace frames; no overall grade."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

import polars as pl

from alpha_validation.verdict import VerdictSummary

if TYPE_CHECKING:
    from alpha_cli import _gauntlet

ENOUGH_TRADES = 30
IMPLAUSIBLE_SHARPE = 3.0
IMPLAUSIBLE_HIT_RATE = 0.80
IMPLAUSIBLE_MEAN_TRADE = 0.05


def capped_verdict(verdict: VerdictSummary, trades: int) -> VerdictSummary:
    """C is the existing middle grade; sparse trades cannot improve a lower grade."""
    if trades >= ENOUGH_TRADES:
        return verdict
    return replace(
        verdict,
        overall="C" if verdict.overall in ("A", "B") else verdict.overall,
        detail={**verdict.detail, "overall_gpa": min(2.0, verdict.detail["overall_gpa"])},
    )


def cap_sparse_run(
    out: _gauntlet.GauntletOutput, result: dict[str, Any]
) -> _gauntlet.GauntletOutput:
    trades = len(out.result.trades)
    if trades >= ENOUGH_TRADES:
        return out
    if "too-few-trades" not in result["labels"]:
        result["labels"].append("too-few-trades")
    result["sentence"] = f"Only {trades} closed trades: too few to judge."
    if out.report.verdict is None:
        return out
    return replace(
        out, report=replace(out.report, verdict=capped_verdict(out.report.verdict, trades))
    )


def plausibility(
    sharpe: float | None,
    hit_rate: float | None,
    mean_trade: float | None,
    trades: int,
    *,
    daily: bool,
) -> list[dict[str, str]]:
    raised = trades >= ENOUGH_TRADES and (
        (sharpe is not None and sharpe > IMPLAUSIBLE_SHARPE)
        or (hit_rate is not None and hit_rate > IMPLAUSIBLE_HIT_RATE)
        or (daily and mean_trade is not None and mean_trade > IMPLAUSIBLE_MEAN_TRADE)
    )
    return (
        [
            {
                "flag": "implausibly-good",
                "detail": (
                    "This looks too good: check for a data error or a look at the future "
                    "before believing it."
                ),
            }
        ]
        if raised
        else []
    )


def audit(
    decisions: pl.DataFrame | None,
    orders: pl.DataFrame | None,
    fills: pl.DataFrame | None,
    ranges: dict[datetime, tuple[float, float]],
    *,
    fee: float | None,
    slippage: float | None,
    trades: int,
    years: float,
    labels: list[str],
    benchmark: bool,
    variants: int,
) -> list[dict[str, str]]:
    items = []

    def add(check: str, passed: bool | None, detail: str) -> None:
        items.append(
            {
                "check": check,
                "status": "NOT-CHECKED" if passed is None else "PASS" if passed else "FLAG",
                "detail": detail,
            }
        )

    if decisions is None or orders is None or fills is None:
        add("fills-after-decisions", None, "Decision, order or fill trace artifact is absent.")
    else:
        decision_times = dict(decisions.select("sequence_id", "ts").iter_rows())
        parents = dict(orders.select("sequence_id", "decision_sequence_id").iter_rows())
        invalid = sum(
            (when := decision_times.get(parents.get(row["order_sequence_id"]))) is None
            or row["ts"] <= when
            for row in fills.iter_rows(named=True)
        )
        add(
            "fills-after-decisions",
            invalid == 0,
            f"{invalid} of {fills.height} fills lack a strictly earlier linked decision.",
        )
    if fills is None or not ranges:
        add("fills-inside-bar-range", None, "Fill trace or source bar ranges are absent.")
    elif fee is None or slippage is None:
        add("fills-inside-bar-range", None, "Recorded cost settings are absent.")
    else:
        invalid = sum(
            row["ts"] not in ranges
            or not ranges[row["ts"]][0] * (1 - slippage / 10_000)
            <= row["price"]
            <= ranges[row["ts"]][1] * (1 + slippage / 10_000)
            for row in fills.iter_rows(named=True)
        )
        add(
            "fills-inside-bar-range",
            invalid == 0,
            f"{invalid} of {fills.height} fills are outside a matched bar's low–high "
            f"allowing recorded slippage of {slippage:g} bps.",
        )
    if fee is None or slippage is None:
        add("costs-charged", None, "Recorded cost settings are absent.")
    else:
        add(
            "costs-charged",
            fee > 0 and slippage > 0,
            f"Spec fee {fee:g} bps and slippage {slippage:g} bps.",
        )
    add(
        "enough-trades",
        trades >= ENOUGH_TRADES,
        f"{trades} closed walk-forward trades; threshold {ENOUGH_TRADES}.",
    )
    add(
        "benchmark-present",
        benchmark,
        "Full-sample benchmark metrics are available."
        if benchmark
        else "Some benchmark metrics are unavailable.",
    )
    add("history-length", years >= 3, f"{years:.3f} years of bars; threshold 3 years.")
    add("artifacts-intact", None, "Artifact verification must complete before publication.")
    add(
        "quick-run",
        "quick" not in labels,
        "Run carries the quick label."
        if "quick" in labels
        else "Run does not carry the quick label.",
    )
    add("variants-counted", True, f"{variants} sensitivity variants recorded for the ledger row.")
    return items
