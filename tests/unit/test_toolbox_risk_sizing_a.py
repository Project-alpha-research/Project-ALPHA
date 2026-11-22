"""Known answers: parametric VaR, Cornish-Fisher VaR and the worst windows."""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
from scipy import stats

from alpha_validation.metrics import value_at_risk
from tests.unit.risk_sizing_support import put_equity, put_returns, read, stored

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


def test_worst_windows(tmp_path: Path) -> None:
    stored(tmp_path)
    head = np.array([100.0, 101, 99, 98, 103, 104, 90, 92, 95, 96, 97, 98])
    equity = np.r_[head, np.linspace(98.0, 110.0, 30)] / 100
    put_equity(tmp_path, equity)
    values = read(tmp_path, "risk.worst_windows")["values"]
    # The single worst bar is the drop from 104 to 90 on the seventh bar (index 6).
    assert values["worst_1"] == pytest.approx(90 / 104 - 1, rel=REL, abs=ABS)
    assert values["end_1"] == "2022-01-07"
    for size in (5, 21):
        ratios = equity[size:] / equity[:-size] - 1
        assert values[f"worst_{size}"] == pytest.approx(ratios.min(), rel=REL, abs=ABS)
        end = datetime(2022, 1, 1) + timedelta(days=int(ratios.argmin()) + size)
        assert values[f"end_{size}"] == end.strftime("%Y-%m-%d")


def test_worst_windows_short_history_names_the_count(tmp_path: Path) -> None:
    stored(tmp_path)
    put_equity(tmp_path, np.array([1.0, 0.9, 0.95, 1.0, 1.1, 1.05]))
    doc = read(tmp_path, "risk.worst_windows")
    assert doc["values"]["worst_1"] == pytest.approx(-0.1, rel=REL, abs=ABS)
    assert doc["values"]["worst_5"] == pytest.approx(1.05 - 1, rel=REL, abs=ABS)
    assert doc["values"]["worst_21"] is None
    assert "found 5" in doc["reasons"]["worst_21"]
