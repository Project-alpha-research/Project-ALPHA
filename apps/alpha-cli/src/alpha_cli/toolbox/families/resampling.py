"""Intervals and alternate paths from the scored run, using the validation estimators."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any, Literal

from alpha_cli._seeds import semantic_seed
from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray

TESTS = "tests/unit/test_toolbox_resampling_checks.py::"
BASIS = "After-cost bar returns from the stored walk-forward equity curve."
BLOCK = Param("mean_block", float, 5.0, None, "Mean number of consecutive bars in a sampled block.")
CI_PARAMS = (
    Param("n_resamples", int, 2000, None, "Number of block-bootstrap samples."),
    BLOCK,
    Param("confidence", float, 0.95, None, "Confidence level for the two-sided interval."),
)
PAST = (
    "It assumes the future looks like blocks of this history; it cannot tell you how the rule"
    " will do if markets change character."
)


def _unavailable(keys: tuple[str, ...], reason: str, seed: int) -> Result:
    return Result(
        dict.fromkeys(keys), dict.fromkeys(keys, reason), details={"seed": seed}, basis=BASIS
    )


def _interval(
    inputs: Inputs, params: dict[str, Any], rng: Generator | None, *, sharpe: bool
) -> Result:
    import numpy as np

    from alpha_cli._gauntlet import safe_sharpe_statistic
    from alpha_validation.bootstrap import block_bootstrap_ci
    from alpha_validation.metrics import cagr

    returns = inputs.stored.scored_returns()
    minimum = 3 if sharpe else 2  # BCa also evaluates the statistic after leaving out one bar.
    keys = ("point", "lower", "upper")
    if len(returns) < minimum:
        return _unavailable(
            keys, f"The interval needs at least {minimum} scored bar returns.", inputs.seed
        )
    if returns.min() == returns.max():
        return _unavailable(
            keys, "A reportable interval needs varying scored returns.", inputs.seed
        )
    ppy = inputs.stored.ppy

    def yearly(sample: FloatArray) -> float:
        # The rule test's own cagr_ci statistic: CAGR of the resample compounded from 1.
        return cagr(np.concatenate(([1.0], np.cumprod(1.0 + sample))), periods_per_year=ppy)

    stat = safe_sharpe_statistic(ppy) if sharpe else yearly
    ci = block_bootstrap_ci(returns, stat, seed=inputs.seed, **params)
    return Result(
        {"point": ci.point, "lower": ci.lower, "upper": ci.upper},
        {},
        basis=BASIS,
        details={"seed": inputs.seed},
    )


def _interval_spec(
    tool_id: str, label: str, unit: Literal["ratio", "fraction"], namespace: str
) -> ToolSpec:
    sharpe = unit == "ratio"
    fmt = ".2f" if sharpe else ".1%"
    phrase = label[0].lower() + label[1:]
    return ToolSpec(
        id=tool_id,
        family="resampling",
        kind="test",
        look="test",
        question=f"What range of {phrase} does the scored history support?",
        needs=("stored_equity",),
        params=CI_PARAMS,
        outputs=(
            Output("point", label, f"The {phrase} of the scored after-cost returns.", unit),
            Output(
                "lower", "Lower limit", f"Lower end of the bootstrap interval for {phrase}.", unit
            ),
            Output(
                "upper", "Upper limit", f"Upper end of the bootstrap interval for {phrase}.", unit
            ),
        ),
        reading=(
            f"{label} was {{point:{fmt}}}. Resampling this history puts it between"
            f" {{lower:{fmt}}} and {{upper:{fmt}}}."
        ),
        caveats=(PAST,),
        seeded=True,
        legacy_seed=semantic_seed(7, namespace),
        time_safety="hindsight",
        poison_test=TESTS + "test_future_input_rejected",
        reference=TESTS + "test_public_function_parity",
        compute=partial(_interval, sharpe=sharpe),
    )


SHARPE_INTERVAL = _interval_spec(
    "resampling.sharpe_interval", "Yearly Sharpe ratio", "ratio", "validation.sharpe_ci"
)
RETURN_INTERVAL = _interval_spec(
    "resampling.return_interval", "Compound yearly return", "fraction", "validation.cagr_ci"
)


# Bound the paths-by-bars matrices allocated by path_metric_arrays, even on long histories.
PATH_CHUNK_CELLS = 4_000_000


def drawdowns(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    from alpha_core import DataError
    from alpha_validation.path_montecarlo import empirical_return_paths, path_metric_arrays

    returns = inputs.stored.scored_returns()
    if len(returns) < 2:
        return _unavailable(
            ("observed", "median", "q95"), "Paths need at least 2 scored bar returns.", inputs.seed
        )
    n_paths = params["n_paths"]
    if n_paths < 1:
        raise DataError(f"n_paths must be >= 1, got {n_paths}")
    chunk_size = max(1, PATH_CHUNK_CELLS // len(returns))
    maximum_drawdowns = np.empty(n_paths)
    # empirical_return_paths calls default_rng(seed), which reuses a supplied Generator.
    # Keep its state (including a buffered integer) across calls to reproduce one large draw.
    chunk_params = {**params, "seed": np.random.default_rng(inputs.seed)}
    for start in range(0, n_paths, chunk_size):
        stop = min(start + chunk_size, n_paths)
        chunk_params["n_paths"] = stop - start
        paths = empirical_return_paths(returns, **chunk_params)
        maximum_drawdowns[start:stop] = path_metric_arrays(paths).maximum_drawdown
    median, q95 = np.quantile(maximum_drawdowns, [0.50, 0.95])
    observed = path_metric_arrays(returns[None, :]).maximum_drawdown[0]
    return Result(
        {
            "observed": float(observed),
            "median": float(median),
            "q95": float(q95),
        },
        {},
        details={"seed": inputs.seed},
        basis=BASIS,
    )


DRAWDOWN_DISTRIBUTION = ToolSpec(
    id="resampling.drawdown_distribution",
    family="resampling",
    kind="test",
    look="test",
    question="How deep was the worst drop compared with histories redrawn from the same returns?",
    needs=("stored_equity",),
    params=(Param("n_paths", int, 10_000, None, "Number of redrawn histories."),),
    outputs=(
        Output(
            "observed",
            "Worst drop",
            "Largest peak-to-trough fall in the run's own equity.",
            "fraction",
        ),
        Output(
            "median",
            "Typical redrawn worst drop",
            "Median worst drop among histories redrawn bar by bar from the run's returns.",
            "fraction",
        ),
        Output(
            "q95",
            "1-in-20 redrawn worst drop",
            "95th percentile of the redrawn worst drops: one history in 20 fell further.",
            "fraction",
        ),
    ),
    reading=(
        "Worst drop in this run: {observed:.1%}. Redrawing its bar returns in random order gave a"
        " typical worst drop of {median:.1%}; one history in twenty fell further than {q95:.1%}."
    ),
    caveats=(
        "It treats every bar's return as independent of the one before, so it cannot show how"
        " losing streaks deepen drops. trades.dependence checks whether wins and losses bunched;"
        " resampling.block_bootstrap_paths keeps runs of bars together.",
    ),
    seeded=True,
    legacy_seed=semantic_seed(7, "monte_carlo.iid"),
    time_safety="hindsight",
    poison_test=TESTS + "test_future_input_rejected",
    reference=TESTS + "test_public_function_parity",
    compute=drawdowns,
)


def block_paths(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from alpha_validation.bootstrap import stationary_bootstrap_indices
    from alpha_validation.path_montecarlo import summarize_path_family

    returns = inputs.stored.scored_returns()
    keys = ("low", "median", "high", "drop_q95")
    if len(returns) < 2:
        return _unavailable(keys, "Paths need at least 2 scored bar returns.", inputs.seed)
    if rng is None:
        raise ValueError("Block-bootstrap paths require a seeded generator")
    # The public stationary bootstrap picks the bars; each row is one history of the full length.
    rows = stationary_bootstrap_indices(
        len(returns), mean_block=params["mean_block"], n_resamples=params["n_paths"], rng=rng
    )
    summary = summarize_path_family("stationary_bootstrap", returns[rows])
    return Result(
        {
            "low": summary.terminal_return_q05,
            "median": summary.terminal_return_q50,
            "high": summary.terminal_return_q95,
            "drop_q95": summary.maximum_drawdown_q95,
        },
        {},
        basis=BASIS,
        details={"seed": inputs.seed},
    )


BLOCK_PATHS = ToolSpec(
    id="resampling.block_bootstrap_paths",
    family="resampling",
    kind="test",
    look="test",
    question="What range of final return and worst drop do redrawn blocks of the history give?",
    needs=("stored_equity",),
    params=(
        Param("n_paths", int, 2000, None, "Number of redrawn histories."),
        BLOCK,
    ),
    outputs=(
        Output(
            "low",
            "Low final return",
            "5th percentile of final return: one history in 20 ended lower.",
            "fraction",
        ),
        Output("median", "Typical final return", "Median final return.", "fraction"),
        Output(
            "high",
            "High final return",
            "95th percentile of final return: one history in 20 ended higher.",
            "fraction",
        ),
        Output(
            "drop_q95",
            "1-in-20 worst drop",
            "95th percentile of the worst drops: one history in 20 fell further.",
            "fraction",
        ),
    ),
    reading=(
        "Redrawing this run's history in blocks gave a typical final return of {median:+.1%}."
        " Nine histories in ten ended between {low:+.1%} and {high:+.1%}."
        " One in twenty had a worst drop deeper than {drop_q95:.1%}."
    ),
    caveats=(
        "Blocks keep short runs of bars together but still assume the future looks like this"
        " history; they cannot tell you how the rule will do if markets change character.",
    ),
    seeded=True,
    time_safety="hindsight",
    poison_test=TESTS + "test_future_input_rejected",
    reference=TESTS + "test_public_function_parity",
    compute=block_paths,
)
