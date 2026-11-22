"""The one re-run path of the parameter-robustness checks, and the tries it counts.

A check names its variants (another setting, a delayed entry, a later start, noisy prices). This
module counts each as a try in the one trial ledger, before any engine run, then runs them through
the diagnostic pass's own engine path (``price_noise.engine_runs``, ``diagnose.full_sample``'s
``run_full_backtest``) and scores each run's full-sample equity like the stored sensitivity rows.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from time import monotonic
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result, Value
from alpha_cli.toolbox.families.parameter_robustness_signals import SignalChange

if TYPE_CHECKING:
    from alpha_cli import _runner
    from alpha_cli.toolbox.inputs import RunSeries
    from alpha_core import Bar

TESTS = "tests/unit/test_toolbox_parameter_robustness.py::"
POISON = TESTS + "test_future_bars_do_not_enter_a_rerun"
# Fewer closed trades than this over the whole history leaves nothing to compare.
MIN_TRADES = 10
# Seconds between progress lines while engine runs go on.
PROGRESS_EVERY = 10.0
# A rough engine speed on daily bars, for the advance estimate only.
SECONDS_PER_BAR = 0.0002
# Engine runs use a spawn pool only when they would take longer than this one at a time.
POOL_FROM_SECONDS = 20.0
BASIS = "Full-sample engine re-runs on the run's own bars, before the held-back period."
TRIES = Output(
    "tries_added",
    "Tries added",
    "Engine re-runs this check added to the trial ledger; a repeat of the same re-run adds none.",
    "count",
)
TRY_SENTENCE = (
    " It made {engine_runs:.0f} engine runs. Making this reading added {tries_added:.0f} new "
    "tries to the count; shown again, it adds none."
)
# A control re-runs the same rule and settings on changed data or execution: not a try.
CONTROL_SENTENCE = (
    " It made {engine_runs:.0f} engine runs. These are controls of the same rule, not new tries."
)


def not_a_pick(example: str) -> str:
    """The caveat of a control: it measures fragility; it never picks a better variant."""
    return (
        f"A control is not a way to pick a better variant: if you now want to {example}, that "
        "is a new rule: test it as one."
    )


RUNS = Output("engine_runs", "Engine runs", "Engine re-runs this check made.", "count")


@dataclass(frozen=True)
class Variant:
    """One engine re-run: a run spec, the first bar it starts on, and an optional change."""

    label: str
    spec: _runner.RunSpec
    start: int = 0
    change: SignalChange | None = None
    # Noisy prices: the copy's bars and the key that names them.
    bars: tuple[Bar, ...] | None = None
    data_key: str | None = None
    identity: dict[str, Any] = field(default_factory=dict)


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def too_little(run: RunSeries) -> str | None:
    """The reason a run is too small to re-read, or None."""
    trades = len(run.full.trades) if run.full is not None else 0
    if trades < MIN_TRADES:
        return (
            f"Too little to read: the rule closed {trades} trades over the whole history; "
            f"at least {MIN_TRADES} are needed to compare re-runs."
        )
    return None


def _bars(run: RunSeries, variant: Variant) -> list[Bar]:
    return list(variant.bars if variant.bars is not None else run.bars[variant.start :])


def try_row(run: RunSeries, tool: str, variant: Variant) -> dict[str, Any]:
    """The ledger row of one re-run: a screen-style try keyed by what was run, on which data."""
    if run.idea is None:
        raise ValueError("A re-run needs the run's idea spec")
    bars = _bars(run, variant)
    identity = {
        "idea": run.idea.spec_sha256,
        "spec": asdict(variant.spec),
        "change": None
        if variant.change is None
        else {"kind": type(variant.change).__name__, **asdict(variant.change)},
        **variant.identity,
    }
    data_id = run.manifest.get("idea_id")
    return {
        "kind": "screen_trial",
        "name": f"{tool}:{variant.label}",
        "spec_sha256": _digest(identity),
        "symbol": run.manifest["metadata"]["symbol"],
        "first_ts": bars[0].ts.isoformat(),
        "last_ts": bars[-1].ts.isoformat(),
        "bar_size": "1D" if run.ppy in (252, 365) else None,
        "store": run.manifest["spine"].get("store"),
        "idea_id": data_id if variant.data_key is None else _digest([data_id, variant.data_key]),
        "tool": tool,
        "of_run": run.run_id,
        "labels": [],
    }


def count_tries(run: RunSeries, tool: str, variants: list[Variant]) -> int:
    """Append each re-run not yet in the ledger as one try, through the ledger writer.

    A re-run already counted (the same settings on the same data, from this check or another)
    adds nothing. Returns how many tries were added.
    """
    from alpha_cli.spine.ledger import append_trial, read_trials
    from alpha_cli.spine.trial_record import row_test_key

    counted = {row_test_key(row) for row in read_trials(run.home) if row["kind"] == "screen_trial"}
    added = 0
    for variant in variants:
        row = try_row(run, tool, variant)
        if row_test_key(row) in counted:
            continue
        counted.add(row_test_key(row))
        added += "repeat" not in append_trial(run.home, row)["labels"]
    return added


def workers(seconds: float) -> int:
    if seconds < POOL_FROM_SECONDS:
        return 1
    return max(1, min(4, (os.cpu_count() or 1) - 1))


@contextmanager
def progress(runs: int, seconds: float) -> Iterator[None]:
    """Say in advance how many engine runs and about how long; then a line every 10 seconds."""
    print(
        f"This check makes {runs} engine runs; about {max(1, round(seconds))} seconds.",
        file=sys.stderr,
        flush=True,
    )
    started, done = monotonic(), threading.Event()

    def beat() -> None:
        while not done.wait(PROGRESS_EVERY):
            print(
                f"Still running: {monotonic() - started:.0f} seconds so far, {runs} engine runs.",
                file=sys.stderr,
                flush=True,
            )

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join()
        print(
            f"Done: {runs} engine runs in {monotonic() - started:.0f} seconds.",
            file=sys.stderr,
            flush=True,
        )


def engine(tasks: list[Any], pool: int) -> list[tuple[Any, int]]:
    """The diagnostic pass's engine runs (a module name tests may replace)."""
    from alpha_cli.spine.price_noise import engine_runs

    return engine_runs(tasks, pool)


def rerun(
    run: RunSeries,
    tool: str,
    variants: list[Variant],
    execute: Callable[[Variant], tuple[Any, int]] | None = None,
    *,
    control: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """Run the variants and score each; return the rows and the new tries.

    Other settings of the rule are tries, counted before any run. A ``control`` (the same rule on
    changed data or execution) writes no ledger row and adds no try.
    """
    from alpha_cli.spine.diagnostics import performance

    added = 0 if control else count_tries(run, tool, variants)
    seconds = sum(len(_bars(run, v)) for v in variants) * SECONDS_PER_BAR
    with progress(len(variants), seconds):
        if execute is not None:
            outcomes = [execute(variant) for variant in variants]
        else:
            tasks = [(_bars(run, v), v.spec, list(run.dividends), v.change) for v in variants]
            outcomes = engine(tasks, workers(seconds))
    rows = []
    for variant, (equity, trades) in zip(variants, outcomes, strict=True):
        scored = performance(equity, run.ppy, BASIS)
        rows.append(
            {
                "name": variant.label,
                "sharpe": scored["sharpe"],
                "total_return": scored["total_return"],
                "max_drawdown": scored["max_drawdown"],
                "trades": trades,
                "reasons": scored["reasons"],
            }
        )
    return rows, added


def original(run: RunSeries) -> dict[str, Any]:
    """The rule as tested, scored the same way as each re-run."""
    from alpha_cli.spine.diagnostics import performance

    scored = performance(run.equity, run.ppy, BASIS)
    trades = len(run.full.trades) if run.full is not None else 0
    return {"name": "as tested", **scored, "trades": trades}


def unavailable(keys: list[str], reason: str, **known: Value) -> Result:
    """Every value unavailable for one reason; nothing is run and no try is added."""
    values: dict[str, Value] = dict.fromkeys(keys)
    values.update(known)
    reasons = {key: reason for key, value in values.items() if value is None}
    return Result(values, reasons, basis=BASIS)


def fill(
    values: dict[str, Value], reasons: dict[str, str], key: str, row: dict[str, Any], metric: str
) -> None:
    """Set one value from a row; a missing value keeps the row's reason."""
    values[key] = row.get(metric)
    if values[key] is None:
        reasons[key] = row.get("reasons", {}).get(metric) or row.get("reason") or "not defined"


def inputs_of(run: RunSeries) -> tuple[Any, _runner.RunSpec]:
    """The idea spec and run spec a re-run needs (``load_rerun`` gives both)."""
    if run.idea is None or run.spec is None or run.full is None:
        raise ValueError("This check needs the run's idea spec and run spec (a re-run input)")
    return run.idea, run.spec
