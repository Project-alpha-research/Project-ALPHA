"""Side-by-side checks of ALPHA's hand-written statistics against statsmodels and arch.

The decision each check supports (the reasons are in
docs/reference/project/components/validation-and-evidence.md):

- **Swapped, bit for bit.** Holm adjusted p-values now come from
  ``statsmodels.stats.multitest.multipletests``. The values the hand-written loop produced are
  frozen here (literals, an in-test copy of the old loop, and a digest over seeded families), so
  the swap is pinned: any change in a single bit of any adjusted p-value fails.
- **Kept: last-digit differences.** Benjamini-Hochberg q-values, Wilson and Newcombe intervals
  agree with statsmodels to ``LAST_DIGIT_ABS`` but not bit for bit (a different order of the same
  arithmetic). Those numbers are stored and compared against thresholds, so ALPHA's own bits are
  frozen here and the library is only compared within tolerance.
- **Kept: different by definition or by random draws.** Required sample size, simulated power,
  the stationary bootstrap, BCa intervals, risk of ruin, White's Reality Check and Hansen's SPA.
  The library is compared within a stated Monte Carlo tolerance, or the difference is pinned.

Tolerances. ``LAST_DIGIT_ABS = 1e-15`` is about four units in the last place of a float64 near 1;
the largest difference seen over 16,370 Wilson, 20,000 Newcombe and 1,636 Benjamini-Hochberg
cases was 4.4e-16. Monte Carlo comparisons use ``MC_SIGMAS = 4.5`` standard errors of the
difference of two independent estimates (a false alarm about once in 150,000 draws; the seeds are
fixed, so a pass is repeatable).

Sources: Holm (1979), Scand. J. Statist. 6:65-70; Benjamini & Hochberg (1995), JRSS-B 57:289-300;
Wilson (1927), JASA 22:209-212; Newcombe (1998), Statist. Med. 17:873-890, method 10; Politis &
Romano (1994), JASA 89:1303-1313; Efron (1987), JASA 82:171-185; White (2000), Econometrica
68:1097-1126; Hansen (2005), JBES 23:365-380.
"""

from __future__ import annotations

import gc
import hashlib
import math
from collections.abc import Iterator

import numpy as np
import pytest
from arch.bootstrap import SPA, StationaryBootstrap
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.power import (
    normal_power_het,
    normal_sample_size_one_tail,
)
from statsmodels.stats.proportion import (
    confint_proportions_2indep,
    proportion_confint,
)

from alpha_research import (
    FrozenSecondaryFamily,
    SecondaryHypothesis,
    holm_adjust_secondary_family,
    required_observations_known_sigma,
    simulate_prospective_power_known_sigma,
)
from alpha_validation import (
    benjamini_hochberg,
    block_bootstrap_ci,
    newcombe_diff_interval,
    reality_check,
    risk_of_ruin,
    spa_test,
    stationary_bootstrap_indices,
    wilson_interval,
)

LAST_DIGIT_ABS = 1e-15
MC_SIGMAS = 4.5
ALPHAS = (0.01, 0.05, 0.10, 0.25)


@pytest.fixture(autouse=True, scope="module")
def _cheap_garbage_collection() -> Iterator[None]:
    """statsmodels' Holm branch runs a full ``gc.collect()`` on every call.

    In a large test process that is 0.1 to 0.7 seconds a call. Freezing the objects that
    already exist makes those collections cheap for this module; it changes no number.
    """
    gc.freeze()
    yield
    gc.unfreeze()


def _hex_digest(values: Iterator[float] | list[float]) -> str:
    return hashlib.sha256("|".join(float(v).hex() for v in values).encode("ascii")).hexdigest()


def _pvalue_families() -> list[list[float]]:
    """Edge cases plus seeded families: ties, n=1, all equal, exact 0 and 1, tiny and long."""
    families: list[list[float]] = [
        [0.5],
        [0.0],
        [1.0],
        [0.0, 1.0],
        [0.03] * 7,
        [0.0] * 4,
        [1.0] * 4,
        [0.01, 0.01, 0.02, 0.02, 0.5],
        [0.01, 0.04, 0.03],
        [0.2, 0.01, 0.01],
        [1e-300, 5e-324, 0.9999999999999999, 0.05],
    ]
    rng = np.random.default_rng(20261115)
    for i in range(60):
        p = rng.random(int(rng.integers(1, 60)))
        if i % 3 == 0:
            p = np.round(p, 2)  # many ties
        if i % 5 == 0:
            # Crowd near zero. Python's scalar pow, not numpy's: numpy's vectorised power differs in
            # the last digit on AVX-512 machines, which would change the frozen corpus digests.
            p = np.array([float(v) ** 6 for v in p])
        if i % 7 == 0:
            p[int(rng.integers(0, p.size))] = 0.0
        if i % 11 == 0:
            p[int(rng.integers(0, p.size))] = 1.0
        families.append([float(v) for v in p])
    families.append([float(v) for v in rng.random(2000)])  # long family
    return families


def _family(pvalues: list[float], alpha: float) -> FrozenSecondaryFamily:
    return FrozenSecondaryFamily(
        family_id="parity",
        alpha=alpha,
        hypotheses=tuple(SecondaryHypothesis(f"h{i:04d}", p) for i, p in enumerate(pvalues)),
    )


# --- Holm: swapped to statsmodels, pinned to the hand-written values -------------------------


def _holm_hand_written(pvalues: list[float]) -> list[float]:
    """The loop ``holm_adjust_secondary_family`` ran before the swap, kept as the reference."""
    count = len(pvalues)
    order = sorted(range(count), key=lambda i: (pvalues[i], f"h{i:04d}"))
    adjusted = [0.0] * count
    prior = 0.0
    for rank, index in enumerate(order):
        prior = max(prior, min(1.0, (count - rank) * pvalues[index]))
        adjusted[index] = prior
    return adjusted


# sha256 over the hex form of every adjusted p-value the hand-written loop produced for
# ``_pvalue_families()``, recorded before the swap.
HOLM_FROZEN_DIGEST = "eb422f787a81b4132a7f12f792315c6dbb8f8b18e4c4a4a45da8df474e3a9eec"
HOLM_FROZEN_CASES: list[tuple[list[float], list[str]]] = [
    ([0.5], ["0x1.0000000000000p-1"]),
    ([0.0], ["0x0.0p+0"]),
    ([1.0], ["0x1.0000000000000p+0"]),
    ([0.0, 1.0], ["0x0.0p+0", "0x1.0000000000000p+0"]),
    (
        [0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03],
        [
            "0x1.ae147ae147ae1p-3",
            "0x1.ae147ae147ae1p-3",
            "0x1.ae147ae147ae1p-3",
            "0x1.ae147ae147ae1p-3",
            "0x1.ae147ae147ae1p-3",
            "0x1.ae147ae147ae1p-3",
            "0x1.ae147ae147ae1p-3",
        ],
    ),
    ([0.0, 0.0, 0.0, 0.0], ["0x0.0p+0", "0x0.0p+0", "0x0.0p+0", "0x0.0p+0"]),
    (
        [1.0, 1.0, 1.0, 1.0],
        [
            "0x1.0000000000000p+0",
            "0x1.0000000000000p+0",
            "0x1.0000000000000p+0",
            "0x1.0000000000000p+0",
        ],
    ),
    (
        [0.01, 0.01, 0.02, 0.02, 0.5],
        [
            "0x1.999999999999ap-5",
            "0x1.999999999999ap-5",
            "0x1.eb851eb851eb8p-5",
            "0x1.eb851eb851eb8p-5",
            "0x1.0000000000000p-1",
        ],
    ),
    ([0.01, 0.04, 0.03], ["0x1.eb851eb851eb8p-6", "0x1.eb851eb851eb8p-5", "0x1.eb851eb851eb8p-5"]),
    ([0.2, 0.01, 0.01], ["0x1.999999999999ap-3", "0x1.eb851eb851eb8p-6", "0x1.eb851eb851eb8p-6"]),
    (
        [1e-300, 5e-324, 0.9999999999999999, 0.05],
        [
            "0x1.01297d23ab683p-995",
            "0x0.0000000000004p-1022",
            "0x1.fffffffffffffp-1",
            "0x1.999999999999ap-4",
        ],
    ),
    (
        [
            0.0010737418240000002,
            0.04218053364099999,
            1.0,
            0.11764899999999996,
            0.003518743761000001,
            0.005489031743999999,
        ],
        [
            "0x1.a636641c4df1bp-8",
            "0x1.03283e2c61d45p-3",
            "0x1.0000000000000p+0",
            "0x1.e1e3eaf6837f5p-3",
            "0x1.204167b87acd4p-6",
            "0x1.67baabd3c2738p-6",
        ],
    ),
    ([0.6796255658723898], ["0x1.5bf7e1d5e512ap-1"]),
]


def test_holm_matches_the_frozen_hand_written_values_bit_for_bit() -> None:
    adjusted_all: list[float] = []
    for index, pvalues in enumerate(_pvalue_families()):
        expected = _holm_hand_written(pvalues)
        alpha = ALPHAS[index % len(ALPHAS)]
        result = holm_adjust_secondary_family(_family(pvalues, alpha))
        got = [item.adjusted_p_value for item in result]
        assert [g.hex() for g in got] == [e.hex() for e in expected]
        assert [item.rejected for item in result] == [e <= alpha for e in expected]
        assert [item.p_value for item in result] == pvalues
        assert [item.hypothesis_id for item in result] == [f"h{i:04d}" for i in range(len(got))]
        adjusted_all.extend(got)
    assert _hex_digest(adjusted_all) == HOLM_FROZEN_DIGEST


@pytest.mark.parametrize(("pvalues", "expected_hex"), HOLM_FROZEN_CASES)
def test_holm_frozen_literal_cases(pvalues: list[float], expected_hex: list[str]) -> None:
    result = holm_adjust_secondary_family(_family(pvalues, 0.05))
    assert [item.adjusted_p_value.hex() for item in result] == expected_hex
    assert [type(item.adjusted_p_value) for item in result] == [float] * len(pvalues)
    assert [type(item.rejected) for item in result] == [bool] * len(pvalues)


def test_holm_library_reject_flags_agree_with_alphas_threshold_rule() -> None:
    # ALPHA rejects when the adjusted p-value is <= alpha; statsmodels walks the step-down
    # thresholds alpha/(m-k). Both are Holm's rule; they agree on every family here.
    for pvalues in _pvalue_families()[::6]:
        for alpha in ALPHAS[1:3]:
            result = holm_adjust_secondary_family(_family(pvalues, alpha))
            library_reject = multipletests(np.array(pvalues), alpha=alpha, method="holm")[0]
            assert [item.rejected for item in result] == [bool(r) for r in library_reject]


# --- Benjamini-Hochberg: kept; statsmodels agrees to the last digit, not bit for bit ---------

BH_FROZEN_DIGEST = "d7c192dbf93ccacc3dcc91eefad45060372157320f6005bc6aaa4526bb0c566d"


def test_benjamini_hochberg_agrees_with_statsmodels_to_the_last_digit() -> None:
    qvalues_all: list[float] = []
    for pvalues in _pvalue_families():
        for alpha in ALPHAS:
            ours = benjamini_hochberg(pvalues, alpha=alpha)
            reject, q, _, _ = multipletests(np.array(pvalues), alpha=alpha, method="fdr_bh")
            assert float(np.max(np.abs(ours.qvalues - q))) <= LAST_DIGIT_ABS
            assert ours.rejected.tolist() == reject.tolist()
        qvalues_all.extend(float(v) for v in ours.qvalues)
    # ALPHA's own bits: these q-values are stored and compared with a threshold downstream.
    assert _hex_digest(qvalues_all) == BH_FROZEN_DIGEST


# --- Wilson and Newcombe intervals: kept, same reason -----------------------------------------

WILSON_FROZEN_DIGEST = "20db51d24f70adbb1ca4f8fffa46e1fcaf6bb723428d399b65a9695b2cbb7eeb"
NEWCOMBE_FROZEN_DIGEST = "3dbc3f4d2176920d794781db1e04c74cc2e7a1ed80c81dbbc28322c2fde2868a"
CONFIDENCES = (0.5, 0.683, 0.9, 0.95, 0.99)


def _count_cases() -> list[tuple[int, int]]:
    cases = [(k, n) for n in range(1, 41) for k in range(n + 1)]
    for n in (100, 257, 1000, 12345, 10**6):
        cases.extend((k, n) for k in sorted({0, 1, 2, n // 3, n // 2, n - 1, n}))
    return cases


def test_wilson_interval_agrees_with_statsmodels_to_the_last_digit() -> None:
    bounds: list[float] = []
    for successes, trials in _count_cases():
        for confidence in CONFIDENCES:
            ours = wilson_interval(successes, trials, confidence=confidence)
            low, high = proportion_confint(
                successes, trials, alpha=1.0 - confidence, method="wilson"
            )
            assert abs(ours.lower - low) <= LAST_DIGIT_ABS
            assert abs(ours.upper - high) <= LAST_DIGIT_ABS
            # The bounds bracket the point only to the last digit: at successes == 0 the
            # hand-written lower bound can be 1.4e-17 instead of 0, and at successes == trials
            # the upper bound 0.9999999999999999 instead of 1. Reported, not changed here.
            assert 0.0 <= ours.lower <= ours.point + LAST_DIGIT_ABS
            assert ours.point - LAST_DIGIT_ABS <= ours.upper <= 1.0
            bounds.extend((ours.lower, ours.upper))
    assert _hex_digest(bounds) == WILSON_FROZEN_DIGEST


def test_newcombe_interval_agrees_with_statsmodels_to_the_last_digit() -> None:
    rng = np.random.default_rng(20261116)
    bounds: list[float] = []
    for i in range(1500):
        n_a, n_b = int(rng.integers(1, 400)), int(rng.integers(1, 400))
        k_a, k_b = int(rng.integers(0, n_a + 1)), int(rng.integers(0, n_b + 1))
        if i % 10 == 0:
            k_a = 0
        if i % 13 == 0:
            k_b = n_b
        if i % 17 == 0:
            n_a = n_b = 1
            k_a, k_b = i % 2, (i // 2) % 2
        confidence = CONFIDENCES[2 + i % 3]
        ours = newcombe_diff_interval(k_a, n_a, k_b, n_b, confidence=confidence)
        low, high = confint_proportions_2indep(
            k_a, n_a, k_b, n_b, method="newcomb", compare="diff", alpha=1.0 - confidence
        )
        assert abs(ours.lower - low) <= LAST_DIGIT_ABS
        assert abs(ours.upper - high) <= LAST_DIGIT_ABS
        bounds.extend((ours.lower, ours.upper))
    assert _hex_digest(bounds) == NEWCOMBE_FROZEN_DIGEST


# --- Required sample size: kept; the library can differ by one whole observation --------------


def test_required_observations_equals_the_closed_form_away_from_a_knife_edge() -> None:
    rng = np.random.default_rng(20261117)
    for i in range(3000):
        minimum = float(rng.random() * 0.01) if i % 2 else 0.0
        alternative = minimum + float(rng.random() * 0.02 + 1e-5)
        sigma = float(rng.random() * 0.1 + 1e-4)
        alpha = (0.05, 0.01, 0.025, 0.1)[i % 4]
        power = (0.8, 0.9, 0.95, 0.6)[i % 3]
        ours = required_observations_known_sigma(
            alternative, minimum, sigma, alpha=alpha, target_power=power
        )
        library = normal_sample_size_one_tail(alternative - minimum, power, alpha, std_null=sigma)
        assert ours == max(2, math.ceil(float(library)))


def test_required_observations_can_differ_by_one_at_a_knife_edge() -> None:
    # When the exact answer is a whole number, rounding up amplifies a last-digit difference
    # (the library uses norm.isf(alpha), ALPHA norm.ppf(1 - alpha)) into one whole observation.
    from scipy.stats import norm

    differing = 0
    total = 0
    for alpha in (0.05, 0.01, 0.025, 0.1):
        for power in (0.8, 0.9, 0.95):
            z_total = float(norm.ppf(1.0 - alpha)) + float(norm.ppf(power))
            for exact in range(2, 200):
                gap = z_total / math.sqrt(exact)
                ours = required_observations_known_sigma(
                    gap, 0.0, 1.0, alpha=alpha, target_power=power
                )
                library = max(2, math.ceil(float(normal_sample_size_one_tail(gap, power, alpha))))
                assert ours in (exact, exact + 1)
                assert abs(ours - library) <= 1
                differing += ours != library
                total += 1
    assert total == 2376
    assert differing > 0  # the reason this function was not swapped


# --- Simulated power: kept; a seeded simulation of the number statsmodels gives exactly -------


def test_simulated_power_is_within_monte_carlo_error_of_the_analytic_power() -> None:
    cases = [
        (30, 0.010, 0.000, 0.050, 0.05),
        (50, 0.010, 0.000, 0.050, 0.05),
        (120, 0.004, 0.001, 0.020, 0.05),
        (400, 0.002, 0.000, 0.015, 0.01),
        (2, 0.500, 0.000, 1.000, 0.10),
        (5000, 0.001, 0.0005, 0.010, 0.025),
    ]
    for sample_size, alternative, minimum, sigma, alpha in cases:
        ours = simulate_prospective_power_known_sigma(
            sample_size, alternative, minimum, sigma, alpha=alpha, simulations=20_000, seed=7
        )
        standard_error = sigma / math.sqrt(sample_size)
        analytic = float(
            normal_power_het(
                (alternative - minimum) / standard_error, 1, alpha, alternative="larger"
            )
        )
        tolerance = MC_SIGMAS * math.sqrt(analytic * (1.0 - analytic) / ours.simulations)
        assert abs(ours.estimated_power - analytic) <= tolerance
    # ALPHA's stored number is the seeded estimate, not the analytic value.
    frozen = simulate_prospective_power_known_sigma(50, 0.010, 0.000, 0.050)
    assert frozen.estimated_power.hex() == "0x1.9cac083126e98p-2"
    assert frozen.rejection_threshold.hex() == "0x1.7d1ed26fec065p-7"


# --- Stationary bootstrap: kept; same law as arch, different random draws ---------------------

INDICES_FROZEN_DIGEST = "56b4305704fc938924b44c1f45f736455483257c64ff690196e669951064670d"


def _mean_block_length(indices: np.ndarray, n: int) -> float:
    breaks = indices[:, 1:] != (indices[:, :-1] + 1) % n
    return float(indices.size / (indices.shape[0] + int(breaks.sum())))


def _arch_indices(n: int, block: int, resamples: int, seed: int) -> np.ndarray:
    bootstrap = StationaryBootstrap(block, np.arange(n), seed=seed)
    return np.array([draw[0][0] for draw in bootstrap.bootstrap(resamples)])


def test_stationary_bootstrap_has_archs_law_but_not_archs_draws() -> None:
    n, block, resamples = 500, 5, 2000
    series = np.random.default_rng(1).normal(0.0005, 0.01, n)
    ours = stationary_bootstrap_indices(
        n, mean_block=float(block), n_resamples=resamples, rng=np.random.default_rng(3)
    )
    theirs = _arch_indices(n, block, resamples, seed=3)

    # Same seed, different numbers: arch draws one path at a time (start points, then
    # uniforms) and restarts a block when u <= p; ALPHA draws the whole uniform matrix, then
    # the whole start-point matrix, and restarts when u < p.
    assert not np.array_equal(ours, theirs)
    assert _hex_digest([float(v) for v in ours[:3].ravel()]) == INDICES_FROZEN_DIGEST

    # Same law. Mean block length: about 200,000 blocks per sample, so each estimate has a
    # relative standard error near 0.2%; 2% is far outside noise and far inside a wrong p.
    assert _mean_block_length(ours, n) == pytest.approx(block, rel=0.02)
    assert _mean_block_length(theirs, n) == pytest.approx(_mean_block_length(ours, n), rel=0.02)
    # Start points uniform on [0, n): mean of 1,000,000 indices has standard error 0.14.
    assert float(ours.mean()) == pytest.approx((n - 1) / 2, abs=MC_SIGMAS * 0.15)
    assert float(theirs.mean()) == pytest.approx((n - 1) / 2, abs=MC_SIGMAS * 0.15)
    # Spread of the resampled mean: a standard deviation from 2,000 draws has relative standard
    # error 1/sqrt(2*2000) = 1.6%, the difference of two 2.2%; 10% is 4.5 of those.
    ours_sd = float(series[ours].mean(axis=1).std(ddof=1))
    theirs_sd = float(series[theirs].mean(axis=1).std(ddof=1))
    assert ours_sd == pytest.approx(theirs_sd, rel=MC_SIGMAS * 0.022)


def test_block_bootstrap_ci_is_within_monte_carlo_error_of_archs_bca() -> None:
    series = np.random.default_rng(1).normal(0.0005, 0.01, 500)

    def mean_statistic(values: np.ndarray) -> float:
        return float(np.mean(values))

    ours = block_bootstrap_ci(series, mean_statistic, n_resamples=2000, mean_block=5.0, seed=11)
    low, high = (
        StationaryBootstrap(5, series, seed=11)
        .conf_int(lambda values: np.atleast_1d(np.mean(values)), reps=2000, method="bca")
        .ravel()
    )
    # A 2.5% quantile of 2,000 near-normal draws has standard error
    # sqrt(0.025*0.975/2000)/pdf(1.96) = 0.060 bootstrap standard deviations, i.e. 1.5% of the
    # interval width (3.92 standard deviations); the difference of two independent ones 2.2%.
    width = ours.upper - ours.lower
    assert abs(ours.lower - float(low)) <= MC_SIGMAS * 0.022 * width
    assert abs(ours.upper - float(high)) <= MC_SIGMAS * 0.022 * width
    assert (ours.lower.hex(), ours.upper.hex()) == (
        "-0x1.17f35875ac17cp-11",
        "0x1.d4e9ed0f7d9ebp-11",
    )


def test_risk_of_ruin_is_within_monte_carlo_error_of_an_arch_resample() -> None:
    returns = np.random.default_rng(9).normal(0.0, 0.03, 300)
    paths = 2000

    def worst_drawdown(values: np.ndarray) -> np.ndarray:
        equity = np.concatenate([[1.0], np.cumprod(1.0 + values)])
        return np.atleast_1d(float((equity / np.maximum.accumulate(equity) - 1.0).min()))

    for ruin in (0.2, 0.3, 0.45):
        ours = risk_of_ruin(returns, ruin_drawdown=ruin, n_paths=paths, mean_block=5.0, seed=4)
        drawdowns = StationaryBootstrap(5, returns, seed=4).apply(worst_drawdown, paths)
        theirs = float(np.mean(drawdowns <= -ruin))
        pooled = (ours + theirs) / 2.0
        tolerance = MC_SIGMAS * math.sqrt(2.0 * pooled * (1.0 - pooled) / paths)
        assert 0.0 < pooled < 1.0
        assert abs(ours - theirs) <= tolerance


# --- Reality Check and SPA: kept; different draws, and arch's SPA is a different statistic ----


def _arch_spa(perf: np.ndarray, resamples: int, seed: int, *, studentize: bool) -> dict[str, float]:
    # arch compares losses (lower is better) against a benchmark's losses; ALPHA's matrix is
    # performance relative to the benchmark, so the benchmark loss is zero and models are -perf.
    spa = SPA(
        np.zeros(perf.shape[0]),
        -perf,
        block_size=5,
        reps=resamples,
        bootstrap="stationary",
        studentize=studentize,
        seed=seed,
    )
    spa.compute()
    return {str(key): float(value) for key, value in spa.pvalues.items()}


def _p_value_tolerance(p_ours: float, p_theirs: float, resamples: int) -> float:
    # ALPHA counts (1 + #{null >= observed}) / (1 + B); arch counts #{null > observed} / B. That
    # is at most 1/(B+1) apart on identical draws; the rest is two independent Monte Carlo errors.
    pooled = min(max((p_ours + p_theirs) / 2.0, 1.0 / resamples), 1.0 - 1.0 / resamples)
    return 1.0 / (resamples + 1) + MC_SIGMAS * math.sqrt(2.0 * pooled * (1.0 - pooled) / resamples)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_reality_check_is_within_monte_carlo_error_of_archs_upper_p_value(seed: int) -> None:
    resamples = 2000
    rng = np.random.default_rng(200 + seed)
    null = rng.normal(0.0, 0.01, (400, 6))
    edge = null.copy()
    edge[:, 0] += 0.0012
    for perf in (null, edge):
        ours = reality_check(perf, n_resamples=resamples, mean_block=5.0, seed=seed)
        theirs = _arch_spa(perf, resamples, seed, studentize=False)["upper"]
        assert abs(ours.p_value - theirs) <= _p_value_tolerance(ours.p_value, theirs, resamples)


def test_archs_spa_is_not_hansens_studentized_statistic() -> None:
    # One quiet strategy with a real edge among twelve loud ones with none. Hansen's studentized
    # statistic (ALPHA) ranks by mean over long-run standard deviation and finds the quiet edge.
    # arch 8 uses its variance estimate only to decide which strategies to recentre; its test
    # statistic is the largest raw mean, which the loud strategies dominate.
    resamples = 1000
    rng = np.random.default_rng(100)
    quiet_edge = rng.normal(0.0006, 0.002, 600)
    loud_noise = [rng.normal(0.0, 0.03, 600) for _ in range(12)]
    perf = np.column_stack([quiet_edge, *loud_noise])

    ours = spa_test(perf, n_resamples=resamples, mean_block=5.0, seed=0)
    theirs = _arch_spa(perf, resamples, 0, studentize=True)

    assert ours.p_value == pytest.approx(1.0 / (resamples + 1))
    assert ours.passed
    assert theirs["consistent"] > 0.2
    # arch's flag changes nothing in its p-values here: the statistic is not studentized.
    assert theirs == _arch_spa(perf, resamples, 0, studentize=False)
    # ALPHA's own Reality Check (unstudentized by design) agrees with arch on the same data.
    unstudentized = reality_check(perf, n_resamples=resamples, mean_block=5.0, seed=0)
    assert abs(unstudentized.p_value - theirs["upper"]) <= _p_value_tolerance(
        unstudentized.p_value, theirs["upper"], resamples
    )


def test_data_snooping_p_values_are_frozen() -> None:
    rng = np.random.default_rng(5)
    perf = rng.normal(0.0, 0.01, (400, 8))
    perf[:, 0] += 0.001
    assert reality_check(perf, seed=3).p_value.hex() == "0x1.26c3bdfc29738p-7"
    spa = spa_test(perf, seed=3)
    assert (spa.p_value.hex(), spa.statistic.hex()) == (
        "0x1.ca85d232eb258p-8",
        "0x1.99bc2b7b80329p+1",
    )
