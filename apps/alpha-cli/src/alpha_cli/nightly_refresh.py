"""N0 (opt-in): pull fresh stored bars for the assets of followed ideas, and only those.

Each pull is the installed `alpha data pull` command in a child process, with the arguments the
owner would type. This module does no network and reads no key: the child uses the environment of
the nightly process, exactly as when the owner runs it. A pull replaces the symbol's whole series,
so it starts at the first stored bar. A failed pull is a minor defect, never a blocking one: the
follow update then records `late` or `missed` honestly.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from alpha_cli.nightly_config import NightlyConfig
from alpha_cli.nightly_steps import (
    COMPUTED,
    MINOR,
    REUSED,
    Runner,
    alpha_argv,
    mark,
    new_step,
    not_run,
    stderr_tail,
)
from alpha_cli.spine.stores import resolve_asset
from alpha_core import DataError

SECRET = re.compile(r"(?i)(\w*(?:key|token|secret|password)\w*\s*[=:]\s*)\S+")
PROVIDER_ARGS = (
    ("asset_class", "--asset-class"),
    ("venue", "--venue"),
    ("calendar", "--calendar"),
    ("currency", "--currency"),
)


def pull_tail(symbol: str, provenance: dict[str, Any], first: date, end: date) -> list[str]:
    """`alpha data pull` arguments for one stored symbol, from its provenance. Raises ValueError
    when the source has no pull form."""
    dataset = provenance.get("dataset")
    dataset = dataset if isinstance(dataset, dict) else {}
    source = str(dataset.get("provider") or provenance.get("source") or "")
    tail = ["data", "pull", symbol]
    if source.startswith("ccxt:"):
        tail += ["--source", "ccxt", "--exchange", source.removeprefix("ccxt:")]
    elif source in {"yfinance", "stooq"}:
        tail += ["--source", source]
    elif source in {"tiingo", "alpaca"}:
        tail += ["--source", source]
        for key, flag in PROVIDER_ARGS:
            if dataset.get(key):
                tail += [flag, str(dataset[key])]
    else:
        raise ValueError(f"the source {source!r} has no pull command")
    return [*tail, "--start", first.isoformat(), "--end", end.isoformat()]


def _span(home: Path, asset: str) -> tuple[datetime, datetime] | None:
    try:
        found = resolve_asset(asset, data_dir=home)
        ts = found.daily_store().read_bars(found.symbol)["ts"]
        low, high = ts.min(), ts.max()
    except (DataError, OSError, KeyError, TypeError):
        return None
    return (low, high) if isinstance(low, datetime) and isinstance(high, datetime) else None


def _scrub(text: str) -> str:
    return SECRET.sub(r"\1[removed]", text)


def _plan(home: Path, asset: str, end: date) -> tuple[list[str], Path | None]:
    found = resolve_asset(asset, data_dir=home)
    span = _span(home, asset)
    if span is None:
        raise ValueError("its stored bars cannot be read")
    provenance = found.daily_store().read_provenance(found.symbol) or {"source": found.source}
    return pull_tail(found.symbol, provenance, span[0].date(), end), (
        None if found.store_name == "home" else found.data_dir
    )


def refresh_assets(
    config: NightlyConfig, home: Path, runner: Runner, assets: Sequence[str], end: date
) -> list[dict[str, Any]]:
    """One pull per asset. `assets` holds the assets of followed ideas only."""
    if not assets:
        return [
            not_run(
                "N0.stub", "N0", "refresh bars", ["data", "pull"], "not run: nothing is followed"
            )
        ]
    steps = []
    for asset in assets:
        step = new_step(f"N0.pull.{asset}", "N0", f"refresh bars {asset}", ["data", "pull", asset])
        steps.append(step)
        try:
            tail, other = _plan(home, asset, end)
        except (ValueError, DataError) as exc:
            mark(step, MINOR, f"no fresh bars for {asset}: {exc}")
            continue
        argv = alpha_argv(tail)
        step["command"] = "alpha " + shlex.join(tail)
        if other is not None:
            argv = ["env", f"ALPHA_DATA_DIR={other}", *argv]
            step["command"] = f"ALPHA_DATA_DIR={shlex.quote(str(other))} {step['command']}"
        before = _span(home, asset)
        out = runner(argv, config.step_timeout)
        step["exit_code"], step["seconds"] = out.exit_code, round(out.seconds, 2)
        if out.timed_out:
            mark(
                step,
                MINOR,
                f"no fresh bars for {asset}: timed out after {config.step_timeout:g} seconds",
            )
        elif out.exit_code != 0:
            words = _scrub(stderr_tail(out.stderr))
            mark(
                step,
                MINOR,
                f"no fresh bars for {asset}: exit code {out.exit_code}. {words}".rstrip(),
            )
        else:
            after = _span(home, asset)
            if before and after:
                step["evidence"] = COMPUTED if after[1] > before[1] else REUSED
                step["note"] = None if after[1] > before[1] else "no new bar"
    return steps
