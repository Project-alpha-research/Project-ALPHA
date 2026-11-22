"""Shuffles that break one feature of the history: order, spectrum phase, year order, halves."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result
from alpha_cli.toolbox.families.resampling_more_common import (
    N_PATHS,
    PAST,
    RETURN_BASIS,
    blank,
    make_spec,
    scored,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray

DROP_KEYS = ("observed", "median", "q95", "share_as_deep")
DROP_OUTPUTS = (
    Output(
        "observed", "Worst drop", "Largest peak-to-trough fall in the run's own equity.", "fraction"
    ),
    Output(
        "median",
        "Typical redrawn worst drop",
        "Median worst drop among redrawn histories.",
        "fraction",
    ),
    Output(
        "q95",
        "1-in-20 redrawn worst drop",
        "95th percentile of the redrawn worst drops: one history in 20 fell further.",
        "fraction",
    ),
    Output(
        "share_as_deep",
        "Share as deep",
        "Share of redrawn histories whose worst drop was at least as deep as the run's own.",
        "fraction",
    ),
)
DROP_READING = (
    "Worst drop in this run: {observed:.1%}. {what} gave a typical worst drop of {median:.1%};"
    " one history in twenty fell further than {q95:.1%}, and {share_as_deep:.0%} fell at"
    " least as far as this run."
)


def lag_one(values: FloatArray) -> Any:
    """Lag-1 autocorrelation of each row (mean-removed, Box and Jenkins 1970 sample form)."""

    centred = values - values.mean(axis=-1, keepdims=True)
    return (centred[..., 1:] * centred[..., :-1]).sum(axis=-1) / (centred**2).sum(axis=-1)


def shuffle(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    returns = scored(inputs)
    keys = ("autocorr", "null_low", "null_high", "p_value")
    if len(returns) < 10:
        reason = "The order test needs at least 10 scored bar returns."
        return blank(keys, reason, RETURN_BASIS, inputs.seed)
    if returns.min() == returns.max():
        return blank(
            keys, "A reportable test needs varying scored returns.", RETURN_BASIS, inputs.seed
        )
    n = params["n_shuffles"]
    if n < 1 or rng is None:
        raise ValueError("n_shuffles must be at least 1 and a seeded generator is required")
    observed = float(lag_one(returns))
    shuffled = lag_one(rng.permuted(np.tile(returns, (n, 1)), axis=1))
    low, high = np.quantile(shuffled, [0.025, 0.975])
    # Permutation p-value with the observed order counted as one draw (Phipson and Smyth 2010).
    p_value = (1 + int(np.sum(np.abs(shuffled) >= abs(observed)))) / (n + 1)
    return Result(
        {
            "autocorr": observed,
            "null_low": float(low),
            "null_high": float(high),
            "p_value": p_value,
        },
        {},
        basis=RETURN_BASIS,
        details={"seed": inputs.seed},
    )


RETURN_SHUFFLE = make_spec(
    "resampling.return_shuffle",
    question="Does the order of the bar returns carry anything beyond the returns themselves?",
    needs=("stored_equity",),
    params=(Param("n_shuffles", int, 2000, None, "Number of random reorderings."),),
    outputs=(
        Output(
            "autocorr",
            "Bar-to-bar correlation",
            "Correlation between each bar's return and the next one's, in the run's order.",
            "ratio",
        ),
        Output(
            "null_low",
            "Shuffled low",
            "2.5th percentile of that correlation after reordering.",
            "ratio",
        ),
        Output(
            "null_high",
            "Shuffled high",
            "97.5th percentile of that correlation after reordering.",
            "ratio",
        ),
        Output(
            "p_value",
            "Permutation p-value",
            "Share of reorderings (counting the real order) with a correlation as far from zero.",
            "p_value",
        ),
    ),
    reading=(
        "Each bar's return correlated {autocorr:+.3f} with the next. Random reordering gives"
        " between {null_low:+.3f} and {null_high:+.3f} (p-value {p_value:.3f}; a small p-value"
        " means the order was probably not random)."
    ),
    caveats=(
        "It only looks at the first step of order. A pattern at longer gaps, or a reason for the"
        " pattern, is outside what it can tell you.",
    ),
    reference="test_known_answer_shuffle",
    compute=shuffle,
    situations=("trade-streaks", "looks-too-good"),
    seeded=True,
)


def phase_surrogate(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    """Phase-randomised surrogates of log returns (Theiler et al. 1992): same spectrum."""
    import numpy as np

    from alpha_validation.path_montecarlo import path_metric_arrays

    returns = scored(inputs)
    if len(returns) < 8:
        reason = "The surrogates need at least 8 scored bar returns."
        return blank(DROP_KEYS, reason, RETURN_BASIS, inputs.seed)
    n = params["n_paths"]
    if n < 1 or rng is None:
        raise ValueError("n_paths must be at least 1 and a seeded generator is required")
    logs = np.log1p(returns)
    spectrum = np.fft.rfft(logs)
    phases = np.exp(2j * np.pi * rng.random((n, len(spectrum))))
    phases[:, 0] = 1.0
    if len(logs) % 2 == 0:
        phases[:, -1] = 1.0  # the Nyquist bin must stay real
    surrogates = np.fft.irfft(spectrum * phases, n=len(logs), axis=1)
    drops = path_metric_arrays(np.expm1(surrogates)).maximum_drawdown
    observed = float(path_metric_arrays(returns[None, :]).maximum_drawdown[0])
    median, q95 = np.quantile(drops, [0.5, 0.95])
    return Result(
        dict(
            zip(
                DROP_KEYS,
                (observed, float(median), float(q95), float(np.mean(drops >= observed))),
                strict=True,
            )
        ),
        {},
        basis=RETURN_BASIS,
        details={"seed": inputs.seed},
    )


PHASE_SURROGATES = make_spec(
    "resampling.phase_surrogates",
    question="Does the drop need more than the return spectrum, which random-phase copies keep?",
    needs=("stored_equity",),
    params=(N_PATHS,),
    outputs=DROP_OUTPUTS,
    reading=DROP_READING.replace("{what}", "Random-phase copies of the log returns"),
    caveats=(
        "The copies keep the average, the spread and the correlation at every gap but remove"
        " fat tails and clustered shocks. A gap between them and the run says the run depends"
        " on those features, not which one. " + PAST,
    ),
    reference="test_known_answer_phase",
    compute=phase_surrogate,
    situations=("drawdown", "looks-too-good"),
    seeded=True,
)

CHECKS = (RETURN_SHUFFLE, PHASE_SURROGATES)
