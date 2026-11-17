"""Inputs of the investigation tools: a recorded rule test's returns and a market to compare.

The strategy's returns come from the diagnostic pass's own full-sample path
(``diagnose.full_sample``) on the bars the run used; a run whose stored history no longer
reproduces it fails loud instead of describing a different history.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from alpha_cli import _runner
from alpha_cli.run_store import find_run_dir, read_manifest
from alpha_cli.spine.diagnose import full_sample
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.facts import read_json
from alpha_cli.spine.run import assemble_run_spec
from alpha_cli.spine.spec import IdeaSpec
from alpha_cli.spine.stores import periods_per_year, resolve_asset
from alpha_validation.attribution import MIN_BARS
from alpha_validation.metrics import to_returns


@dataclass(frozen=True)
class RunSeries:
    """A rule-test run's identity and its full-sample equity on the bars the run used."""

    home: Path
    run_id: str
    manifest: dict[str, Any]
    asset: str
    ppy: int
    dates: tuple[datetime, ...]
    equity: tuple[float, ...]
    # The engine samples equity at each bar's open, so a fair market return is open-to-open.
    opens: dict[datetime, float]


def load_run(home: Path, run_id: str) -> RunSeries:
    rdir = find_run_dir(home, run_id)
    if rdir is None:
        raise SpineError(
            "UNKNOWN_RUN",
            f"Unknown completed run {run_id!r}.",
            "Run alpha results --json to list recorded runs.",
        )
    manifest = read_manifest(rdir)
    stored = read_json(rdir / "spec.json")
    if not isinstance(manifest.get("spine"), dict) or not stored:
        raise SpineError(
            "NOT_A_RULE_TEST",
            f"Run {run_id} was not made by alpha test, so the tools cannot rebuild its returns.",
            "Run alpha results --json to list rule-test runs.",
        )
    meta = manifest["metadata"]
    resolved = resolve_asset(f"{meta['symbol']}@{manifest['spine']['store']}", data_dir=home)
    last = datetime.fromisoformat(meta["last_ts"])
    # Bars added after the run are left out, so the tool describes the run's own history.
    bars = [
        bar
        for bar in _runner.load_bars(resolved.symbol, data_dir=resolved.data_dir)[0]
        if bar.ts <= last
    ]
    dividends = _runner.load_dividends(resolved.symbol, data_dir=resolved.data_dir)
    changed = SpineError(
        "RUN_DATA_CHANGED",
        f"The stored history of {resolved.symbol} no longer reproduces run {run_id}.",
        "Run alpha test again from the saved spec, then run alpha tool on the new run.",
    )
    if _runner.source_fingerprint(bars, dividends=dividends) != manifest.get("source_fingerprint"):
        raise changed
    idea = IdeaSpec.model_validate({k: v for k, v in stored.items() if k != "spec_sha256"})
    ppy = periods_per_year([bar.ts for bar in bars])
    spec = assemble_run_spec(idea, resolved.symbol, ppy, len(bars))
    _, dates, equity = full_sample(bars, dividends, spec)
    expected = read_json(rdir / "diagnostics.json").get("full_sample", {}).get("total_return")
    if expected is not None and not math.isclose(
        equity[-1] / equity[0] - 1, expected, rel_tol=1e-9, abs_tol=1e-12
    ):
        raise changed
    return RunSeries(
        home=home,
        run_id=run_id,
        manifest=manifest,
        asset=f"{resolved.symbol}@{resolved.store_name}",
        ppy=ppy,
        dates=dates,
        equity=tuple(float(value) for value in equity),
        opens={bar.ts: float(bar.open) for bar in bars},
    )


@dataclass(frozen=True)
class Joined:
    name: str
    same_asset: bool
    dates: list[datetime]
    strategy: Any
    market: Any
    ppy: int
    counts: dict[str, int]


def join_market(series: RunSeries, asset: str | None) -> Joined:
    """Inner-join the run with another asset's opens on timestamps; returns span shared bars."""
    name, opens = series.asset, series.opens
    if asset is not None:
        resolved = resolve_asset(asset, data_dir=series.home)
        name = f"{resolved.symbol}@{resolved.store_name}"
        if name != series.asset:
            # Point-in-time: nothing after the run's last bar is read.
            bars, _ = _runner.load_bars(
                resolved.symbol, data_dir=resolved.data_dir, as_of=series.dates[-1]
            )
            opens = {bar.ts: float(bar.open) for bar in bars}
    common = [date for date in series.dates if date in opens]
    inside = sum(series.dates[0] <= ts <= series.dates[-1] for ts in opens)
    counts = {
        "run_bars": len(series.dates),
        "other_bars_in_run_window": inside,
        "shared_bars": len(common),
        "run_bars_dropped": len(series.dates) - len(common),
        "other_bars_dropped": inside - len(common),
    }
    if len(common) < MIN_BARS + 1:
        raise SpineError(
            "TOO_FEW_BARS",
            f"Run {series.run_id} and {name} share {len(common)} bar timestamps; "
            f"{MIN_BARS + 1} are needed.",
            "Run alpha tool again with a benchmark or market that covers the run's dates.",
        )
    equity = dict(zip(series.dates, series.equity, strict=True))
    return Joined(
        name=name,
        same_asset=name == series.asset,
        dates=common,
        strategy=to_returns([equity[date] for date in common]),
        market=to_returns([opens[date] for date in common]),
        ppy=series.ppy if len(common) == len(series.dates) else periods_per_year(common),
        counts=counts,
    )


def regime_flags(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Observations on a causal regime split, never a verdict."""
    flags = []
    for row in rows:
        if row["share_of_time"] >= 0.95:
            flags.append(
                {
                    "flag": "one-regime-dominates",
                    "detail": (
                        f"The model put {row['share_of_time']:.0%} of bars in the {row['name']} "
                        "regime, so this market history shows no clear calm/turbulent split."
                    ),
                }
            )
        share = row["share_of_log_return"]
        if share is not None and share >= 0.8:
            flags.append(
                {
                    "flag": "return-concentrated-in-regime",
                    "detail": (
                        f"{share:.0%} of the strategy's total log return was earned in the "
                        f"{row['name']} regime, which covers {row['share_of_time']:.0%} of bars."
                    ),
                }
            )
    return flags
