"""Investigation tools over a recorded rule test: market attribution, regimes, change points.

Each tool rebuilds the run's full-sample returns (``tool_inputs.load_run``), calls one pure
function in ``alpha_validation``, appends one ledger row and stores its output OUTSIDE the
immutable run directory: ``<home>/diagnostics/<run_id>/<tool>-<sha8 of params>.json``.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.ledger import append_trial
from alpha_cli.spine.tool_inputs import Joined, RunSeries, join_market, load_run, regime_flags
from alpha_core import atomic
from alpha_validation import regimes as regime_model
from alpha_validation.attribution import market_attribution
from alpha_validation.changepoints import change_points
from alpha_validation.metrics import to_returns


def record(
    series: RunSeries,
    tool: str,
    params: dict[str, Any],
    labels: list[str],
    basis: str,
    result: dict[str, Any],
    facts: list[tuple[str, str, Any, str | None]],
) -> dict[str, Any]:
    """Count the tool run in the ledger, then publish its output beside (not inside) the run."""
    canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), allow_nan=False)
    relative = (
        f"diagnostics/{series.run_id}/{tool}-{hashlib.sha256(canonical.encode()).hexdigest()[:8]}"
        ".json"
    )
    spine = series.manifest["spine"]
    labels = list(dict.fromkeys([*spine.get("labels", []), *labels]))
    row = append_trial(
        series.home,
        {
            "kind": f"tool:{tool}",
            "run_id": series.run_id,
            "test_id": spine.get("test_id"),
            "name": spine.get("name"),
            "symbol": series.manifest["metadata"]["symbol"],
            "store": spine.get("store"),
            "params": params,
            "tool_output": relative,
            "labels": labels,
            "verdict": None,
        },
    )
    document = {
        "tool": tool,
        "params": params,
        "run_id": series.run_id,
        "test_id": spine.get("test_id"),
        "recorded_at": datetime.now(UTC).isoformat(),
        "labels": labels,
        "basis": basis,
        "result": result,
        "facts": [
            {
                "metric": metric,
                "value": value,
                "run_id": series.run_id,
                "basis": basis,
                "source": f"{relative}:{field}",
                "labels": labels,
                "reason": (reason or f"{field} is unavailable") if value is None else None,
            }
            for metric, field, value, reason in facts
        ],
    }
    atomic.write_text(
        series.home / relative, json.dumps(document, sort_keys=True, indent=2, allow_nan=False)
    )
    return {**document, "file": relative, "trials_total": row["total_trials"]}


# Two assets' bars share a date stamp, not an instant: a coin's day opens at midnight UTC and a
# US stock's at the exchange open, so a cross-asset comparison carries this caveat.
CLOCKS = (
    "a shared timestamp is the same bar date, not the same instant, when the two assets open "
    "at different times of day; "
)


def attribution(home: Path, run_id: str, benchmark: str | None = None) -> dict[str, Any]:
    series = load_run(home, run_id)
    joined = join_market(series, benchmark)
    result = market_attribution(joined.strategy, joined.market, periods_per_year=joined.ppy)
    basis = (
        f"full-sample strategy returns against buy-and-hold open-to-open returns of "
        f"{joined.name} on shared timestamps (the engine marks equity at each bar's open); "
        f"{'' if joined.same_asset else CLOCKS}{result.pop('basis')}"
    )
    result.update(benchmark=joined.name, periods_per_year=joined.ppy, join=joined.counts)
    return record(
        series,
        "attribution",
        {"benchmark": joined.name, "risk_free": 0.0},
        ["benchmark-is-same-asset"] if joined.same_asset else [],
        basis,
        result,
        [
            ("market_beta", "result.beta", result["beta"], None),
            ("market_alpha_annual", "result.alpha_annual", result["alpha_annual"], None),
            ("market_alpha_p", "result.alpha_p", result["alpha_p"], None),
            ("market_r_squared", "result.r_squared", result["r_squared"], None),
        ],
    )


def _split(joined: Joined, state: list[int], k: int, basis: str) -> dict[str, Any]:
    split = regime_model.returns_by_regime(
        joined.strategy, joined.market, state, periods_per_year=joined.ppy, k=k
    )
    for row in split["regimes"]:
        row["name"] = {0: "calm", k - 1: "turbulent"}.get(row["regime"], f"middle {row['regime']}")
    return {"basis": basis, **split}


def regimes(home: Path, run_id: str, market: str | None = None, k: int = 2) -> dict[str, Any]:
    series = load_run(home, run_id)
    joined = join_market(series, market)
    fit = regime_model.volatility_regimes(joined.market, k=k, seed=0)
    if not fit["converged"]:
        raise SpineError(
            "MODEL_DID_NOT_CONVERGE",
            f"The {k}-regime model did not converge on {joined.name}: {fit['reason']}.",
            "Run alpha tool regimes again with --k 2, or with a --market with a longer history.",
        )
    causal = _split(joined, fit["causal_state"], k, regime_model.SPLIT_BASIS)
    hindsight = _split(joined, fit["hindsight_state"], k, regime_model.HINDSIGHT_BASIS)
    turbulent = causal["regimes"][-1]
    result = {
        "market": joined.name,
        "periods_per_year": joined.ppy,
        "join": joined.counts,
        "model": {
            key: fit[key]
            for key in ("k", "n", "means", "variances", "transition", "expected_durations")
        }
        | {"annual_volatility": [math.sqrt(v * joined.ppy) for v in fit["variances"]]},
        "split": causal,
        "hindsight": {"labels": ["hindsight"], **hindsight},
        "flags": regime_flags(causal["regimes"]),
        "series": {
            "dates": [date.isoformat() for date in joined.dates[1:]],
            "filtered_turbulent_probability": [row[-1] for row in fit["filtered"]],
            "causal_state": fit["causal_state"],
            "hindsight_state": fit["hindsight_state"],
        },
    }
    basis = (
        f"{fit['basis']}; market = open-to-open returns of {joined.name}, matching the "
        "engine's open-marked equity; "
        f"{'' if joined.same_asset else CLOCKS}{regime_model.SPLIT_BASIS}"
    )
    return record(
        series,
        "regimes",
        {"market": joined.name, "k": k, "seed": 0},
        [*fit["labels"], *(["benchmark-is-same-asset"] if joined.same_asset else [])],
        basis,
        result,
        [
            (
                "regime_turbulent_share_of_return",
                "result.split.regimes[-1].share_of_log_return",
                turbulent["share_of_log_return"],
                turbulent["reasons"].get("share_of_log_return"),
            ),
            (
                "regime_turbulent_share_of_time",
                "result.split.regimes[-1].share_of_time",
                turbulent["share_of_time"],
                None,
            ),
        ],
    )


def changepoints(home: Path, run_id: str, on: str = "returns") -> dict[str, Any]:
    if on not in ("returns", "equity"):
        raise SpineError(
            "UNKNOWN_SERIES",
            f"Unknown series {on!r}.",
            "Run alpha tool changepoints with --on returns or --on equity.",
            ["returns", "equity"],
        )
    series = load_run(home, run_id)
    returns = to_returns(series.equity)
    found = change_points(returns if on == "returns" else np.log(series.equity))
    # Return i ends at dates[i + 1]; equity point i sits at dates[i].
    shift = 1 if on == "returns" else 0
    segments = []
    for segment in found["segments"]:
        first = max(segment["start"] + shift - 1, 0)
        part = returns[first : segment["end"] + shift - 1]
        segments.append(
            {
                "start_date": series.dates[segment["start"] + shift].isoformat(),
                "end_date": series.dates[segment["end"] + shift - 1].isoformat(),
                "bars": segment["n"],
                "annual_return": float(np.mean(part)) * series.ppy,
                "annual_volatility": float(np.std(part, ddof=1)) * math.sqrt(series.ppy),
            }
        )
    params = {key: found[key] for key in ("model", "min_size", "max_points")} | {"on": on}
    result = {
        "on": on,
        "periods_per_year": series.ppy,
        "penalty": found["penalty"],
        "penalty_raises": found["penalty_raises"],
        "breaks": [
            {"index": index, "date": series.dates[index + shift].isoformat()}
            for index in found["breaks"]
        ],
        "segments": segments,
    }
    basis = (
        f"{found['basis']}; searched on the run's full-sample "
        f"{'per-bar returns' if on == 'returns' else 'log equity curve'}; segment annual return "
        "= mean per-bar return * periods_per_year, volatility = standard deviation * sqrt of it"
    )
    return record(
        series,
        "changepoints",
        params,
        found["labels"],
        basis,
        result,
        [("changepoint_count", "result.breaks", len(found["breaks"]), None)],
    )
