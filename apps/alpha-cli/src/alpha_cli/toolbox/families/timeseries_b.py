"""Shape of the return distribution and its memory: volatility clustering, normality, scaling."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Param, Result
from alpha_cli.toolbox.families.timeseries_common import (
    finished,
    flat,
    make,
    too_little,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray

FLAT = "The scored returns do not vary."
SHAPIRO_LIMIT = 5000


def arch_lm(r: FloatArray, lags: int) -> tuple[float, float]:
    """Engle (1982) LM test: n_eff * R^2 of squared returns on their own lags, chi-squared."""
    import numpy as np
    from scipy.stats import chi2

    sq = (r - r.mean()) ** 2
    y = sq[lags:]
    x = np.column_stack(
        [np.ones(len(y))] + [sq[lags - k : len(sq) - k] for k in range(1, lags + 1)]
    )
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    total = float(((y - y.mean()) ** 2).sum())
    lm = len(y) * (1.0 - float(resid @ resid) / total)
    return lm, float(chi2.sf(lm, lags))


def _arch(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys, lags = ("lags", "lm", "p_value"), params["lags"]
    r = inputs.stored.scored_returns()
    if r.size < max(30, 5 * lags):
        return too_little(keys, max(30, 5 * lags), r.size)
    if flat(r):
        return unavailable(keys, FLAT, r.size)
    squares = (r - r.mean()) ** 2
    if flat(squares[lags:]):
        return unavailable(
            keys, "The squared returns do not vary, so there is nothing to regress.", r.size
        )
    lm, p = arch_lm(r, lags)
    return finished({"lags": lags, "lm": lm, "p_value": p}, "Undefined.")


def normality_reading(r: FloatArray) -> dict[str, float | None]:
    """Skew, excess kurtosis, Jarque-Bera (1980) and Shapiro-Wilk (1965; up to 5,000 returns)."""
    from scipy import stats

    jb = stats.jarque_bera(r)
    shapiro = float(stats.shapiro(r).pvalue) if r.size <= SHAPIRO_LIMIT else None
    return {
        "skew": float(stats.skew(r)),
        "excess_kurtosis": float(stats.kurtosis(r)),
        "jarque_bera": float(jb.statistic),
        "jb_p_value": float(jb.pvalue),
        "shapiro_p_value": shapiro,
    }


def _normality(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = ("skew", "excess_kurtosis", "jarque_bera", "jb_p_value", "shapiro_p_value")
    r = inputs.stored.scored_returns()
    if r.size < 20:
        return too_little(keys, 20, r.size)
    if flat(r):
        return unavailable(keys, FLAT, r.size)
    values = normality_reading(r)
    why = f"Shapiro-Wilk is read up to {SHAPIRO_LIMIT} returns; this run has {r.size}."
    return finished(values, why)


def fluctuation(r: FloatArray, size: int) -> float:
    """Root-mean-square residual of the return profile after a line fit in each box (Peng 1994)."""
    import numpy as np

    profile = np.cumsum(r - r.mean())
    boxes = len(profile) // size
    y = profile[: boxes * size].reshape(boxes, size)
    t = np.arange(size) - (size - 1) / 2
    slope = (y * t).sum(axis=1) / float(t @ t)
    resid = y - y.mean(axis=1, keepdims=True) - slope[:, None] * t
    return float(np.sqrt(np.mean(resid**2)))


def dfa_exponent(r: FloatArray) -> float | None:
    """Slope of log fluctuation against log box size; None when a fluctuation is zero."""
    import numpy as np

    sizes = np.unique(np.round(np.geomspace(4, len(r) // 4, 12)).astype(int))
    values = np.array([fluctuation(r, int(s)) for s in sizes])
    if len(sizes) < 3 or not np.all(values > 0):
        return None
    return float(np.polyfit(np.log(sizes), np.log(values), 1)[0])


def _dfa(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = ("alpha",)
    r = inputs.stored.scored_returns()
    if r.size < 100:
        return too_little(keys, 100, r.size)
    alpha = dfa_exponent(r)
    return finished({"alpha": alpha}, "A box size had no fluctuation to measure.")


def gph(r: FloatArray, power: float) -> tuple[float, float]:
    """Geweke & Porter-Hudak (1983) log-periodogram estimate of d and its standard error."""
    import numpy as np

    n = len(r)
    m = int(n**power)
    freq = 2.0 * np.pi * np.arange(1, m + 1) / n
    periodogram = np.abs(np.fft.rfft(r - r.mean())[1 : m + 1]) ** 2 / (2.0 * np.pi * n)
    x = np.log(4.0 * np.sin(freq / 2.0) ** 2)
    slope = float(np.polyfit(x, np.log(periodogram), 1)[0])
    return -slope, float(np.pi / np.sqrt(6.0 * np.sum((x - x.mean()) ** 2)))


def _gph(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = ("d", "std_error", "z")
    r = inputs.stored.scored_returns()
    if r.size < 100:
        return too_little(keys, 100, r.size)
    if flat(r):
        return unavailable(keys, FLAT, r.size)
    d, se = gph(r, params["power"])
    return finished({"d": d, "std_error": se, "z": d / se}, "Undefined.")


def _out(key: str, label: str, gloss: str, unit: Any = "ratio") -> Output:
    return Output(key, label, gloss, unit)


CHECKS = (
    make(
        "arch_lm",
        "Do large moves cluster in time?",
        (Param("lags", int, 5, range(1, 31), "Number of bars back to include."),),
        (
            _out("lags", "Days back", "Number of lags in the test.", "count"),
            _out(
                "lm",
                "ARCH-LM statistic",
                "Observations times the R-squared of squared returns on their own lags.",
            ),
            _out(
                "p_value",
                "p-value",
                "Chance of a statistic this large if volatility did not cluster.",
                "p_value",
            ),
        ),
        "The ARCH-LM statistic over {lags:.0f} bars back is {lm:.1f} (p-value {p_value:.3f})."
        " A small p-value means big moves tended to follow big moves; a large one means this test"
        " found no clear clustering.",
        "Engle (1982). It detects clustering of the size of moves, not their direction,"
        " and heavy tails alone can inflate it.",
        _arch,
        "test_known_arch_lm",
        situations=("calm-or-turbulent",),
        test=True,
    ),
    make(
        "normality",
        "Do returns look like a bell curve?",
        (),
        (
            _out("skew", "Skewness", "Negative means a longer tail of losses; 0 for a bell curve."),
            _out(
                "excess_kurtosis",
                "Excess kurtosis",
                "Positive means fatter tails than a bell curve; 0 for a bell curve.",
            ),
            _out("jarque_bera", "Jarque-Bera statistic", "Combines skewness and kurtosis."),
            _out(
                "jb_p_value",
                "Jarque-Bera p-value",
                "Chance of a statistic this large from a bell curve.",
                "p_value",
            ),
            _out(
                "shapiro_p_value",
                "Shapiro-Wilk p-value",
                "Chance of a fit this poor from a bell curve (up to 5,000 returns).",
                "p_value",
            ),
        ),
        "Skewness is {skew:+.2f} and excess kurtosis is {excess_kurtosis:+.2f}; both are zero for a"
        " bell curve. The Jarque-Bera p-value is {jb_p_value:.3f}: a small value means the returns"
        " differ from a bell curve.",
        "Jarque & Bera (1980); Shapiro & Wilk (1965). With many bars, tiny departures give small"
        " p-values. It says the shape differs, not whether that matters for the rule.",
        _normality,
        "test_known_normality",
        situations=(
            "drawdown",
            "return-range",
        ),
        test=True,
    ),
    make(
        "dfa",
        "Do returns remember their own past over long spans, even through trends?",
        (),
        (
            _out(
                "alpha",
                "Scaling exponent",
                "Detrended fluctuation exponent: 0.5 no memory, above 0.5 persistence.",
            ),
        ),
        "The detrended fluctuation exponent is {alpha:.3f}. About one half means no long"
        " memory; above one half means moves tended to persist over long spans; below means"
        " they tended to reverse.",
        "Peng et al. (1994). The exponent is read from box sizes 4 to a quarter of the history and"
        " has no p-value here; short runs move it by a few hundredths.",
        _dfa,
        "test_known_dfa",
        situations=("behaviour-change",),
    ),
    make(
        "long_memory",
        "Is there fractional long memory in returns?",
        (
            Param(
                "power",
                float,
                0.5,
                (0.4, 0.5, 0.6),
                "Share of the low frequencies used, as a power of the history length.",
            ),
        ),
        (
            _out("d", "Memory order d", "Fractional integration order: 0 no long memory."),
            _out("std_error", "Standard error", "Standard error of d from the regression."),
            _out("z", "z-score", "d divided by its standard error."),
        ),
        "The long-memory order d is {d:+.3f} with a standard error of {std_error:.3f} (z {z:+.1f})."
        " About zero means no long memory; positive means shocks faded slowly; negative means"
        " they reversed.",
        "Geweke & Porter-Hudak (1983). The estimate is noisy on a few hundred bars and changes"
        " with the share of frequencies used.",
        _gph,
        "test_known_long_memory",
        situations=("behaviour-change",),
    ),
)
