"""N0 (opt-in): pull stored bars for the assets of followed ideas, and only those.

Each pull is the installed `alpha data pull ... --json` command in a child process, with the
arguments the owner would type. The pull itself freezes the stored series as a snapshot before it
replaces anything, reuses an identical snapshot, and reports what changed (counts and dates, never
a price). This module reads that JSON. A failed freeze (exit code 3) means nothing was replaced:
a blocking defect for that asset. New bars are `computed`, none are `reused`, and a revised or
dropped old bar is a minor defect that names the snapshot. This module does no network and reads no
key: the child uses the environment of the nightly process, exactly as when the owner runs it.
A pull replaces the symbol's whole series, so it starts at the first stored bar and the provider's
whole history comes again. The request ends at the newest CLOSED day: a provider with an inclusive
end gets the day before the run's UTC date, so a forming bar is never asked for. A failed pull is
a minor defect, never a blocking one: the follow update then records `late` or `missed` honestly.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from alpha_cli.nightly_config import NightlyConfig
from alpha_cli.nightly_steps import (
    BLOCKING,
    COMPUTED,
    MINOR,
    REUSED,
    Outcome,
    Runner,
    alpha_argv,
    mark,
    new_step,
    not_run,
    stderr_tail,
)
from alpha_cli.spine.stores import resolve_asset
from alpha_core import DataError

SECRET = re.compile(r"(?i)(\w*(?:key|token|secret|password)\w*[\"']?\s*[=:]\s*[\"']?)[^\s\"',&]+")
AUTH = re.compile(
    r"(?i)((?:\bauthorization[\"']?\s*[=:]\s*[\"']?|\bbearer\s+|\bbasic\s+))(?:(?:bearer|token|basic)\s+)?[^\s\"',&]+"
)
INCLUSIVE_END = {"stooq", "tiingo", "alpaca"}
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
    if source in INCLUSIVE_END:
        end -= timedelta(days=1)  # an inclusive end must not reach the day still forming
    return [*tail, "--start", first.isoformat(), "--end", end.isoformat()]


def _bars(home: Path, asset: str) -> pl.DataFrame | None:
    """The stored bars, read-only. None when they cannot be read."""
    try:
        found = resolve_asset(asset, data_dir=home)
        return found.daily_store().read_bars(found.symbol)
    except (DataError, OSError, KeyError, TypeError):
        return None


def _span(frame: pl.DataFrame | None) -> tuple[datetime, datetime] | None:
    if frame is None or "ts" not in frame.columns or not frame.height:
        return None
    low, high = frame["ts"].min(), frame["ts"].max()
    return (low, high) if isinstance(low, datetime) and isinstance(high, datetime) else None


def _scrub(text: str) -> str:
    return SECRET.sub(r"\1[removed]", AUTH.sub(r"\1[removed]", text))


def _plan(home: Path, asset: str, end: date) -> tuple[list[str], Path | None]:
    found = resolve_asset(asset, data_dir=home)
    span = _span(_bars(home, asset))
    if span is None:
        raise ValueError("its stored bars cannot be read")
    provenance = found.daily_store().read_provenance(found.symbol) or {"source": found.source}
    return pull_tail(found.symbol, provenance, span[0].date(), end), (
        None if found.store_name == "home" else found.data_dir
    )


def _child(
    runner: Runner, step: dict[str, Any], tail: Sequence[str], other: Path | None, timeout: float
) -> Outcome:
    """Run one child command (in a named store when `other` is set) and fill the step's command,
    exit code and seconds."""
    argv = alpha_argv(tail)
    step["command"] = "alpha " + shlex.join(tail)
    if other is not None:
        argv = ["env", f"ALPHA_DATA_DIR={other}", *argv]
        step["command"] = f"ALPHA_DATA_DIR={shlex.quote(str(other))} {step['command']}"
    out = runner(argv, timeout)
    step["exit_code"], step["seconds"] = out.exit_code, round(out.seconds, 2)
    return out


def _failure(out: Outcome, timeout: float) -> str | None:
    """Plain words for a failed child command, scrubbed; None when it succeeded."""
    if out.timed_out:
        return f"timed out after {timeout:g} seconds"
    if out.exit_code != 0:
        return f"exit code {out.exit_code}. {_scrub(stderr_tail(out.stderr))}".rstrip()
    return None


FREEZE_FAILED = 3  # `alpha data pull` exit code: the stored series could not be frozen


def _revision_words(asset: str, report: dict[str, Any], other: Path | None) -> str | None:
    """Plain words when the provider changed or dropped earlier bars; None when it did not."""
    revised, dropped = report["bars_revised"], report["bars_removed"]["count"]
    if not revised["count"] and not dropped:
        return None
    snap = (report.get("snapshot") or {}).get("id")
    listing = "alpha data snapshots"
    if other is not None:
        listing = f"ALPHA_DATA_DIR={shlex.quote(str(other))} {listing}"
    head = f"the provider revised history for {asset}"
    if revised["count"]:
        head += f": first changed bar {revised['first_date']} ({', '.join(revised['columns'])})"
    if dropped:
        head += f"{';' if revised['count'] else ':'} {dropped} earlier bars are gone"
    return f"{head}. The earlier series is kept in snapshot {snap}; list it with `{listing}`"


def _read_report(out: Outcome) -> dict[str, Any] | None:
    try:
        report = json.loads(out.stdout)
    except ValueError:
        return None
    needed = ("bars_added", "bars_removed", "bars_revised")
    return report if isinstance(report, dict) and all(k in report for k in needed) else None


def refresh_assets(
    config: NightlyConfig,
    home: Path,
    runner: Runner,
    assets: Sequence[str],
    end: date,
) -> list[dict[str, Any]]:
    """One pull per asset. `assets` holds the assets of followed ideas only."""
    if not assets:
        return [
            not_run(
                "N0.stub", "N0", "refresh bars", ["data", "pull"], "not run: nothing is followed"
            )
        ]
    steps: list[dict[str, Any]] = []
    for asset in assets:
        step = new_step(f"N0.pull.{asset}", "N0", f"refresh bars {asset}", ["data", "pull", asset])
        steps.append(step)
        try:
            tail, other = _plan(home, asset, end)
        except (ValueError, DataError) as exc:
            mark(step, MINOR, f"no fresh bars for {asset}: {exc}")
            continue
        out = _child(runner, step, [*tail, "--json"], other, config.step_timeout)
        failed = _failure(out, config.step_timeout)
        if failed is not None and out.exit_code == FREEZE_FAILED and not out.timed_out:
            mark(step, BLOCKING, f"could not freeze {asset} before the refresh: {failed}")
            continue
        if failed is not None:
            mark(step, MINOR, f"no fresh bars for {asset}: {failed}")
            continue
        report = _read_report(out)
        if report is None:
            mark(step, MINOR, f"the refresh of {asset} ran, but its result could not be read")
            continue
        if report.get("snapshot"):
            step["ids"] = {"snapshot": report["snapshot"]["id"]}
        grew = report["bars_added"]["count"] > 0
        step["evidence"] = COMPUTED if grew else REUSED
        step["note"] = None if grew else "no new bar"
        words = _revision_words(asset, report, other)
        if words is not None:
            mark(step, MINOR, words)
    return steps
