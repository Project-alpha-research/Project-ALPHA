"""Market descriptions built from the existing validation functions."""

from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING, Any

from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs, Joined

# Two assets' bars share a date stamp, not an instant: a coin's day opens at midnight UTC and a
# US stock's at the exchange open, so a cross-asset comparison carries this caveat.
CLOCKS = (
    "a shared timestamp is the same bar date, not the same instant, when the two assets open "
    "at different times of day; "
)


def attribution(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from alpha_cli.toolbox.inputs import join_market
    from alpha_validation.attribution import market_attribution

    joined = join_market(inputs)
    result = market_attribution(joined.strategy, joined.market, periods_per_year=joined.ppy)
    basis = (
        f"full-sample strategy returns against buy-and-hold open-to-open returns of "
        f"{joined.name} on shared timestamps (the engine marks equity at each bar's open); "
        f"{'' if joined.same_asset else CLOCKS}{result.pop('basis')}"
    )
    result.update(benchmark=joined.name, periods_per_year=joined.ppy, join=joined.counts)
    return Result(
        {key: result[key] for key in ("beta", "alpha_annual", "alpha_p", "r_squared")},
        {},
        labels=("benchmark-is-same-asset",) if joined.same_asset else (),
        basis=basis,
        details=result,
        params={"benchmark": joined.name, "risk_free": 0.0},
    )


def _split(joined: Joined, state: list[int], k: int, basis: str) -> dict[str, Any]:
    from alpha_validation import regimes as regime_model

    split = regime_model.returns_by_regime(
        joined.strategy, joined.market, state, periods_per_year=joined.ppy, k=k
    )
    for row in split["regimes"]:
        row["name"] = {0: "calm", k - 1: "turbulent"}.get(row["regime"], f"middle {row['regime']}")
    return {"basis": basis, **split}


def regime_reading(causal: list[dict[str, Any]], hindsight: list[dict[str, Any]]) -> dict[str, Any]:
    def shares(rows: list[dict[str, Any]]) -> str:
        return ", ".join(
            f"{row['name']} "
            + (
                "unavailable"
                if row["share_of_log_return"] is None
                else f"{row['share_of_log_return']:.0%}"
            )
            for row in rows
        )

    second = {row["regime"]: row["share_of_log_return"] for row in hindsight}
    disagrees = any(
        row["share_of_log_return"] is not None
        and second[row["regime"]] is not None
        and row["share_of_log_return"] * second[row["regime"]] < 0
        for row in causal
    )
    sentence = (
        f"Causal split: {shares(causal)} of return; "
        f"with hindsight (not knowable at the time): {shares(hindsight)}."
    )
    if disagrees:
        sentence += " Hindsight would tell a different story here; use the causal split."
    return {"sentence": sentence, "labels": ["hindsight-disagrees"] if disagrees else []}


def regimes(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from alpha_cli.toolbox.inputs import join_market, regime_flags
    from alpha_validation import regimes as regime_model

    joined = join_market(inputs)
    k = params["k"]
    # The published default fit uses seed zero, including its optimiser restarts.
    seed = inputs.seed
    fit = regime_model.volatility_regimes(joined.market, k=k, seed=seed)
    if not fit["converged"]:
        raise SpineError(
            "MODEL_DID_NOT_CONVERGE",
            f"The {k}-regime model did not converge on {joined.name}: {fit['reason']}.",
            "Use --param k=2 or --param market=SYMBOL with a longer history.",
        )
    causal = _split(joined, fit["causal_state"], k, regime_model.SPLIT_BASIS)
    hindsight = _split(joined, fit["hindsight_state"], k, regime_model.HINDSIGHT_BASIS)
    reading = regime_reading(causal["regimes"], hindsight["regimes"])
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
        "causal": causal,
        "split": causal,  # compatibility for previously published tool consumers
        "hindsight": {
            "title": "with hindsight (not knowable at the time)",
            "labels": ["hindsight"],
            **hindsight,
        },
        "sentence": reading["sentence"],
        "flags": regime_flags(causal["regimes"]),
        "series": {
            "dates": [date.isoformat() for date in joined.dates[1:]],
            "filtered_turbulent_probability": [row[-1] for row in fit["filtered"]],
            "causal_state": fit["causal_state"],
            "hindsight_state": fit["hindsight_state"],
        },
    }
    basis = (
        f"{reading['sentence']} {fit['basis']}; market = open-to-open returns of "
        f"{joined.name}, matching the "
        "engine's open-marked equity; "
        f"{'' if joined.same_asset else CLOCKS}{regime_model.SPLIT_BASIS}"
    )
    return Result(
        {
            "turbulent_share_of_return": turbulent["share_of_log_return"],
            "turbulent_share_of_time": turbulent["share_of_time"],
        },
        {"turbulent_share_of_return": turbulent["reasons"]["share_of_log_return"]}
        if turbulent["share_of_log_return"] is None
        else {},
        labels=(
            *reading["labels"],
            *fit["labels"],
            *(["benchmark-is-same-asset"] if joined.same_asset else []),
        ),
        series=result.pop("series"),
        details=result,
        basis=basis,
        params={"market": joined.name, "k": k, "seed": seed},
    )


CHANGE_NEAR_POSITION_BARS = 5
# Above this share of bars near a switch, "position change" is weak evidence.
NEAR_SWITCH_ROUGH = 0.2


def describe_changes(
    breaks: list[int], dates: tuple[datetime, ...], positions: tuple[bool, ...], *, shift: int
) -> dict[str, Any]:
    if not positions:
        # No recorded position series: never guess, so no break is called a behaviour shift.
        return {
            "breaks": [
                {
                    "index": index,
                    "date": dates[index + shift].isoformat(),
                    "position_change": None,
                    "label": "position state unknown",
                }
                for index in breaks
            ],
            "behaviour_shifts": None,
            "position_changes": None,
            "sentence": (
                f"{len(breaks)} change points; the rule's position state was not recorded, so "
                "none can be told apart from the rule stepping in or out."
            ),
        }
    if len(positions) != len(dates):
        raise ValueError("change points require a position state for every bar")
    transitions = [i for i in range(1, len(positions)) if positions[i] != positions[i - 1]]
    rows = []
    for index in breaks:
        bar = index + shift
        nearby = any(abs(bar - change) <= CHANGE_NEAR_POSITION_BARS for change in transitions)
        rows.append(
            {
                "index": index,
                "date": dates[bar].isoformat(),
                "position_change": nearby,
                "label": "position change" if nearby else "behaviour shift",
            }
        )
    stepping = sum(row["position_change"] is True for row in rows)
    shifts = len(rows) - stepping
    sentence = (
        "No shift in behaviour found beyond entering and leaving the market "
        f"({stepping} change points, all the rule stepping in or out)."
        if rows and shifts == 0
        else (
            f"{shifts} shifts while in the market; {stepping} are just the rule stepping in or out."
        )
    )
    # How much of the history is "near a switch": when it is large, the split is rough.
    near = sum(
        any(abs(bar - change) <= CHANGE_NEAR_POSITION_BARS for change in transitions)
        for bar in range(len(positions))
    ) / len(positions)
    if near > NEAR_SWITCH_ROUGH:
        sentence += (
            f" {near:.0%} of all bars lie within {CHANGE_NEAR_POSITION_BARS} bars of a switch, "
            "so this split is rough."
        )
    return {
        "breaks": rows,
        "behaviour_shifts": shifts,
        "position_changes": stepping,
        "near_switch_share": near,
        "sentence": sentence,
    }


def changepoints(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    from alpha_validation.changepoints import change_points
    from alpha_validation.metrics import annualized_volatility, to_returns

    on = params["on"]
    series = inputs.run
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
                "annual_volatility": annualized_volatility(part, periods_per_year=series.ppy),
            }
        )
    params = {key: found[key] for key in ("model", "min_size", "max_points")} | {"on": on}
    changes = describe_changes(found["breaks"], series.dates, series.positions, shift=shift)
    result = {
        **changes,
        "on": on,
        "periods_per_year": series.ppy,
        "penalty": found["penalty"],
        "penalty_raises": found["penalty_raises"],
        "segments": segments,
    }
    basis = (
        f"{changes['sentence']} {found['basis']}; searched on the run's full-sample "
        f"{'per-bar returns' if on == 'returns' else 'log equity curve'}; segment annual return "
        "= mean per-bar return * periods_per_year, volatility = standard deviation * sqrt of it"
    )
    return Result(
        {"count": changes["behaviour_shifts"]},
        {"count": "the rule's position state was not recorded"}
        if changes["behaviour_shifts"] is None
        else {},
        labels=tuple(found["labels"]),
        basis=basis,
        details=result,
        params=params,
    )


ATTRIBUTION = ToolSpec(
    id="market.attribution",
    question="How much of the return comes from exposure to the benchmark?",
    needs=("run_returns", "run_bars"),
    params=(
        Param("benchmark", str, None, None, "Comparison asset, defaulting to the run's own asset."),
    ),
    outputs=(
        Output(
            "beta",
            "Market beta",
            "How much the strategy moves when the benchmark moves by one (1 = one for one).",
            "ratio",
            "market_beta",
            "result.beta",
        ),
        Output(
            "alpha_annual",
            "Annual alpha",
            "Yearly return left over after removing the benchmark exposure.",
            "fraction",
            "market_alpha_annual",
            "result.alpha_annual",
        ),
        Output(
            "alpha_p",
            "Alpha p-value",
            "Chance of a leftover return this large if the true leftover were zero (p-value).",
            "p_value",
            "market_alpha_p",
            "result.alpha_p",
        ),
        Output(
            "r_squared",
            "Explained variation",
            "Share of the strategy's return variation explained by the benchmark.",
            "fraction",
            "market_r_squared",
            "result.r_squared",
        ),
    ),
    reading="Market beta is {beta:.4f} and annual alpha is {alpha_annual:.2%}.",
    caveats=("The regression uses one benchmark and open-to-open returns on shared timestamps.",),
    reference="tests/unit/test_attribution.py::test_matches_first_principles_and_independent_newey_west",
    compute=attribution,
    time_safety="needs_pit_guard",
    poison_test="tests/unit/test_toolbox_runner.py::test_future_market_bars_do_not_change_inputs",
)

VOL_REGIMES = ToolSpec(
    id="market.vol_regimes",
    question="Does the rule earn its return in calm or turbulent markets?",
    needs=("run_returns", "run_bars"),
    params=(
        Param("market", str, None, None, "Market asset, defaulting to the run's own asset."),
        Param("k", int, 2, (2, 3, 4), "Number of market regimes."),
    ),
    outputs=(
        Output(
            "turbulent_share_of_return",
            "Turbulent return share",
            "Share of the strategy's total log return earned in the most turbulent market regime.",
            "fraction",
            "regime_turbulent_share_of_return",
            "result.split.regimes[-1].share_of_log_return",
        ),
        Output(
            "turbulent_share_of_time",
            "Turbulent time share",
            "Share of bars the market spent in its most turbulent regime.",
            "fraction",
            "regime_turbulent_share_of_time",
            "result.split.regimes[-1].share_of_time",
        ),
    ),
    reading=(
        "The turbulent regime covered {turbulent_share_of_time:.2%} of bars "
        "and earned {turbulent_share_of_return:.2%} of return."
    ),
    caveats=("Regime parameters use the full sample. The smoothed split uses hindsight.",),
    reference="tests/unit/test_regimes.py::test_output_matches_statsmodels_reordered_by_variance",
    compute=regimes,
    seeded=True,
    legacy_seed=0,
    time_safety="hindsight",
    poison_test="tests/unit/test_regimes.py::test_a_bar_cannot_change_its_own_causal_label",
)

CHANGEPOINTS = ToolSpec(
    id="market.changepoints",
    question="When did the behaviour of the rule change?",
    needs=("run_returns", "run_positions"),
    params=(Param("on", str, "returns", ("returns", "equity"), "Search returns or log equity."),),
    outputs=(
        Output(
            "count",
            "Behaviour shifts",
            "Number of dates at which the run's behaviour shifted, found with hindsight.",
            "count",
            "changepoint_count",
            "result.behaviour_shifts",
        ),
    ),
    reading="Shifts in behaviour after allowing for position changes: {count}.",
    caveats=("Breaks are found with hindsight. Frequent position switches make the split rough.",),
    reference="tests/unit/test_changepoints.py::test_same_breaks_as_ruptures_pelt_with_the_matching_cost",
    compute=changepoints,
    time_safety="hindsight",
    poison_test="tests/unit/test_toolbox_runner.py::test_future_bars_do_not_enter_replay",
)
