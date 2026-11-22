"""Tests for a break in the mean or the variance of the scored returns (Chow, CUSUM)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result
from alpha_cli.toolbox.families.regimes_base import (
    BASIS,
    MIN_BARS,
    MIN_GROUP,
    dated_returns,
    spec,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray

CHOW_KEYS = (
    "first_mean",
    "second_mean",
    "f_stat",
    "p_value",
    "break_date",
    "first_bars",
    "second_bars",
)


def chow(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    """Chow (1960) F test for a shift in the mean at a known date (one parameter, k = 1)."""
    from scipy import stats

    dates, returns = dated_returns(inputs)
    if returns.size < MIN_BARS:
        return unavailable(
            CHOW_KEYS, f"Needs at least {MIN_BARS} scored bars; found {returns.size}."
        )
    text = params["break_date"]
    if text:
        when = datetime.fromisoformat(text)
        when = when if when.tzinfo else when.replace(tzinfo=UTC)
        cut = sum(ts < when for ts in dates)
    else:
        cut = returns.size // 2
    first, second = returns[:cut], returns[cut:]
    if first.size < MIN_GROUP or second.size < MIN_GROUP:
        return unavailable(
            CHOW_KEYS,
            f"Needs at least {MIN_GROUP} bars on each side of the date; found {first.size} before"
            f" and {second.size} after.",
        )
    split = float(((first - first.mean()) ** 2).sum() + ((second - second.mean()) ** 2).sum())
    if split <= 0:
        return unavailable(CHOW_KEYS, "Returns do not vary within either side, so no test applies.")
    pooled = float(((returns - returns.mean()) ** 2).sum())
    f_stat = (pooled - split) / (split / (returns.size - 2))
    return Result(
        {
            "first_mean": float(first.mean()),
            "second_mean": float(second.mean()),
            "f_stat": float(f_stat),
            "p_value": float(stats.f.sf(f_stat, 1, returns.size - 2)),
            "break_date": dates[cut].date().isoformat(),
            "first_bars": int(first.size),
            "second_bars": int(second.size),
        },
        {},
        basis=BASIS,
    )


CHOW = spec(
    "regimes.chow_test",
    "Did the average return change at a date I chose?",
    ("stored_equity",),
    (
        Output(
            "first_mean",
            "Mean bar return before",
            "Average return per bar before the date.",
            "fraction",
        ),
        Output(
            "second_mean",
            "Mean bar return after",
            "Average return per bar from the date on.",
            "fraction",
        ),
        Output(
            "f_stat",
            "F statistic",
            "Chow F statistic for equal means before and after the date.",
            "ratio",
        ),
        Output(
            "p_value",
            "Two-sided p-value",
            "Chance of a change this large if the mean never changed (F distribution).",
            "p_value",
        ),
        Output("break_date", "Date used", "First date of the second part.", "date"),
        Output("first_bars", "Bars before", "Number of bars before the date.", "count"),
        Output("second_bars", "Bars after", "Number of bars from the date on.", "count"),
    ),
    "The mean bar return was {first_mean:.4%} before {break_date} and {second_mean:.4%} after"
    " (Chow F {f_stat:.2f}, p-value {p_value:.3f}).",
    "The test assumes the date was named before looking at the returns, and equal variance and"
    " independent bars (Chow 1960). A date picked after seeing a gap makes the p-value too small."
    " Leave the date empty to cut at the middle bar.",
    "test_chow_known_answer",
    chow,
    params=(
        Param(
            "break_date",
            str,
            "",
            None,
            "First date of the second part, as YYYY-MM-DD; empty means the middle bar.",
        ),
    ),
    kind="test",
)

CUSUM_BOUND = 0.948  # Brown, Durbin and Evans (1975), table of a for a five percent level.
MEAN_KEYS = ("peak_ratio", "peak_date", "bars")


def recursive_residuals(returns: FloatArray) -> FloatArray:
    """Brown-Durbin-Evans (1975) recursive residuals of a constant-mean model, r = 2..n."""
    import numpy as np

    count = np.arange(1, returns.size)  # bars already seen before each new bar
    prior_mean = np.cumsum(returns)[:-1] / count
    return (returns[1:] - prior_mean) / np.sqrt(1 + 1 / count)


def cusum_mean(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    dates, returns = dated_returns(inputs)
    if returns.size < MIN_BARS:
        return unavailable(
            MEAN_KEYS, f"Needs at least {MIN_BARS} scored bars; found {returns.size}."
        )
    w = recursive_residuals(returns)
    sigma = float(np.sqrt((w**2).sum() / w.size))
    if sigma <= 0:
        return unavailable(MEAN_KEYS, "Returns do not vary, so no test applies.")
    total = np.cumsum(w) / sigma
    steps = np.arange(1, w.size + 1)
    root = np.sqrt(w.size)
    bound = CUSUM_BOUND * (root + 2 * steps / root)
    ratio = np.abs(total) / bound
    peak = int(ratio.argmax())
    return Result(
        {
            "peak_ratio": float(ratio[peak]),
            "peak_date": dates[peak + 1].date().isoformat(),
            "bars": int(returns.size),
        },
        {},
        details={"bound_level": CUSUM_BOUND},
        basis=BASIS,
    )


CUSUM_MEAN = spec(
    "regimes.cusum_mean",
    "Has the average return drifted over the history?",
    ("stored_equity",),
    (
        Output(
            "peak_ratio",
            "Peak against line",
            "Largest cumulative surprise divided by the boundary line at that bar.",
            "ratio",
        ),
        Output(
            "peak_date", "Date of the peak", "Date of the bar where the ratio was largest.", "date"
        ),
        Output("bars", "Bars", "Number of scored bars.", "count"),
    ),
    "The running sum of return surprises peaked at {peak_ratio:.2f} times the standard"
    " boundary line, on {peak_date}; a peak above the line is a drift in the mean that steady"
    " returns rarely produce.",
    "This is the CUSUM test of Brown, Durbin and Evans (1975) on a constant-mean model. It reports"
    " where the sum came closest to the line, not a p-value. It finds slow drifts better than"
    " one sudden jump, and it assumes independent returns.",
    "test_cusum_mean_known_answer",
    cusum_mean,
    kind="test",
)

SQUARES_KEYS = ("max_gap", "gap_date", "p_value", "bars")


def cusum_variance(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np
    from scipy import stats

    dates, returns = dated_returns(inputs)
    if returns.size < MIN_BARS:
        return unavailable(
            SQUARES_KEYS, f"Needs at least {MIN_BARS} scored bars; found {returns.size}."
        )
    squares = recursive_residuals(returns) ** 2
    if squares.sum() <= 0:
        return unavailable(SQUARES_KEYS, "Returns do not vary, so no test applies.")
    running = np.cumsum(squares) / squares.sum()
    gap = np.abs(running - np.arange(1, squares.size + 1) / squares.size)
    peak = int(gap.argmax())
    scaled = float(gap[peak] * np.sqrt(squares.size / 2))
    return Result(
        {
            "max_gap": float(gap[peak]),
            "gap_date": dates[peak + 1].date().isoformat(),
            "p_value": float(stats.kstwobign.sf(scaled)),
            "bars": int(returns.size),
        },
        {},
        basis=BASIS,
    )


CUSUM_VARIANCE = spec(
    "regimes.cusum_variance",
    "Has the size of the return swings changed over the history?",
    ("stored_equity",),
    (
        Output(
            "max_gap",
            "Largest gap",
            "Largest gap between the running share of squared surprises and an even share.",
            "fraction",
        ),
        Output("gap_date", "Date of the gap", "Date of the bar where the gap was largest.", "date"),
        Output(
            "p_value",
            "Approximate p-value",
            "Chance of a gap this large if volatility never changed (Kolmogorov approximation).",
            "p_value",
        ),
        Output("bars", "Bars", "Number of scored bars.", "count"),
    ),
    "The running share of squared return surprises strayed {max_gap:.1%} from an even pace, most on"
    " {gap_date} (approximate p-value {p_value:.3f}).",
    "This is the CUSUM-of-squares test of Brown, Durbin and Evans (1975) on a constant-mean model."
    " The p-value uses the large-sample Kolmogorov law, so it is rough on short histories, and"
    " fat tails push it too low.",
    "test_cusum_variance_known_answer",
    cusum_variance,
    kind="test",
)
