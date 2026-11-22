"""Shared pieces of the time-series checks: one way to build a spec and to say "too little"."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec, Value
from alpha_cli.toolbox.situations import Situation

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

TESTS = "tests/unit/test_toolbox_timeseries.py::"
BASIS = "After-cost bar returns from the stored walk-forward equity curve."
Compute = Callable[["Inputs", dict[str, Any], "Generator | None"], Result]


def make(
    name: str,
    question: str,
    params: tuple[Param, ...],
    outputs: tuple[Output, ...],
    reading: str,
    caveat: str,
    compute: Compute,
    reference: str,
    *,
    situations: tuple[Situation, ...],
    test: bool = False,
    seeded: bool = False,
) -> ToolSpec:
    """One time-series check on the stored equity curve; ``test`` marks a significance reading."""
    return ToolSpec(
        id=f"timeseries.{name}",
        answers=(question,),
        situations=situations,
        family="timeseries",
        kind="test" if test else "diagnostic",
        look="test" if test else "describe",
        question=question,
        needs=("stored_equity",),
        params=params,
        outputs=outputs,
        reading=reading,
        caveats=(caveat,),
        seeded=seeded,
        time_safety="hindsight",
        poison_test=TESTS + "test_future_input_rejected",
        reference=TESTS + reference,
        compute=compute,
    )


def unavailable(keys: tuple[str, ...], reason: str, count: int) -> Result:
    return Result(
        dict.fromkeys(keys), dict.fromkeys(keys, reason), details={"n_returns": count}, basis=BASIS
    )


def too_little(keys: tuple[str, ...], needed: int, count: int) -> Result:
    return unavailable(
        keys, f"Needs at least {needed} scored bar returns; this run has {count}.", count
    )


def finished(values: dict[str, Any], reason: str) -> Result:
    """Keep finite numbers; every other entry is unavailable and carries ``reason``."""
    import math

    clean: dict[str, Value] = {
        key: (float(v) if isinstance(v, int | float) and math.isfinite(v) else None)
        for key, v in values.items()
    }
    reasons = {key: reason for key, v in clean.items() if v is None}
    return Result(clean, reasons, basis=BASIS)


def flat(returns: Any) -> bool:
    return bool(returns.max() == returns.min())
