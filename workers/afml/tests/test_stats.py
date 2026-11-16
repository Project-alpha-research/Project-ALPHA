"""Checks for wave 1 item 6: PSR, DSR, PBO, minimum track record and strategy risk."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats as ss
from shared_fixtures import SEED

from alpha_afml_worker.contract import ContractError
from alpha_afml_worker.stats import pbo, sharpe_stats, strategy_risk


@pytest.fixture(scope="module")
def returns() -> np.ndarray:
    return np.random.default_rng(SEED).normal(0.0006, 0.01, 800)


def test_psr_by_hand_and_both_libraries(returns: np.ndarray) -> None:
    out = sharpe_stats(returns)
    sr, n = out["sharpe"], out["n_obs"]
    skew, kurt = out["skew"], out["kurtosis"]
    z = sr * math.sqrt(n - 1) / math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr * sr)
    assert out["quantowl"]["psr"] == pytest.approx(ss.norm.cdf(z), abs=1e-12)
    assert out["risklabai"]["psr"] == pytest.approx(out["quantowl"]["psr"], abs=1e-12)


def test_dsr_difference_is_only_the_trial_variance_ddof(returns: np.ndarray) -> None:
    trials = np.random.default_rng(SEED + 1).normal(0.02, 0.03, 20)
    out = sharpe_stats(returns, trials)
    q, r = out["quantowl"]["expected_max_sharpe"], out["risklabai"]["expected_max_sharpe"]
    # RiskLabAI takes the population standard deviation (ddof=0); quantowl and ALPHA ddof=1.
    assert r == pytest.approx(q * math.sqrt((trials.size - 1) / trials.size), rel=1e-12)
    assert out["risklabai"]["dsr"] > out["quantowl"]["dsr"]  # a lower bar gives a higher DSR


def test_min_track_record_length_hits_the_target_psr(returns: np.ndarray) -> None:
    out = sharpe_stats(returns)
    assert out["quantowl"]["min_track_record_length"] > 1
    assert out["risklabai"]["psr_at_min_track_record_length"] == pytest.approx(0.95, abs=1e-12)


def test_pbo_libraries_agree_on_noise() -> None:
    matrix = np.random.default_rng(SEED).normal(0.0, 0.01, (800, 10))
    out = pbo(matrix, 16)
    assert out["quantowl"]["pbo"] == pytest.approx(out["risklabai"]["pbo"], abs=1e-12)
    assert np.allclose(out["quantowl"]["logits"], out["risklabai"]["logits"], atol=1e-10)


def test_strategy_risk_implied_precision_agrees() -> None:
    bets = np.random.default_rng(SEED).normal(0.002, 0.02, 300)
    out = strategy_risk(bets, freq=50.0, target_sharpe=1.0)
    q, r = out["quantowl"]["implied_precision"], out["risklabai"]["implied_precision"]
    assert q == pytest.approx(r, abs=1e-10)
    assert 0.0 <= out["quantowl"]["probability_of_failure"] <= 1.0


def test_bad_input_fails_loud() -> None:
    with pytest.raises(ContractError):
        sharpe_stats(np.ones(10))
    with pytest.raises(ContractError):
        pbo(np.ones((100, 1)))
