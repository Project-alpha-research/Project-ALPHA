"""Candidate inspection only: decide at a close, enter at the next bar's open."""

from __future__ import annotations

from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_study.setup.expr import compile_expr
from alpha_study.setup.spec import SetupSpec

PENDING = "pending-trigger"


def _status(reason: str | None) -> str:
    if reason is None:
        return "accepted"
    return "pending" if reason == PENDING else "rejected"


def _validate(bars: pl.DataFrame) -> None:
    required = {"ts", "open", "high", "low", "close", "volume"}
    if missing := required - set(bars.columns):
        raise DataError(f"bars missing required columns: {sorted(missing)}")
    ts = bars["ts"]
    if not isinstance(ts.dtype, pl.Datetime) or ts.dtype.time_zone != "UTC":
        raise DataError("bars.ts must be timezone-aware UTC datetime")
    if ts.null_count() or not ts.is_sorted() or ts.n_unique() != len(ts):
        raise DataError("bars.ts must be non-null, strictly increasing and unique")
    for name in ("open", "high", "low", "close", "volume"):
        column = bars[name]
        if not column.dtype.is_numeric():
            raise DataError(f"bars.{name} must be numeric")
        if name != "volume" and column.null_count():
            raise DataError(f"bars.{name} must not contain nulls")
        if not column.drop_nulls().is_finite().all():
            raise DataError(f"bars.{name} must be finite")


def _decision(
    i: int,
    spec: SetupSpec,
    values: dict[str, list[Any]],
    length: int,
) -> tuple[str | None, str | None, int | None]:
    for name in spec.filters:
        value = values[f"filter:{name}"][i]
        if value is None:
            return "warm-up", f"{name}: null", None
        if not value:
            return name, f"{name}: false", None
    for name in spec.reference:
        if values[f"ref:{name}"][i] is None:
            return "warm-up", f"{name}: null", None
    trigger = i
    if spec.trigger is not None:
        # A null trigger value (a missing volume, say) is false; the static warm-up
        # already excludes bars where the trigger cannot be computed yet.
        found = next(
            (
                j
                for j in range(i, min(length, i + spec.trigger.within + 1))
                if values["trigger"][j] is True
            ),
            None,
        )
        if found is None:
            if i + spec.trigger.within >= length:
                # The window runs past the last supplied bar: it could still trigger.
                return PENDING, "trigger: window not finished", None
            return "no-trigger", "trigger: false within window", None
        trigger = found
    if trigger + 1 >= length:
        return "no-next-bar", "entry: no next bar", trigger
    return None, None, trigger


def find_candidates(spec: SetupSpec, bars: pl.DataFrame, *, symbol: str) -> pl.DataFrame:
    """Return event rows after static warm-up, with ordered reasons and next-open fills.

    A trigger window that runs past the last supplied bar without a trigger is not a
    rejection: status `pending`, reason `pending-trigger`. `no-trigger` is reported
    only once the whole window has been seen. A trigger at the final bar is
    `no-next-bar`: its next-open entry does not exist yet.
    """
    _validate(bars)
    if symbol not in spec.setup.assets:
        raise DataError(f"symbol {symbol!r} is not in setup.assets")
    expressions = {"event": compile_expr(spec.setup.event)}
    expressions.update(
        {f"filter:{name}": compile_expr(text) for name, text in spec.filters.items()}
    )
    expressions.update({f"ref:{name}": compile_expr(text) for name, text in spec.reference.items()})
    if spec.trigger is not None:
        expressions["trigger"] = compile_expr(spec.trigger.when)
    warmup = max(value.warmup for value in expressions.values())
    evaluated = bars.with_columns(value.expr.alias(name) for name, value in expressions.items())
    values = {name: evaluated[name].to_list() for name in expressions}
    timestamps, opens = bars["ts"].to_list(), bars["open"].to_list()
    schema: dict[str, pl.DataType] = {
        "candidate_id": pl.Int64(),
        "symbol": pl.String(),
        "event_ts": bars.schema["ts"],
        "status": pl.String(),
        "reason": pl.String(),
        "detail": pl.String(),
        "trigger_ts": bars.schema["ts"],
        "entry_ts": bars.schema["ts"],
        "entry_price": pl.Float64(),
        **{f"ref_{name}": pl.Float64() for name in spec.reference},
    }
    rows: list[dict[str, Any]] = []
    for i in range(warmup, bars.height):
        if values["event"][i] is not True:
            continue
        reason, detail, trigger = _decision(i, spec, values, bars.height)
        entry = trigger + 1 if trigger is not None and trigger + 1 < bars.height else None
        rows.append(
            {
                "candidate_id": len(rows) + 1,
                "symbol": symbol,
                "event_ts": timestamps[i],
                "status": _status(reason),
                "reason": reason,
                "detail": detail,
                "trigger_ts": timestamps[trigger] if trigger is not None else None,
                "entry_ts": timestamps[entry] if entry is not None else None,
                "entry_price": opens[entry] if entry is not None else None,
                **{f"ref_{name}": values[f"ref:{name}"][i] for name in spec.reference},
            }
        )
    return pl.DataFrame(rows, schema=schema)


def summarise(candidates: pl.DataFrame) -> dict[str, Any]:
    """Count acceptance and rejection reasons, retaining the event extent."""
    rejected: dict[str, int] = {}
    accepted = pending = 0
    for row in candidates.iter_rows(named=True):
        if row["status"] == "accepted":
            accepted += 1
        elif row["status"] == "pending":
            pending += 1
        else:
            reason = row["reason"]
            rejected[reason] = rejected.get(reason, 0) + 1
    return {
        "accepted": accepted,
        "pending": pending,
        "rejected": rejected,
        "first_event": candidates["event_ts"][0] if candidates.height else None,
        "last_event": candidates["event_ts"][-1] if candidates.height else None,
    }
