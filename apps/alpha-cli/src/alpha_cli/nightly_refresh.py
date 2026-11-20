"""N0 (opt-in): freeze, then pull, stored bars for the assets of followed ideas, and only those.

Before each pull the asset's stored bars and corporate actions are frozen by the installed
`alpha data snapshot` command (a child process). If that fails, the pull for that asset is not run:
a blocking defect, so nothing is replaced without a frozen copy. The snapshot id is in the record.
Each pull is the installed `alpha data pull` command in a child process, with the arguments the
owner would type. This module does no network and reads no key: the child uses the environment of
the nightly process, exactly as when the owner runs it. A pull replaces the symbol's whole series,
so it starts at the first stored bar and the provider's whole history comes again. Before the pull
the old bars are held in memory; after it each old bar is compared, and a changed or missing old
bar is a minor defect that names the first changed date (never a price). The request ends at the
newest CLOSED day: a provider with an inclusive end gets the day before the run's UTC date, so a
forming bar is never asked for. A failed pull is a minor defect, never a blocking one: the follow
update then records `late` or `missed` honestly.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from alpha_cli.nightly_config import NightlyConfig
from alpha_cli.nightly_steps import (
    BLOCKING,
    COMPUTED,
    MINOR,
    NOT_RUN,
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


def first_revised(old: pl.DataFrame, new: pl.DataFrame) -> tuple[date, list[str]] | None:
    """The first day whose old bar is missing or different after the pull, with the names of the
    columns that differ on that day (`missing` when the bar is gone). None when nothing changed."""
    cols = [c for c in old.columns if c in new.columns]
    if "ts" not in cols:
        return None
    fresh = {row[0]: row for row in new.select(cols).iter_rows()}
    for row in old.select(cols).sort("ts").iter_rows():
        found = fresh.get(row[0])
        if found != row and isinstance(row[0], datetime):
            names = (
                ["missing"]
                if found is None
                else [c for c, a, b in zip(cols, row, found, strict=True) if a != b]
            )
            return row[0].date(), names
    return None


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


def snapshot_tail(asset: str, pull: Sequence[str], stamp: datetime) -> tuple[str, list[str]]:
    """The snapshot id and the `alpha data snapshot` arguments for the asset a pull is about to
    replace. The id holds the run's UTC time, so a second run on the same day never collides.
    The source options are those of the pull, because the command checks the stored provenance."""
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", pull[2]).strip("-") or "asset"
    snap_id = f"n0-{stamp:%Y%m%dT%H%M%S}-{name}"
    options = list(pull[3:-4])
    kept: list[str] = []
    for index, word in enumerate(options):
        if word in {"--source", "--exchange"} and index + 1 < len(options):
            kept += [word, options[index + 1]]
    return snap_id, ["data", "snapshot", snap_id, pull[2], *kept]


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


def _freeze(
    config: NightlyConfig,
    runner: Runner,
    asset: str,
    tail: list[str],
    other: Path | None,
    stamp: datetime,
) -> tuple[dict[str, Any], str | None]:
    """Freeze the asset's stored bars and actions. Returns the step and the snapshot id, or None
    for the id when the freeze failed (a blocking defect: nothing may be replaced unfrozen)."""
    snap_id, snap = snapshot_tail(asset, tail, stamp)
    step = new_step(f"N0.freeze.{asset}", "N0", f"freeze bars {asset}", snap)
    step["ids"] = {"snapshot": snap_id}
    failed = _failure(_child(runner, step, snap, other, config.step_timeout), config.step_timeout)
    if failed is None:
        return step, snap_id
    mark(step, BLOCKING, f"could not freeze {asset} before the refresh: {failed}")
    return step, None


def _revision_words(
    asset: str, changed: tuple[date, list[str]], snap_id: str, other: Path | None
) -> str:
    listing = "alpha data snapshots"
    if other is not None:
        listing = f"ALPHA_DATA_DIR={shlex.quote(str(other))} {listing}"
    return (
        f"the provider revised history for {asset}: first changed bar {changed[0]} "
        f"({', '.join(changed[1])}). The earlier series is kept in snapshot {snap_id}; "
        f"list it with `{listing}`"
    )


def refresh_assets(
    config: NightlyConfig,
    home: Path,
    runner: Runner,
    assets: Sequence[str],
    end: date,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """One freeze, then one pull, per asset. `assets` holds the assets of followed ideas only."""
    if not assets:
        return [
            not_run(
                "N0.stub", "N0", "refresh bars", ["data", "pull"], "not run: nothing is followed"
            )
        ]
    stamp = now or datetime.now(UTC)
    steps: list[dict[str, Any]] = []
    for asset in assets:
        step = new_step(f"N0.pull.{asset}", "N0", f"refresh bars {asset}", ["data", "pull", asset])
        try:
            tail, other = _plan(home, asset, end)
        except (ValueError, DataError) as exc:
            steps.append(step)
            mark(step, MINOR, f"no fresh bars for {asset}: {exc}")
            continue
        frozen, snap_id = _freeze(config, runner, asset, tail, other, stamp)
        steps += [frozen, step]
        if snap_id is None:
            step["state"], step["note"] = NOT_RUN, f"not run: {asset} could not be frozen first"
            continue
        step["ids"] = {"snapshot": snap_id}
        old = _bars(home, asset)
        before = _span(old)
        out = _child(runner, step, tail, other, config.step_timeout)
        failed = _failure(out, config.step_timeout)
        if failed is not None:
            mark(step, MINOR, f"no fresh bars for {asset}: {failed}")
            continue
        fresh = _bars(home, asset)
        after = _span(fresh)
        if before and after:
            step["evidence"] = COMPUTED if after[1] > before[1] else REUSED
            step["note"] = None if after[1] > before[1] else "no new bar"
        changed = first_revised(old, fresh) if old is not None and fresh is not None else None
        if changed is not None:
            mark(step, MINOR, _revision_words(asset, changed, snap_id, other))
    return steps
