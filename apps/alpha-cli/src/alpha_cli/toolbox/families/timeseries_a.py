"""Serial dependence of returns: autocorrelation, trend or reversion, memory and streaks."""

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


def autocorrelations(r: FloatArray, max_lag: int) -> FloatArray:
    """Sample autocorrelations at lags 1..max_lag (Box & Jenkins; full-sample variance)."""
    import numpy as np

    d = r - r.mean()
    total = float(d @ d)
    return np.array([float(d[k:] @ d[:-k]) / total for k in range(1, max_lag + 1)])


def partial_autocorrelations(acf: FloatArray) -> FloatArray:
    """Partial autocorrelations from autocorrelations by the Durbin-Levinson recursion."""
    import numpy as np

    out = np.empty(len(acf))
    phi = np.empty(0)
    for k in range(1, len(acf) + 1):
        num = acf[k - 1] - float(phi @ acf[: k - 1][::-1])
        den = 1.0 - float(phi @ acf[: k - 1])
        last = num / den
        phi = np.r_[phi - last * phi[::-1], last]
        out[k - 1] = last
    return out


def ljung_box(r: FloatArray, lags: int) -> tuple[float, float]:
    """Q = n(n+2) sum rho_k^2 / (n-k), chi-squared on ``lags`` (Ljung & Box 1978, eq. 2)."""
    import numpy as np
    from scipy.stats import chi2

    n = len(r)
    rho = autocorrelations(r, lags)
    q = float(n * (n + 2) * np.sum(rho**2 / (n - np.arange(1, lags + 1))))
    return q, float(chi2.sf(q, lags))


def _ljung(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys, lags = ("lags", "q", "p_value"), params["lags"]
    r = inputs.stored.scored_returns()
    if r.size < max(30, 3 * lags):
        return too_little(keys, max(30, 3 * lags), r.size)
    if flat(r):
        return unavailable(keys, FLAT, r.size)
    q, p = ljung_box(r, lags)
    return finished({"lags": lags, "q": q, "p_value": p}, "Undefined.")


def _acf(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    keys = ("lag1", "band", "peak_lag", "peak_acf", "peak_pacf_lag", "peak_pacf", "outside")
    lags = params["max_lag"]
    r = inputs.stored.scored_returns()
    if r.size < max(30, 3 * lags):
        return too_little(keys, max(30, 3 * lags), r.size)
    if flat(r):
        return unavailable(keys, FLAT, r.size)
    acf = autocorrelations(r, lags)
    pacf = partial_autocorrelations(acf)
    band = 1.96 / float(np.sqrt(r.size))
    peak, ppeak = int(np.argmax(np.abs(acf))), int(np.argmax(np.abs(pacf)))
    result = finished(
        {
            "lag1": acf[0],
            "band": band,
            "peak_lag": peak + 1,
            "peak_acf": acf[peak],
            "peak_pacf_lag": ppeak + 1,
            "peak_pacf": pacf[ppeak],
            "outside": int(np.sum(np.abs(acf) > band)),
        },
        "Undefined.",
    )
    return Result(
        result.values,
        result.reasons,
        series={
            "lag": list(range(1, lags + 1)),
            "acf": [float(v) for v in acf],
            "pacf": [float(v) for v in pacf],
        },
        basis=result.basis,
    )


def _out(key: str, label: str, gloss: str, unit: Any = "ratio") -> Output:
    return Output(key, label, gloss, unit)


CHECKS = (
    make(
        "ljung_box",
        "Are returns on nearby bars linked to each other?",
        (Param("lags", int, 10, range(1, 61), "Number of bars back to include."),),
        (
            _out("lags", "Days back", "Number of lags in the test.", "count"),
            _out("q", "Ljung-Box statistic", "Weighted sum of squared autocorrelations."),
            _out(
                "p_value",
                "p-value",
                "Chance of a statistic this large from unlinked returns.",
                "p_value",
            ),
        ),
        "Over {lags:.0f} bars back the Ljung-Box statistic is {q:.1f} (p-value {p_value:.3f}). A"
        " small p-value means returns on nearby bars moved together more than chance alone"
        " usually gives; a large one means this test found no clear link.",
        "It measures linear links only, in any direction and size, and says nothing about whether"
        " they could be traded. The p-value assumes steady volatility; volatility clusters make it"
        " too small.",
        _ljung,
        "test_known_ljung_box",
        situations=("trade-streaks",),
        test=True,
    ),
    make(
        "autocorrelation",
        "At which lags are returns correlated with their own past?",
        (Param("max_lag", int, 10, range(1, 41), "Longest lag to show, in bars."),),
        (
            _out(
                "lag1",
                "Lag-1 autocorrelation",
                "Correlation of a bar's return with the bar before.",
            ),
            _out(
                "band",
                "Noise band",
                "About 95% of values from unlinked returns lie within plus or minus this.",
            ),
            _out(
                "peak_lag",
                "Strongest lag",
                "Lag with the largest absolute autocorrelation.",
                "count",
            ),
            _out("peak_acf", "Strongest autocorrelation", "Autocorrelation at that lag."),
            _out(
                "peak_pacf_lag",
                "Strongest partial lag",
                "Lag with the largest absolute partial autocorrelation.",
                "count",
            ),
            _out(
                "peak_pacf",
                "Strongest partial autocorrelation",
                "Partial autocorrelation at that lag.",
            ),
            _out(
                "outside",
                "Lags outside the band",
                "Count of lags whose autocorrelation lies outside the noise band.",
                "count",
            ),
        ),
        "The bar-to-bar (lag-1) autocorrelation is {lag1:+.3f}. The strongest lag is"
        " {peak_lag:.0f} at {peak_acf:+.3f}; the noise band is about plus or minus {band:.3f}."
        " {outside:.0f} lags lie outside it. The strongest partial lag is {peak_pacf_lag:.0f}"
        " at {peak_pacf:+.3f}.",
        "Lags outside the band are not proof of a pattern; one in twenty is expected by chance."
        " The partial autocorrelation removes the effect of shorter lags.",
        _acf,
        "test_known_autocorrelation",
        situations=("trade-streaks",),
    ),
)
