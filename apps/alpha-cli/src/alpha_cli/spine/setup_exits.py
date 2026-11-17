"""Frozen trigger-close levels and conservative long-only measured outcomes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

MAX_HOLD_BARS = 250
PATTERN_LEVEL_REASON = "this exit depends on the pattern's own levels; random dates have none"


@dataclass(frozen=True)
class PreparedExits:
    bars: list[Any]
    levels: dict[str, tuple[str, float, list[Any]]]
    opposite: list[Any]
    time_bars: int
    time_reason: str
    warmup: int
    control_reason: str | None


def prepare_exits(spec: Any, bars: list[Any]) -> PreparedExits:
    """Compile the evaluator's own causal expressions once, for all possible starts."""
    import polars as pl

    from alpha_study.setup.expr import compile_expr
    from alpha_study.setup.spec import parse_exit

    if not bars:
        raise ValueError("trade requires bars")
    for i, bar in enumerate(bars):
        if any(
            not math.isfinite(getattr(bar, k)) or getattr(bar, k) <= 0
            for k in ("open", "high", "low", "close")
        ):
            raise ValueError("trade prices must be positive and finite")
        if i and bar.ts <= bars[i - 1].ts:
            raise ValueError("trade bars must be strictly increasing")
    frame = pl.DataFrame(
        {k: [getattr(b, k) for b in bars] for k in ("open", "high", "low", "close", "volume")}
    )
    levels: dict[str, tuple[str, float, list[Any]]] = {}
    warmup = 0
    for name in ("stop", "target"):
        text = getattr(spec.exit, name)
        if text is None:
            continue
        if text in spec.reference:
            text = spec.reference[text]
        value = parse_exit(text)
        if value.kind == "percent":
            levels[name] = (value.kind, float(value.multiplier or 1), [])
        else:
            expression = compile_expr(
                f"atr({value.period})" if value.kind == "atr" else str(value.level)
            )
            warmup = max(warmup, expression.warmup)
            levels[name] = (
                value.kind,
                float(value.multiplier or 1),
                frame.select(expression.expr.alias("value"))["value"].to_list(),
            )
    opposite: list[Any] = [False] * len(bars)
    if spec.exit.opposite:
        expression = compile_expr(spec.exit.opposite)
        warmup = max(warmup, expression.warmup)
        opposite = frame.select(expression.expr.alias("value"))["value"].to_list()
    return PreparedExits(
        bars,
        levels,
        opposite,
        spec.exit.time_bars or MAX_HOLD_BARS,
        "time" if spec.exit.time_bars else "max-hold",
        warmup,
        None,
    )


def _levels(prepared: PreparedExits, start: int) -> tuple[dict[str, Any], bool]:
    price = prepared.bars[start].open
    levels: dict[str, Any] = {"stop": None, "target": None}
    valid = True
    for name, (kind, multiplier, values) in prepared.levels.items():
        distance = price * multiplier / 100 if kind == "percent" else values[start - 1]
        level = (
            None
            if distance is None
            else (
                distance
                if kind == "level"
                else price
                + (1 if name == "target" else -1) * distance * (multiplier if kind == "atr" else 1)
            )
        )
        levels[name] = level
        valid &= (
            level is not None
            and math.isfinite(level)
            and (level < price if name == "stop" else level > price)
        )
    return levels, valid


def simulate(prepared: PreparedExits, start: int, cost: float) -> dict[str, Any]:
    """Walk future bars only to measure the outcome; they never change initial levels.

    Adverse excursion uses lows while held; an open fill sees only that open. A stop
    fill caps the exit bar at its fill price because its later low was never held.
    """
    bars = prepared.bars
    if not 1 <= start < len(bars) or not math.isfinite(cost) or cost < 0:
        raise ValueError("invalid trade entry position or cost")
    price = bars[start].open
    levels, valid = _levels(prepared, start)
    row = dict(
        entry_index=start,
        entry_ts=bars[start].ts,
        entry_price=price,
        **levels,
        exit_index=None,
        exit_ts=None,
        exit_price=None,
        reason="invalid-levels",
        bars_held=0,
        gross_return=None,
        net_return=None,
        r_multiple=None,
        worst_adverse_move=None,
        both_touched=0,
        complete=False,
    )
    if not valid:
        return row
    stop, target = levels["stop"], levels["target"]
    worst, both = price, 0
    end, fill, reason = len(bars) - 1, bars[-1].close, "open-at-end"
    for i in range(start, len(bars)):
        bar = bars[i]
        stop_hit = stop is not None and bar.low <= stop
        target_hit = target is not None and bar.high >= target
        both += int(stop_hit and target_hit)
        if i > start and stop is not None and bar.open <= stop:
            end, fill, reason = i, bar.open, "stop-gap"
            worst = min(worst, fill)
            break
        if stop_hit:
            end, fill, reason = i, stop, "stop"
            worst = min(worst, fill)
            break
        worst = min(worst, bar.open if target_hit and bar.open >= target else bar.low)
        if target_hit:
            end, fill, reason = i, target, "target"
            break
        if prepared.opposite[i] is True:
            if i + 1 < len(bars):
                end, fill, reason = i + 1, bars[i + 1].open, "opposite"
                worst = min(worst, fill)
            break
        if i - start + 1 == prepared.time_bars:
            end, fill, reason = i, bar.close, prepared.time_reason
            break
    open_exit = reason in {"opposite", "stop-gap"} or (
        reason == "target" and bars[end].open >= target
    )
    gross = fill / price - 1
    return {
        **row,
        "exit_index": end,
        "exit_ts": bars[end].ts,
        "exit_price": fill,
        "reason": reason,
        "bars_held": end - start + (0 if open_exit else 1),
        "gross_return": gross,
        "net_return": gross - cost,
        "r_multiple": (gross - cost) / ((price - stop) / price) if stop is not None else None,
        "worst_adverse_move": worst / price - 1,
        "both_touched": both,
        "complete": reason != "open-at-end",
    }


def trade_candidates(
    candidates: list[dict[str, Any]], prepared: dict[str, PreparedExits], costs: dict[str, float]
) -> list[dict[str, Any]]:
    """Keep one position per asset; even an exit at the entry open blocks that open."""
    indices = {a: {b.ts: i for i, b in enumerate(p.bars)} for a, p in prepared.items()}
    occupied: dict[str, int] = {}
    rows = []
    accepted = [r for r in candidates if r["status"] == "accepted" and r["cluster_first"]]
    for candidate in sorted(
        accepted, key=lambda r: (r["entry_ts"], r["symbol"], r["candidate_id"])
    ):
        asset = candidate["symbol"]
        start = indices[asset][candidate["entry_ts"]]
        if candidate["entry_price"] != prepared[asset].bars[start].open:
            raise ValueError(f"{asset}: recorded entry does not match its bar open")
        if start <= occupied.get(asset, -1):
            row = dict(
                entry_index=start,
                entry_ts=candidate["entry_ts"],
                entry_price=candidate["entry_price"],
                stop=None,
                target=None,
                exit_index=None,
                exit_ts=None,
                exit_price=None,
                reason="skipped-in-trade",
                bars_held=0,
                gross_return=None,
                net_return=None,
                r_multiple=None,
                worst_adverse_move=None,
                both_touched=0,
                complete=False,
            )
        else:
            row = simulate(prepared[asset], start, costs[asset])
            if row["exit_index"] is not None:
                occupied[asset] = row["exit_index"]
        rows.append(
            dict(
                asset=asset,
                candidate_id=candidate["candidate_id"],
                cluster_id=candidate["cluster_id"],
                **row,
            )
        )
    return rows


def trades_frame(rows: list[dict[str, Any]]) -> Any:
    import polars as pl

    schema: dict[str, Any] = dict(
        asset=pl.String,
        candidate_id=pl.Int64,
        cluster_id=pl.Int64,
        entry_index=pl.Int64,
        entry_ts=pl.Datetime("us", "UTC"),
        entry_price=pl.Float64,
        stop=pl.Float64,
        target=pl.Float64,
        exit_index=pl.Int64,
        exit_ts=pl.Datetime("us", "UTC"),
        exit_price=pl.Float64,
        reason=pl.String,
        bars_held=pl.Int64,
        gross_return=pl.Float64,
        net_return=pl.Float64,
        r_multiple=pl.Float64,
        worst_adverse_move=pl.Float64,
        both_touched=pl.Int64,
        complete=pl.Boolean,
    )
    return pl.DataFrame(rows, schema=schema)
