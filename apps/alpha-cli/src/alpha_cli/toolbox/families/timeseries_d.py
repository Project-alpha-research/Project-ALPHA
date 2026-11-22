"""Trend, reversion, memory and streaks in returns: variance ratio, Hurst exponent, runs."""

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


def variance_ratio_z(r: FloatArray, q: int) -> tuple[float, float]:
    import numpy as np

    from alpha_patterns.cycles import variance_ratio

    log_prices = np.r_[0.0, np.cumsum(np.log1p(r))]
    out = variance_ratio(log_prices, q=q)
    return out.ratio, out.z_score


def _variance_ratio(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    from scipy.stats import norm

    keys, q = ("horizon", "ratio", "z", "p_value"), params["q"]
    r = inputs.stored.scored_returns()
    if r.size < max(30, 4 * q):
        return too_little(keys, max(30, 4 * q), r.size)
    if flat(r):
        return unavailable(keys, FLAT, r.size)
    ratio, z = variance_ratio_z(r, q)
    p = 2.0 * float(norm.sf(abs(z))) if z == z else None
    return finished({"horizon": q, "ratio": ratio, "z": z, "p_value": p}, "Undefined.")


def hurst_reading(r: FloatArray, trials: int, seed: int) -> dict[str, float]:
    """Rescaled-range Hurst exponent of the returns against its white-noise spread (Hurst 1951)."""
    from alpha_patterns.cycles import hurst_exponent, hurst_random_walk_reference

    h = hurst_exponent(r)
    mean, sd = hurst_random_walk_reference(len(r), trials=trials, seed=seed)
    return {"hurst": h, "null_mean": mean, "null_sd": sd, "z": (h - mean) / sd}


def _hurst(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = ("hurst", "null_mean", "null_sd", "z")
    r = inputs.stored.scored_returns()
    if r.size < 64:
        return too_little(keys, 64, r.size)
    if flat(r):
        return unavailable(keys, FLAT, r.size)
    assert rng is not None
    seed = int(rng.integers(2**31 - 1))
    result = finished(hurst_reading(r, params["trials"], seed), "Undefined.")
    result.details.update(seed=seed)
    return result


def runs_reading(r: FloatArray) -> dict[str, float] | None:
    """Wald-Wolfowitz (1940) runs test on the signs of the returns (zeros break a run)."""
    from alpha_validation.trade_dependence import trade_runs_test

    test = trade_runs_test(r)
    if test is None:
        return None
    return {
        "runs": test.n_runs,
        "expected": test.expected_runs,
        "z": test.z,
        "p_value": test.p_value,
    }


def _runs(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = ("runs", "expected", "z", "p_value")
    r = inputs.stored.scored_returns()
    if r.size < 10:
        return too_little(keys, 10, r.size)
    got = runs_reading(r)
    if got is None:
        return unavailable(keys, "Needs both up and down bars among the returns.", r.size)
    return finished(got, "Undefined.")


def _out(key: str, label: str, gloss: str, unit: Any = "ratio") -> Output:
    return Output(key, label, gloss, unit)


CHECKS = (
    make(
        "variance_ratio",
        "Do returns trend or reverse over several bars?",
        (Param("q", int, 5, range(2, 61), "Horizon in bars."),),
        (
            _out("horizon", "Horizon", "Days per step of the comparison.", "count"),
            _out(
                "ratio",
                "Variance ratio",
                "Variance of q-bar moves over q times the one-bar variance.",
            ),
            _out("z", "Robust z-score", "Lo-MacKinlay z-score, robust to changing volatility."),
            _out(
                "p_value",
                "p-value",
                "Two-sided chance of a z-score this far from 0 under a random walk.",
                "p_value",
            ),
        ),
        "Over {horizon:.0f} bars the variance ratio is {ratio:.3f} (z {z:+.2f}, p-value"
        " {p_value:.3f}). A random walk gives a ratio of one. Above one means moves tended to"
        " continue; below one means they tended to reverse."
        " A large p-value means the gap from one could be chance.",
        "Lo & MacKinlay (1988). The ratio compares overlapping q-bar moves; it does not say why"
        " returns trend or reverse, and one horizon is one look.",
        _variance_ratio,
        "test_known_variance_ratio",
        situations=("trade-streaks",),
        test=True,
    ),
    make(
        "hurst",
        "Do returns trend, wander or reverse over long spans?",
        (
            Param(
                "trials", int, 100, range(20, 1001), "White-noise series used for the comparison."
            ),
        ),
        (
            _out(
                "hurst",
                "Hurst exponent",
                "Rescaled-range exponent of the returns; 0.5 means no memory.",
            ),
            _out(
                "null_mean",
                "White-noise average",
                "Average exponent of white noise of the same length.",
            ),
            _out("null_sd", "White-noise spread", "Standard deviation of that exponent."),
            _out(
                "z",
                "Distance in spreads",
                "How many white-noise spreads the exponent lies from its average.",
            ),
        ),
        "The Hurst exponent of the returns is {hurst:.3f}. White noise of the same length gives"
        " {null_mean:.3f} with a spread of {null_sd:.3f}, so the run sits {z:+.1f} spreads away."
        " Above that means moves tended to persist; below means they tended to reverse.",
        "The estimator is biased on short series, so compare with the white-noise average, not 0.5."
        " Hurst (1951). The white-noise draws use the run's seed.",
        _hurst,
        "test_known_hurst_matches_library",
        situations=("behaviour-change",),
        seeded=True,
    ),
    make(
        "up_down_runs",
        "Do up bars and down bars come in random order?",
        (),
        (
            _out("runs", "Streaks", "Number of unbroken streaks of up or down bars.", "count"),
            _out(
                "expected",
                "Expected streaks",
                "Streaks expected if the same up and down bars came in random order.",
                "count",
            ),
            _out("z", "Runs z-score", "Negative means bunching, positive means alternation."),
            _out(
                "p_value",
                "p-value",
                "Two-sided chance of a gap this large if the order were random.",
                "p_value",
            ),
        ),
        "Up and down bars formed {runs:.0f} streaks; random order would give about {expected:.1f}"
        " (p-value {p_value:.3f}). Fewer streaks than expected means bars of one direction"
        " bunched.",
        "Wald & Wolfowitz (1940). It looks at direction only, not size, and a flat bar breaks"
        " a streak.",
        _runs,
        "test_known_runs_hand_case",
        situations=("trade-streaks",),
        test=True,
    ),
)
