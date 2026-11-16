"""Wave 1 item 4: fixed-width fractional differencing, with d chosen on training data only.

Both libraries' weights and FFD values must agree to 1e-10. The minimum-d search (Snippet 5.4:
the smallest d on a 0.0..1.0 grid whose FFD series passes an ADF test, maxlag 1, constant) is the
look-ahead trap: run on the whole series it uses the future. :func:`fit_min_d` therefore takes the
training span only and returns d frozen; :func:`ffd` then applies that fixed d forward. The FFD
value at bar t uses bars ``t - width .. t`` only.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from quantowl import fracdiff as qf
from RiskLabAI.data.differentiation import differentiation as rd
from statsmodels.tsa.stattools import adfuller

from alpha_afml_worker.contract import AgreementError, ContractError

TOLERANCE = 1e-10
GRID = np.round(np.linspace(0.0, 1.0, 11), 10)


def ffd_weights(d: float, thres: float) -> np.ndarray:
    """Lag-ordered FFD weights ``w_0 = 1, w_1, ...``; both libraries must agree."""
    q = np.asarray(qf.get_weights_ffd(d, thres), dtype=np.float64)
    r = np.asarray(rd.calculate_weights_ffd(d, thres), dtype=np.float64).ravel()[::-1]
    if q.shape != r.shape or float(np.max(np.abs(q - r))) > TOLERANCE:
        raise AgreementError(f"FFD weights differ for d={d}, thres={thres}")
    return q


def ffd(values: np.ndarray, d: float, thres: float) -> np.ndarray:
    """FFD of ``values`` (log prices); NaN during the warm-up. Libraries agree to 1e-10."""
    x = np.asarray(values, dtype=np.float64)
    if x.ndim != 1 or x.size < 2 or not bool(np.all(np.isfinite(x))):
        raise ContractError("ffd needs a finite 1-D series of at least 2 values")
    ffd_weights(d, thres)
    q = np.asarray(qf.frac_diff_ffd(x, d, thres), dtype=np.float64)
    r = rd.fractional_difference_fixed_single(pd.Series(x), d, thres).to_numpy(dtype=np.float64)
    if not np.array_equal(np.isnan(q), np.isnan(r)):
        raise AgreementError("FFD warm-up differs between the libraries")
    both = ~np.isnan(q)
    if both.any() and float(np.max(np.abs(q[both] - r[both]))) > TOLERANCE:
        raise AgreementError("FFD values differ between the libraries")
    return q


def _adf_pvalue(x: np.ndarray) -> float:
    return float(adfuller(x, maxlag=1, regression="c", autolag=None)[1])


@dataclass(frozen=True)
class MinD:
    """The smallest passing d on the training span, frozen, with the table that chose it."""

    d: float | None
    pvalue: float | None
    corr: float | None
    table: list[dict[str, float]]  # d, ADF p-value, correlation with the input, per grid value
    train_bars: int


def fit_min_d(close_train: pd.Series, pvalue: float = 0.05, thres: float = 0.01) -> MinD:
    """Snippet 5.4 on the training closes only; both libraries must pick the same d.

    ``close_train`` is a price Series on a DatetimeIndex (RiskLabAI takes logs and calendar days
    itself). quantowl's search gets the same log prices and statsmodels' ADF.
    """
    if not isinstance(close_train.index, pd.DatetimeIndex) or close_train.size < 60:
        raise ContractError("fit_min_d needs at least 60 training closes on a DatetimeIndex")
    values = close_train.to_numpy(dtype=np.float64)
    if not bool(np.all(np.isfinite(values))) or bool(np.any(values <= 0.0)):
        raise ContractError("training closes must be finite and > 0")
    log = np.log(values)
    q = qf.find_min_d(log, pvalue, adf_test=_adf_pvalue, d_grid=GRID, thres=thres)
    index = close_train.index.tz_convert("UTC").tz_localize(None).normalize()
    if index.has_duplicates:
        raise ContractError("fit_min_d expects one close per calendar day")
    frame = pd.DataFrame({"close": values}, index=index)
    table = rd.find_optimal_ffd_simple(frame, p_value_threshold=pvalue)
    passing = table.index[table["pVal"] <= pvalue]
    r_d = float(passing[0]) if len(passing) else None
    if (q.d is None) != (r_d is None) or (
        q.d is not None and r_d is not None and abs(q.d - r_d) > 1e-9
    ):
        raise AgreementError(f"minimum d differs: quantowl {q.d}, RiskLabAI {r_d}")
    if q.pvalue is not None and abs(q.pvalue - float(table.loc[passing[0], "pVal"])) > 1e-8:
        raise AgreementError("ADF p-values differ between the libraries at the chosen d")
    rows = [{"d": float(d), "pvalue": float(row["pVal"]), "corr": float(row["corr"])}
            for d, row in table.iterrows()]  # fmt: skip
    return MinD(q.d, q.pvalue, q.corr, rows, int(values.size))
