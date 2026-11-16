"""Wave 1 item 6: second opinions on ALPHA's PSR, DSR and PBO; minimum track record; strategy risk.

The worker computes each statistic with RiskLabAI and quantowl from the same inputs and returns
both, side by side, with the moments it used. It does not pick a winner: ALPHA's own
``alpha_validation`` values stay the record, and ``tests/integration/test_afml_stats_parity.py``
compares the three and names the cause of every difference. Conventions used here are ALPHA's:
per-observation (not annualised) Sharpe with ``ddof=1``, skewness and non-excess kurtosis with
``bias=True``, and the trial-Sharpe variance with ``ddof=1``.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from quantowl import pbo as qpbo
from quantowl import stats as qs
from quantowl import strategy_risk as qsr
from RiskLabAI.backtest.probabilistic_sharpe_ratio import benchmark_sharpe_ratio
from RiskLabAI.backtest.probabilistic_sharpe_ratio import probabilistic_sharpe_ratio as r_psr
from RiskLabAI.backtest.probability_of_backtest_overfitting import (
    probability_of_backtest_overfitting as r_pbo,
)
from RiskLabAI.backtest.strategy_risk import implied_precision as r_implied_precision
from scipy import stats as ss

from alpha_afml_worker.contract import ContractError


def _returns(values: np.ndarray) -> np.ndarray:
    r = np.asarray(values, dtype=np.float64)
    if r.ndim != 1 or r.size < 3 or not bool(np.all(np.isfinite(r))):
        raise ContractError("returns must be a finite 1-D series of at least 3 values")
    if float(np.std(r, ddof=1)) <= 0.0:
        raise ContractError("returns have zero variance; a Sharpe ratio is undefined")
    return r


def sharpe_stats(
    returns: np.ndarray, trial_sharpes: np.ndarray | None = None, prob: float = 0.95
) -> dict[str, Any]:
    """PSR(0), DSR and minimum track record length from both libraries, with their inputs."""
    r = _returns(returns)
    n = int(r.size)
    sr = float(np.mean(r) / np.std(r, ddof=1))
    skew = float(ss.skew(r, bias=True))
    kurt = float(ss.kurtosis(r, fisher=False, bias=True))
    trials = None if trial_sharpes is None else np.asarray(trial_sharpes, dtype=np.float64)
    n_trials = 1 if trials is None else int(trials.size)
    var_sr = float(np.var(trials, ddof=1)) if trials is not None and trials.size >= 2 else 0.0
    q_sr0 = qs.expected_max_sharpe(n_trials, var_sr)
    # RiskLabAI's benchmark uses the population (ddof=0) standard deviation of the trials and,
    # for a single trial, that trial's own Sharpe; it is reported as it computes it.
    r_sr0 = 0.0 if trials is None else float(benchmark_sharpe_ratio(list(trials)))
    out: dict[str, Any] = {
        "n_obs": n, "sharpe": sr, "skew": skew, "kurtosis": kurt, "n_trials": n_trials,
        "trial_sharpe_variance": var_sr,
        "quantowl": {
            "psr": qs.probabilistic_sharpe_ratio(sr, 0.0, n, skew, kurt),
            "expected_max_sharpe": q_sr0,
            "dsr": qs.probabilistic_sharpe_ratio(sr, q_sr0, n, skew, kurt),
        },
        "risklabai": {
            "psr": float(r_psr(sr, 0.0, n, skew, kurt)),
            "expected_max_sharpe": r_sr0,
            "dsr": float(r_psr(sr, r_sr0, n, skew, kurt)),
        },
    }  # fmt: skip
    if sr > 0.0:
        mintrl = float(qs.min_track_record_length(sr, 0.0, skew, kurt, prob))
        out["quantowl"]["min_track_record_length"] = mintrl
        # RiskLabAI has no minTRL; the same formula is checked against its PSR: at T = minTRL
        # its PSR must equal ``prob`` (the definition of minTRL).
        out["risklabai"]["psr_at_min_track_record_length"] = float(
            r_psr(sr, 0.0, mintrl, skew, kurt)
        )
    return out


def pbo(matrix: np.ndarray, n_partitions: int = 16) -> dict[str, Any]:
    """Probability of backtest overfitting (CSCV) from both libraries on the same matrix."""
    m = np.asarray(matrix, dtype=np.float64)
    if m.ndim != 2 or m.shape[1] < 2 or not bool(np.all(np.isfinite(m))):
        raise ContractError("the performance matrix must be finite, T rows x N >= 2 configurations")
    usable = (m.shape[0] // n_partitions) * n_partitions
    trimmed = m[:usable]  # quantowl needs T divisible by S; ALPHA drops the remainder the same way
    q = qpbo.probability_of_backtest_overfitting(trimmed, n_partitions=n_partitions)
    r_value, r_logits = r_pbo(trimmed, n_partitions=n_partitions)
    return {
        "rows_used": usable,
        "quantowl": {"pbo": float(q.pbo), "logits": np.asarray(q.logits).tolist()},
        "risklabai": {"pbo": float(r_value), "logits": np.asarray(r_logits).tolist()},
    }


def strategy_risk(returns: np.ndarray, freq: float, target_sharpe: float) -> dict[str, Any]:
    """Probability that a strategy's precision falls short of what a target Sharpe needs.

    quantowl's ``probability_of_failure`` (AFML 15.4); RiskLabAI's ``implied_precision`` is the
    cross-check of the threshold precision for the same payoffs and frequency.
    """
    r = _returns(returns)
    if not math.isfinite(freq) or freq <= 0.0:
        raise ContractError("freq (bets per year) must be > 0")
    pt, sl = float(r[r > 0].mean()), float(r[r <= 0].mean())
    return {
        "bets": int(r.size), "freq": freq, "target_sharpe": target_sharpe, "pt": pt, "sl": sl,
        "precision": float(np.mean(r > 0)),
        "quantowl": {
            "probability_of_failure": float(qsr.probability_of_failure(r, freq, target_sharpe)),
            "implied_precision": float(qsr.implied_precision(sl, pt, freq, target_sharpe)),
        },
        "risklabai": {
            "implied_precision": float(r_implied_precision(sl, pt, freq, target_sharpe)),
        },
    }  # fmt: skip
