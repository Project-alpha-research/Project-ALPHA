"""Readings that set a run beside published reference series (descriptive, never a verdict)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox.contract import Output, Result, ToolSpec, Value
from alpha_cli.toolbox.published_parts import (
    BASIS,
    CAUTION,
    FIXED,
    INFERRED,
    INFERRED_LABEL,
    MONTHLY,
    NOT_STOCKS,
    NOT_US,
    NUMBERS,
    ONE_AT_A_TIME,
    UNKNOWN,
    exposures,
    search,
    series_by_signal,
    singles,
)
from alpha_cli.toolbox.reference import LABEL, SENTENCE, read_reference_for_period
from alpha_cli.toolbox.run_months import scored_monthly, us_asset_class

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs


def _typed(
    branch: str, sentence: str, details: dict[str, Any], labels: tuple[str, ...] = ()
) -> Result:
    values: dict[str, Value] = dict.fromkeys(NUMBERS)
    reasons = dict.fromkeys(NUMBERS, sentence)
    values["sentence"] = sentence
    return Result(
        values, reasons, labels=(LABEL, *labels), basis=BASIS, details={"branch": branch, **details}
    )


def published_factors(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    from alpha_core import DataError
    from alpha_validation.factor_attribution import factor_attribution, min_observations

    home, target = inputs.data_home, inputs.stored
    asset_class, basis = us_asset_class(home, target)
    extra = (INFERRED_LABEL,) if basis == "calendar" else ()
    if asset_class not in {"stock", "etf"}:
        branch, sentence = (
            ("unknown-asset", UNKNOWN) if asset_class is None else ("not-applicable", NOT_US)
        )
        return _typed(branch, sentence, {"periods_per_year": MONTHLY})
    fund = f" {NOT_STOCKS}" if asset_class == "etf" else ""
    fund += f" {INFERRED}" if basis == "calendar" else ""
    monthly = scored_monthly(home, target)
    reference = read_reference_for_period(
        home, first_day=monthly.first_day, last_day=monthly.last_day
    )
    by_signal, years = series_by_signal(reference.rows)
    absent = [name for name, _ in FIXED if name not in by_signal]
    if absent:
        raise SpineError(
            "FACTOR_MISSING", f"The stored file has no {absent}.", "Pull a newer release."
        )
    pairs = [
        (month, value)
        for month, value in zip(monthly.months, monthly.returns, strict=True)
        if all(month in by_signal[name] for name, _ in FIXED)
    ]
    used = [month for month, _ in pairs]
    strategy = [value for _, value in pairs]
    need = min_observations(len(FIXED))
    details: dict[str, Any] = {
        "vintage": reference.vintage,
        "periods_per_year": MONTHLY,
        "months_used": [m.isoformat() for m in used],
        "months_used_count": len(used),
        "months_incomplete": [m.isoformat() for m in monthly.incomplete],
        "months_without_reference": len(monthly.months) - len(used),
        "months_needed": need,
        "reference_rule": SENTENCE,
    }
    if basis == "calendar":
        details["asset_kind_basis"] = basis
    if len(used) < need:
        text = f"Cannot read: too few months to read ({len(used)} of {need} needed)."
        return _typed("too-few-months", text, details, extra)
    names = [name for name, _ in FIXED]
    matrix = np.column_stack([[by_signal[name][m] for m in used] for name in names])
    found = search(strategy, used, by_signal, years)
    details["search"] = found
    try:
        fit = factor_attribution(strategy, matrix, periods_per_year=MONTHLY, factor_names=names)
    except DataError as exc:
        if "collinear" not in str(exc):
            raise
        alone = singles(strategy, matrix, names)
        details.update(refusal=str(exc), singles=alone)
        if not any("beta" in row for row in alone):
            return _typed(
                "cannot-read",
                "Cannot read: factors too similar in this period.",
                details,
                extra,
            )
        text = f"{ONE_AT_A_TIME} Each one is in the details. {CAUTION}{fund} {found['sentence']}"
        return _typed("collinear-singles", text, details, extra)
    labels = dict(FIXED)
    factors = [
        {
            **row,
            "signal": row["name"],
            "label": labels[row["name"]],
            "published_year": years[row["name"]],
        }
        for row in fit["factors"]
    ]
    low, high = fit["alpha_ci95_per_period"]
    details.update(
        branch="read", factors=factors, fit={k: v for k, v in fit.items() if k != "factors"}
    )
    sentence = (
        f"About {fit['r_squared']:.0%} of the month-to-month variation in this strategy's returns "
        f"moves with these published factors (adjusted for their number: "
        f"{fit['adj_r_squared']:.0%}). "
        f"The part not explained by them is {fit['alpha_per_period']:.2%} a month (95% range "
        f"{low:.2%} to {high:.2%}), or {fit['alpha_annual']:.1%} a year, over {fit['n']} months. "
        f"{exposures(factors)} {CAUTION}{fund} {found['sentence']}"
    )
    values: dict[str, Value] = {
        "explained_share": fit["r_squared"],
        "sentence": sentence,
    }
    return Result(values, {}, labels=(LABEL, *extra), basis=BASIS, details=details)


def _fraction(key: str, label: str, gloss: str) -> Output:
    return Output(key, label, gloss, "fraction")


PUBLISHED_FACTORS = ToolSpec(
    id="context.published_factors",
    family="context",
    answers=("Is this just a known published factor?", "Is the result new?"),
    situations=("just-the-market", "looks-too-good", "known-factor"),
    question="How much of this strategy's monthly returns moves with well-known published factors?",
    needs=("stored_equity", "reference_factors"),
    params=(),
    outputs=(
        _fraction(
            "explained_share",
            "Explained share",
            "Share of the month-to-month variation that moves with the factors (R squared).",
        ),
        Output(
            "sentence",
            "Reading",
            "Plain reading, with the exploratory search across all signals.",
            "text",
        ),
    ),
    reading=f"{{sentence}} {SENTENCE}",
    caveats=(
        "The factors are US stock factors; an ETF that holds no stocks is not a stock strategy.",
        "The ranges use large-sample approximations and are too narrow when months are few.",
        "A significant exposure is not evidence of an edge; a low share does not prove one.",
        "The correlation range of the search assumes independent months.",
    ),
    reference="tests/unit/test_toolbox_published_factors.py::test_known_answer_planted_factor",
    compute=published_factors,
    version=2,
    time_safety="hindsight",
    poison_test="tests/unit/test_toolbox_published_factors.py::test_held_back_months_are_never_read",
)
