"""Tail checks on the scored returns: a generalised Pareto and Hill tail fit."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result
from alpha_cli.toolbox.families.risk_common import (
    BASIS,
    PAST,
    bar_returns,
    check,
    unavailable,
)

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs

    BoolArray = npt.NDArray[np.bool_]

TESTS = "test_toolbox_risk_sizing_b"
MIN_EXCEEDANCES = 20
TAIL = Param(
    "tail_fraction", float, 0.1, (0.05, 0.1, 0.2), "Share of the worst bars used to fit the tail."
)


def tail_fit(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np
    from scipy import stats

    keys = ("threshold", "exceedances", "gpd_shape", "gpd_scale", "hill_index", "var_99", "es_99")
    losses = -bar_returns(inputs)
    n = len(losses)
    threshold = float(np.quantile(losses, 1 - params["tail_fraction"])) if n else 0.0
    beyond = losses[losses > threshold] - threshold
    if len(beyond) < MIN_EXCEEDANCES:
        why = (
            f"Needs at least {MIN_EXCEEDANCES} losses beyond the threshold; found {len(beyond)}"
            f" in {n} bars."
        )
        return unavailable(keys, why)
    k = len(beyond)
    # McNeil and Frey (2000): peaks over threshold, a generalised Pareto fit to the excesses.
    shape, _, scale = (float(x) for x in stats.genpareto.fit(beyond, floc=0))
    values: dict[str, Any] = {
        "threshold": threshold,
        "exceedances": k,
        "gpd_shape": shape,
        "gpd_scale": scale,
    }
    reasons: dict[str, str] = {}
    ordered = np.sort(losses)[::-1]
    if ordered[k] > 0:
        # Hill (1975): mean log ratio of the k largest losses to the next one.
        values["hill_index"] = float(np.mean(np.log(ordered[:k] / ordered[k])))
    else:
        values["hill_index"] = None
        reasons["hill_index"] = "The Hill estimator needs positive losses at the threshold."
    ratio = n / k * (1 - 0.99)
    if shape >= 1:
        values.update(var_99=None, es_99=None)
        reasons.update(dict.fromkeys(("var_99", "es_99"), "The fitted tail has no finite mean."))
        return Result(values, reasons, basis=BASIS)
    if abs(shape) < 1e-9:
        var = threshold - scale * math.log(ratio)
    else:
        var = threshold + scale / shape * (ratio ** (-shape) - 1)
    values["var_99"] = float(var)
    values["es_99"] = float((var + scale - shape * threshold) / (1 - shape))
    return Result(values, reasons, basis=BASIS)


CHECKS = (
    check(
        "risk.tail_fit",
        TESTS,
        question="How heavy is the loss tail once the worst bars are fitted on their own?",
        answers=("How fat is the tail of my losses?", "How bad can the worst losses get?"),
        situations=("drawdown", "return-range"),
        needs=("stored_equity",),
        params=(TAIL,),
        outputs=(
            Output(
                "threshold",
                "Tail threshold",
                "Loss per bar above which a bar counts in the tail.",
                "fraction",
            ),
            Output(
                "exceedances",
                "Tail bars",
                "Count of bars with a loss beyond the threshold.",
                "count",
            ),
            Output(
                "gpd_shape",
                "Tail shape",
                "Generalised Pareto shape; larger means a heavier tail.",
                "ratio",
            ),
            Output(
                "gpd_scale",
                "Tail scale",
                "Generalised Pareto scale of the excess loss.",
                "fraction",
            ),
            Output(
                "hill_index",
                "Hill index",
                "Hill estimate of the tail index from the same bars.",
                "ratio",
            ),
            Output(
                "var_99",
                "One-in-100 loss",
                "Loss per bar the fitted tail gives at the 99% level.",
                "fraction",
            ),
            Output(
                "es_99",
                "Average beyond that",
                "Average loss per bar beyond the one-in-100 loss.",
                "fraction",
            ),
        ),
        reading=(
            "The worst bars started at a loss of {threshold:.2%}. Fitting them gives a tail"
            " shape of"
            " {gpd_shape:.2f} (Hill {hill_index:.2f}), a one-in-a-hundred loss of {var_99:.2%}"
            " and an average"
            " of {es_99:.2%} beyond that."
        ),
        caveats=(
            PAST + " A tail fit rests on few bars; its shape moves a lot with the threshold.",
        ),
        compute=tail_fit,
        cost="seconds",
    ),
)
