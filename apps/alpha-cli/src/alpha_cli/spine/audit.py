"""Mechanical observations over a run's trace frames; no overall grade."""

from __future__ import annotations

from datetime import datetime

import polars as pl


def audit(
    decisions: pl.DataFrame | None,
    orders: pl.DataFrame | None,
    fills: pl.DataFrame | None,
    ranges: dict[datetime, tuple[float, float]],
    *,
    fee: float,
    slippage: float,
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
    else:
        invalid = sum(
            row["ts"] not in ranges
            or not ranges[row["ts"]][0] <= row["price"] <= ranges[row["ts"]][1]
            for row in fills.iter_rows(named=True)
        )
        add(
            "fills-inside-bar-range",
            invalid == 0,
            f"{invalid} of {fills.height} fills are outside a matched bar's low–high.",
        )
    add(
        "costs-charged",
        fee > 0 and slippage > 0,
        f"Spec fee {fee:g} bps and slippage {slippage:g} bps.",
    )
    add("enough-trades", trades >= 30, f"{trades} closed walk-forward trades; threshold 30.")
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
