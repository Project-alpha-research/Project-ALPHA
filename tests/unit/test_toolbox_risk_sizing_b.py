"""Known answers: tail fit, Kupiec coverage and Christoffersen independence."""

import math
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
from scipy import stats

from tests.unit.risk_sizing_support import put_returns, read, stored

REL, ABS = 1e-9, 1e-12


def geometric_tail_losses() -> npt.NDArray[np.float64]:
    """200 losses: twenty geometric ones above a threshold, the rest below 0.002."""
    top = 0.002 * 1.2 ** np.arange(1, 21)
    rest = np.linspace(0.0001, 0.0019, 179)
    return np.asarray(np.r_[rest, 0.002, top], dtype=np.float64)


def test_tail_fit(tmp_path: Path) -> None:
    stored(tmp_path)
    losses = geometric_tail_losses()
    put_returns(tmp_path, -losses)
    values = read(tmp_path, "risk.tail_fit")["values"]
    assert values["exceedances"] == 20
    # Hill (1975): mean log ratio of the k largest to the next one; here (k + 1) / 2 * ln 1.2.
    assert values["hill_index"] == pytest.approx(10.5 * math.log(1.2), rel=REL, abs=ABS)
    u = np.quantile(losses, 0.9)
    assert values["threshold"] == pytest.approx(u, rel=REL, abs=ABS)
    shape, _, scale = stats.genpareto.fit(losses[losses > u] - u, floc=0)
    assert values["gpd_shape"] == pytest.approx(shape, rel=1e-6)
    assert values["gpd_scale"] == pytest.approx(scale, rel=1e-6)
    # McNeil and Frey (2000) eq. 8 and 9 for the 99% point of the loss tail.
    var = u + scale / shape * ((200 / 20 * 0.01) ** (-shape) - 1)
    assert values["var_99"] == pytest.approx(var, rel=1e-6)
    es = (var + scale - shape * u) / (1 - shape)
    assert values["es_99"] == pytest.approx(es, rel=1e-6)


def test_tail_fit_needs_twenty_beyond_the_threshold(tmp_path: Path) -> None:
    stored(tmp_path)
    put_returns(tmp_path, np.sin(np.arange(120) * 0.9) * 0.01)
    doc = read(tmp_path, "risk.tail_fit")
    assert doc["values"]["gpd_shape"] is None
    assert "found 12 in 120 bars" in doc["reasons"]["gpd_shape"]


def breach_returns(
    positions: list[int], evaluated: int = 60, history: int = 60
) -> npt.NDArray[np.float64]:
    """Gains of one percent, with a loss on the stated positions of the evaluated stretch."""
    r = np.full(history + evaluated, 0.01)
    for p in positions:
        r[history + p] = -0.01
    return r


def test_var_coverage(tmp_path: Path) -> None:
    stored(tmp_path)
    put_returns(tmp_path, breach_returns([10, 11, 40]))
    values = read(tmp_path, "risk.var_coverage")["values"]
    n, x, p = 60, 3, 0.05
    # Kupiec (1995) eq. 5: LR = -2 ln[(1-p)^(n-x) p^x] + 2 ln[(1-x/n)^(n-x) (x/n)^x].
    lr = -2 * ((n - x) * math.log(1 - p) + x * math.log(p))
    lr += 2 * ((n - x) * math.log(1 - x / n) + x * math.log(x / n))
    assert values["evaluated"] == n
    assert values["breaches"] == x
    assert values["expected_breaches"] == pytest.approx(3.0, rel=REL, abs=ABS)
    assert values["breach_rate"] == pytest.approx(0.05, rel=REL, abs=ABS)
    assert values["lr"] == pytest.approx(lr, rel=REL, abs=ABS)
    assert values["p_value"] == pytest.approx(stats.chi2.sf(lr, 1), rel=REL, abs=ABS)


def test_var_coverage_with_no_breach(tmp_path: Path) -> None:
    stored(tmp_path)
    put_returns(tmp_path, breach_returns([]))
    values = read(tmp_path, "risk.var_coverage")["values"]
    assert values["breaches"] == 0
    assert values["lr"] == pytest.approx(-2 * 60 * math.log(0.95), rel=REL, abs=ABS)


def test_var_independence(tmp_path: Path) -> None:
    stored(tmp_path)
    put_returns(tmp_path, breach_returns([10, 11, 40]))
    values = read(tmp_path, "risk.var_independence")["values"]
    # Breaches at 10, 11 and 40 of 60: pairs (0,0)=54, (0,1)=2, (1,0)=2, (1,1)=1.
    n00, n01, n10, n11 = 54, 2, 2, 1
    p01, p11 = n01 / (n00 + n01), n11 / (n10 + n11)
    p = (n01 + n11) / (n00 + n01 + n10 + n11)
    ll0 = (n00 + n10) * math.log(1 - p) + (n01 + n11) * math.log(p)
    ll1 = n00 * math.log(1 - p01) + n01 * math.log(p01)
    ll1 += n10 * math.log(1 - p11) + n11 * math.log(p11)
    lr_ind = -2 * (ll0 - ll1)
    n, x, rate = 60, 3, 0.05
    lr_uc = -2 * ((n - x) * math.log(1 - rate) + x * math.log(rate))
    lr_uc += 2 * ((n - x) * math.log(1 - x / n) + x * math.log(x / n))
    assert values["breaches"] == 3
    assert values["breach_after_breach"] == pytest.approx(p11, rel=REL, abs=ABS)
    assert values["breach_after_calm"] == pytest.approx(p01, rel=REL, abs=ABS)
    assert values["lr_independence"] == pytest.approx(lr_ind, rel=REL, abs=ABS)
    assert values["p_independence"] == pytest.approx(stats.chi2.sf(lr_ind, 1), rel=REL, abs=ABS)
    assert values["lr_conditional"] == pytest.approx(lr_uc + lr_ind, rel=REL, abs=ABS)
    assert values["p_conditional"] == pytest.approx(
        stats.chi2.sf(lr_uc + lr_ind, 2), rel=REL, abs=ABS
    )


def test_var_independence_needs_breaches(tmp_path: Path) -> None:
    stored(tmp_path)
    put_returns(tmp_path, breach_returns([]))
    doc = read(tmp_path, "risk.var_independence")
    assert doc["values"]["lr_independence"] is None
    assert "no breach" in doc["reasons"]["lr_independence"].lower()
    assert doc["values"]["breaches"] == 0
