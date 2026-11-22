"""Known answers: parametric VaR, Cornish-Fisher VaR and the worst windows."""

from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
from scipy import stats

from alpha_validation.metrics import value_at_risk
from tests.unit.risk_sizing_support import put_returns, read, stored

REL, ABS = 1e-9, 1e-12


def skewed_returns() -> npt.NDArray[np.float64]:
    i = np.arange(150)
    return np.asarray(
        0.01 * np.sin(0.7 * i) - 0.03 * (i % 11 == 0) + 0.004 * (i % 5), dtype=np.float64
    )


def test_parametric_var(tmp_path: Path) -> None:
    stored(tmp_path)
    r = skewed_returns()
    put_returns(tmp_path, r)
    doc = read(tmp_path, "risk.parametric_var")
    values = doc["values"]
    mean, sd = r.mean(), r.std(ddof=1)
    # RiskMetrics (1996): VaR = -(mean + z * sd) with z the normal quantile at 1 - confidence.
    assert values["normal_var"] == pytest.approx(
        -(mean + sd * stats.norm.ppf(0.05)), rel=REL, abs=ABS
    )
    df, loc, scale = stats.t.fit(r)
    assert values["t_df"] == pytest.approx(df, rel=1e-6)
    assert values["t_var"] == pytest.approx(-stats.t.ppf(0.05, df, loc, scale), rel=1e-6)
    assert values["historical_var"] == pytest.approx(value_at_risk(r), rel=REL, abs=ABS)
    again = read(tmp_path, "risk.parametric_var", "confidence=0.99")["values"]
    assert again["normal_var"] == pytest.approx(
        -(mean + sd * stats.norm.ppf(0.01)), rel=REL, abs=ABS
    )


def test_parametric_var_refuses_a_collapsed_student_t_fit(tmp_path: Path) -> None:
    # A run flat 40% of the time (out of the market) makes the Student-t fit collapse onto zero.
    stored(tmp_path)
    r = np.random.default_rng(3).normal(0.0004, 0.01, 200)
    r[np.arange(200) % 5 < 2] = 0.0
    put_returns(tmp_path, r)
    doc = read(tmp_path, "risk.parametric_var")
    assert doc["values"]["t_var"] is None and doc["values"]["t_df"] is None
    assert "flat" in doc["reasons"]["t_var"]
    assert doc["values"]["normal_var"] > 0


def test_cornish_fisher_var(tmp_path: Path) -> None:
    stored(tmp_path)
    r = skewed_returns()
    put_returns(tmp_path, r)
    values = read(tmp_path, "risk.cornish_fisher_var")["values"]
    z = stats.norm.ppf(0.05)
    s, k = stats.skew(r), stats.kurtosis(r)
    # Zangari (1996), Favre and Galeano (2002) eq. 3: the quantile adjusted by skew and kurtosis.
    z_cf = z + (z**2 - 1) * s / 6 + (z**3 - 3 * z) * k / 24 - (2 * z**3 - 5 * z) * s**2 / 36
    expected = -(r.mean() + r.std(ddof=1) * z_cf)
    assert values["cf_var"] == pytest.approx(max(0.0, expected), rel=REL, abs=ABS)
    assert values["skew"] == pytest.approx(s, rel=REL, abs=ABS)
    assert values["excess_kurtosis"] == pytest.approx(k, rel=REL, abs=ABS)
    assert values["normal_var"] == pytest.approx(-(r.mean() + r.std(ddof=1) * z), rel=REL, abs=ABS)


def test_cornish_fisher_says_when_the_expansion_breaks(tmp_path: Path) -> None:
    stored(tmp_path)
    r = np.full(100, 0.001)
    r[0] = -0.5
    put_returns(tmp_path, r)
    doc = read(tmp_path, "risk.cornish_fisher_var", "confidence=0.99")
    assert doc["values"]["cf_var"] is None
    assert "expansion" in doc["reasons"]["cf_var"]
    assert doc["values"]["skew"] == pytest.approx(stats.skew(r), rel=REL, abs=ABS)
