"""Time-series checks: known answers, too little data and repeatability, one block per check."""

import itertools
import math
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.tsa.stattools import acf as sm_acf
from statsmodels.tsa.stattools import pacf as sm_pacf

from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox.families import timeseries_a as ta
from alpha_cli.toolbox.families import timeseries_b as tb
from alpha_cli.toolbox.families import timeseries_c as tc
from alpha_cli.toolbox.families import timeseries_d as td
from alpha_cli.toolbox.families.timeseries import CHECKS
from alpha_cli.toolbox.inputs import Inputs, resolve
from alpha_cli.toolbox.registry import SPECS, get
from alpha_cli.toolbox.runner import run
from alpha_patterns.cycles import hurst_exponent, hurst_random_walk_reference, variance_ratio
from tests.unit.test_spine_tools import RUN
from tests.unit.test_toolbox_resampling_checks import write_equity
from tests.unit.test_toolbox_run_level_checks import END, stored_run

LJUNG, ACF, VR, HURST, RUNS = (
    f"timeseries.{n}"
    for n in ("ljung_box", "autocorrelation", "variance_ratio", "hurst", "up_down_runs")
)
ARCH, NORMAL, DFA, GPH, SAMPEN, LZ, PERM = (
    f"timeseries.{n}"
    for n in (
        "arch_lm",
        "normality",
        "dfa",
        "long_memory",
        "sample_entropy",
        "compressibility",
        "permutation_entropy",
    )
)
TOOLS = (LJUNG, ACF, VR, HURST, RUNS, ARCH, NORMAL, DFA, GPH, SAMPEN, LZ, PERM)


def sample(n: int = 400, seed: int = 11) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0005, 0.01, n)


def put(home: Path, tool: str, returns: np.ndarray) -> None:
    folder = stored_run(home, tool)
    write_equity(folder, np.r_[1.0, np.cumprod(1.0 + returns)])


def compute(home: Path, tool: str, params: dict[str, Any] | None = None, seed: int = 19) -> Any:
    spec = get(tool)
    settings = {p.name: p.default for p in spec.params} | (params or {})
    rng = np.random.default_rng(seed) if spec.seeded else None
    assert spec.compute is not None
    return spec.compute(Inputs(resolve(home, RUN), seed=seed), settings, rng)


def test_all_checks_registered_and_listed() -> None:
    ids = {spec.id for spec in SPECS}
    assert set(TOOLS) <= ids and len(CHECKS) == len(TOOLS) and len(TOOLS) >= 10
    for spec in CHECKS:
        assert spec.family == "timeseries" and spec.needs == ("stored_equity",)
        text = spec.reading.lower()
        assert not any(word in text for word in (" pass", " fail", "should", "buy ", "sell "))


# ---- known answers -------------------------------------------------------------------------


def test_known_ljung_box() -> None:
    r = sample()
    q, p = ta.ljung_box(r, 10)
    ref = acorr_ljungbox(r, lags=[10], return_df=True)
    assert (q, p) == pytest.approx(
        (ref["lb_stat"].iloc[0], ref["lb_pvalue"].iloc[0]), rel=1e-9, abs=1e-12
    )


def test_known_autocorrelation() -> None:
    r = sample()
    acf = ta.autocorrelations(r, 8)
    assert acf == pytest.approx(sm_acf(r, nlags=8, fft=False)[1:], rel=1e-9, abs=1e-12)
    assert ta.partial_autocorrelations(acf) == pytest.approx(
        sm_pacf(r, nlags=8, method="ldb")[1:], rel=1e-9, abs=1e-12
    )
    # A perfectly alternating series has lag-1 autocorrelation -(n-1)/n.
    alt = np.array([1.0, -1.0] * 10)
    assert ta.autocorrelations(alt, 1)[0] == pytest.approx(-19 / 20, rel=1e-9, abs=1e-12)


def test_known_variance_ratio() -> None:
    r = sample()
    log_prices = np.r_[0.0, np.cumsum(np.log1p(r))]
    ref = variance_ratio(log_prices, q=5)
    assert (ref.ratio, ref.z_score) == pytest.approx(td.variance_ratio_z(r, 5), rel=1e-9, abs=1e-12)
    # Trending returns read above 1, alternating returns below 1.
    trend = np.r_[np.full(100, 0.01), np.full(100, -0.01)] + sample(200, 3) * 0.001
    assert td.variance_ratio_z(trend, 5)[0] > 1.0
    zig = np.array([0.01, -0.01] * 100) + sample(200, 4) * 0.001
    assert td.variance_ratio_z(zig, 5)[0] < 1.0


def test_known_hurst_matches_library() -> None:
    r = sample(512)
    values = td.hurst_reading(r, trials=30, seed=5)
    assert values["hurst"] == pytest.approx(hurst_exponent(r), rel=1e-9, abs=1e-12)
    mean, sd = hurst_random_walk_reference(512, trials=30, seed=5)
    assert (values["null_mean"], values["null_sd"]) == pytest.approx(
        (mean, sd), rel=1e-9, abs=1e-12
    )
    assert values["z"] == pytest.approx((values["hurst"] - mean) / sd, rel=1e-9, abs=1e-12)


def test_known_runs_hand_case() -> None:
    # + + - - + - + + - +: 6 ups, 4 downs, 7 runs; mean 2*6*4/10+1 = 5.8, variance 4.8*3.8/9.
    r = np.array([1, 1, -1, -1, 1, -1, 1, 1, -1, 1]) * 0.01
    z = (7 - 5.8) / math.sqrt(4.8 * 3.8 / 9)
    got = td.runs_reading(r)
    assert got == pytest.approx(
        {"runs": 7, "expected": 5.8, "z": z, "p_value": 2 * stats.norm.sf(abs(z))},
        rel=1e-9,
        abs=1e-12,
    )


def test_known_arch_lm() -> None:
    rng = np.random.default_rng(2)
    spell = np.repeat(np.tile([0.004, 0.03], 20), 20)
    r = rng.normal(0, spell)
    lm, p = tb.arch_lm(r, 5)
    ref = het_arch(r - r.mean(), nlags=5, ddof=0, result_object=False)
    assert (lm, p) == pytest.approx((ref[0], ref[1]), rel=1e-9, abs=1e-12)
    assert p < 1e-3
    assert tb.arch_lm(sample(), 5)[1] > 0.01


def test_known_normality() -> None:
    r = np.random.default_rng(8).standard_t(4, 600) * 0.01
    got = tb.normality_reading(r)
    jb = stats.jarque_bera(r)
    assert got == pytest.approx(
        {
            "skew": stats.skew(r),
            "excess_kurtosis": stats.kurtosis(r),
            "jarque_bera": jb.statistic,
            "jb_p_value": jb.pvalue,
            "shapiro_p_value": stats.shapiro(r).pvalue,
        },
        rel=1e-9,
        abs=1e-12,
    )
    assert got["jb_p_value"] is not None and got["jb_p_value"] < 0.01
    big = tb.normality_reading(sample(5001))
    assert big["shapiro_p_value"] is None


def test_known_dfa() -> None:
    # Profile of +1,-1,... is 1,0,1,0; a line fit to each box of 4 leaves squared residuals
    # 0.04+0.36+0.36+0.04 = 0.8, so F(4)^2 = 0.8 / 4 = 0.2.
    x = np.array([1.0, -1.0] * 4)
    assert tb.fluctuation(x, 4) == pytest.approx(math.sqrt(0.2), rel=1e-9, abs=1e-12)
    # Peng et al. 1994: white noise gives alpha near 0.5, its running sum near 1.5.
    noise = sample(4000, 5)
    assert tb.dfa_exponent(noise) == pytest.approx(0.5, abs=0.08)
    assert tb.dfa_exponent(np.cumsum(noise)) == pytest.approx(1.5, abs=0.15)


def test_known_long_memory() -> None:
    r = sample(64, 6)
    x = r - r.mean()
    n, m = len(x), 8
    freq = 2 * np.pi * np.arange(1, m + 1) / n
    dft = [
        abs(sum(x[t] * np.exp(-1j * w * t) for t in range(n))) ** 2 / (2 * np.pi * n) for w in freq
    ]
    regressor = np.log(4 * np.sin(freq / 2) ** 2)
    slope = np.polyfit(regressor, np.log(dft), 1)[0]
    se = math.pi / math.sqrt(6 * np.sum((regressor - regressor.mean()) ** 2))
    assert tb.gph(r, 0.5) == pytest.approx((-slope, se), rel=1e-9, abs=1e-12)
    assert abs(tb.gph(sample(4000, 7), 0.5)[0]) < 3 * tb.gph(sample(4000, 7), 0.5)[1]


def brute_sample_entropy(x: np.ndarray, m: int, tol: float) -> float:
    n = len(x)
    a = b = 0
    for i, j in itertools.combinations(range(n - m), 2):
        if max(abs(x[i + k] - x[j + k]) for k in range(m)) <= tol:
            b += 1
            if abs(x[i + m] - x[j + m]) <= tol:
                a += 1
    return -math.log(a / b)


def test_known_sample_entropy() -> None:
    # Richman & Moorman 2000: -ln(A/B) over the first n-m templates, tolerance r * sd.
    x = sample(80, 9)
    tol = 0.2 * float(np.std(x))
    assert tc.sample_entropy(x, 2, 0.2) == pytest.approx(
        brute_sample_entropy(x, 2, tol), rel=1e-9, abs=1e-12
    )
    assert tc.sample_entropy(np.full(50, 0.01), 2, 0.2) == pytest.approx(0.0, abs=1e-12)
    # No two patterns within tolerance: undefined, not a number.
    assert (
        tc.sample_entropy(np.array([0.0, 10.0, 20.0, 40.0, 80.0, 160.0, 320.0]), 2, 0.001) is None
    )
    assert tc.sample_entropy(np.tile([0.0, 1.0, 0.5], 40), 2, 0.2) == pytest.approx(0.0, abs=1e-12)


def test_known_compressibility() -> None:
    # Hand parses (Lempel & Ziv 1976): 0|001|10|100|1000|101 is 6 parts; 0|1|01010101 is 3.
    assert tc.lz_complexity([int(c) for c in "0001101001000101"]) == 6
    assert tc.lz_complexity([int(c) for c in "0101010101"]) == 3
    assert tc.lz_complexity([0] * 8) == 2
    rng = np.random.default_rng(1)
    random_bits = (rng.random(4000) > 0.5).astype(int).tolist()
    assert tc.lz_reading(np.where(np.array(random_bits) == 1, 0.01, -0.01))["normalised"] == (
        pytest.approx(1.0, abs=0.15)
    )


def test_known_permutation_entropy() -> None:
    assert tc.permutation_entropy_of(np.arange(1.0, 60.0), 3) == pytest.approx(0.0, abs=1e-12)
    x = sample(300, 10)
    counts: dict[tuple[int, ...], int] = {}
    for i in range(len(x) - 2):
        key = tuple(np.argsort(x[i : i + 3], kind="stable"))
        counts[key] = counts.get(key, 0) + 1
    p = np.array(list(counts.values())) / (len(x) - 2)
    expected = float(-(p * np.log2(p)).sum() / math.log2(6))
    assert tc.permutation_entropy_of(x, 3) == pytest.approx(expected, rel=1e-9, abs=1e-12)


# ---- one run through the command path ------------------------------------------------------


@pytest.mark.parametrize("tool", TOOLS)
def test_end_to_end_values_are_finite_and_reading_renders(tool: str, tmp_path: Path) -> None:
    put(tmp_path, tool, sample(700, 21))
    doc = run(tmp_path, tool, RUN)
    assert all(isinstance(v, float | int) for v in doc["values"].values()), doc["reasons"]
    assert doc["reading"] and "unavailable" not in doc["reading"]
    assert run(tmp_path, tool, RUN) == doc


# ---- too little data -----------------------------------------------------------------------


@pytest.mark.parametrize("tool", TOOLS)
def test_too_little_data(tool: str, tmp_path: Path) -> None:
    put(tmp_path, tool, sample(7, 1))
    doc = run(tmp_path, tool, RUN)
    assert all(v is None for v in doc["values"].values())
    assert all("at least" in reason and "has 7" in reason for reason in doc["reasons"].values())
    assert "unavailable" in doc["reading"]


# ---- repeat is identical -------------------------------------------------------------------


@pytest.mark.parametrize("tool", TOOLS)
def test_repeat_is_identical(tool: str, tmp_path: Path) -> None:
    put(tmp_path, tool, sample(700, 22))
    first = compute(tmp_path, tool)
    assert compute(tmp_path, tool) == first


@pytest.mark.parametrize("tool", TOOLS)
def test_future_input_rejected(tool: str, tmp_path: Path) -> None:
    put(tmp_path, tool, sample(700, 23))
    path = tmp_path / "runs" / RUN / "equity_curve.parquet"
    frame = pl.read_parquet(path)
    frame.vstack(
        frame.tail(1).with_columns(pl.lit(END + timedelta(days=1)).alias("ts"))
    ).write_parquet(path)
    with pytest.raises(SpineError, match="run period"):
        run(tmp_path, tool, RUN)


def test_arch_lm_constant_squares_is_unavailable(tmp_path: Path) -> None:
    # Alternating +0.5 / -0.5 vary, but every squared residual is the same.
    put(tmp_path, ARCH, np.array([0.5, -0.5] * 20))
    doc = run(tmp_path, ARCH, RUN)
    assert all(v is None for v in doc["values"].values())
    assert all("squared returns do not vary" in r for r in doc["reasons"].values())


def test_runs_leave_out_flat_bars() -> None:
    # Flat bars neither add nor break streaks: zeros between the same signs change nothing.
    signs = np.array([1, 1, -1, -1, 1, -1, 1, 1, -1, 1]) * 0.01
    padded = np.insert(signs, [2, 5, 5, 9], 0.0)
    assert td.runs_reading(padded) == td.runs_reading(signs)
