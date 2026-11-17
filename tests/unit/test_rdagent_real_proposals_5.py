"""The family classifier on the real composite proposals of the second and third wide runs.

The proposals' keys and values are copied verbatim from the runs' logs, so these tests judge the
inputs the proposer really wrote, not a tidied synthetic version of them.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit._rdagent_real_proposals import PROPOSALS
from tests.unit.test_rdagent_loop_fixups_4 import WIDE_RUN_CLOSED
from workers.rdagent import idea_families


def families(name: str, variables: Any = None) -> set[str]:
    proposal = PROPOSALS[name]
    return set(
        idea_families.idea_family(
            name,
            proposal["description"],
            proposal["formulation"],
            proposal["variables"] if variables is None else variables,
        ).split("; ")
    )


def test_run3_logistic_diffusion_mix_reads_exactly_its_six_named_inputs() -> None:
    names = ("price_delay", "delay_beta_ratio", "lead_lag_score", "lag_lag_score", "hurst")
    assert families("ml_logit_top3_diffusion_7d") == {"other: " + n for n in (*names, "entropy")}
    assert not families("ml_logit_top3_diffusion_7d") & WIDE_RUN_CLOSED


def test_run3_placeholder_mix_reads_the_inputs_its_values_name() -> None:
    assert families("ml_logit_topthird_weekly_open") == {
        "past return (momentum or reversal)",
        "drawdown",
        "VWAP distance",
        "other: overnight_drift",
        "other: variance_ratio",
    }


def test_run3_ridge_mix_and_run2_gbdt_mix_keep_only_feature_names() -> None:
    assert families("cs_ridge_openfam_7d") == {
        "past return (momentum or reversal)",
        "drawdown",
        "VWAP distance",
    }
    assert families("ml_gbdt_topthird_7d") == {
        "past return (momentum or reversal)",
        "VWAP distance",
    }


def test_run2_gradient_boosted_mix_is_still_refused_without_junk_families() -> None:
    found = families("gbm_spread_7d")
    assert found == {
        "past return (momentum or reversal)",
        "volatility and beta",
        "volume level and trend",
        "price near its high / range position",
    }
    assert found & WIDE_RUN_CLOSED


def test_run2_price_delay_regression_stays_one_construct() -> None:
    # A regression is a composite only when it lists two keyword-recognised features; its
    # regression statistics (SSR, SST, R^2) are not features.
    assert families("price_delay_120d") == {"other: price_delay"}


def test_a_closed_feature_added_to_a_real_mix_is_refused() -> None:
    variables = {**PROPOSALS["ml_logit_top3_diffusion_7d"]["variables"], "mom_60d_{i,t}": "x"}
    assert "past return (momentum or reversal)" in families("ml_logit_top3_diffusion_7d", variables)


@pytest.mark.parametrize(
    "symbol",
    [
        "r_1",
        "x_{i,s,j}",
        "b_0",
        "W_1_99",
        "y_raw_{i,s}",
        "\\hat y_{i,t}",
        "tilde_x_i_s_j",
        "R^2_{full,i,t}",
        "SSR_{full}",
        "SST",
        "10^{-12}",
        "252_min_dates",
        "rank_t",
        "n_estimators",
        "max_iter",
        "l2_regularization",
        "min_samples_leaf",
        "colsample_bytree",
        "subsample",
        "reg_lambda",
        "refit_frequency",
        "s=t-279,...,t-28",
    ],
)
def test_math_symbols_targets_and_settings_never_make_a_family(symbol: str) -> None:
    variables = {symbol: "x", "hurst_{i,t}": "Hurst exponent"}
    assert idea_families.idea_family("ridge_mix", variables=variables) == "other: hurst"


def test_prose_in_a_placeholder_value_is_not_an_input() -> None:
    # "rolling_20d mean" is prose about how an input is built, not an input name; a placeholder
    # whose value names no input is unreadable and cannot hide a closed family's feature.
    hidden = {"x1": "the rolling_20d mean of 60-day momentum", "x2": "hurst_120d"}
    found = set(idea_families.idea_family("ridge_mix", variables=hidden).split("; "))
    assert found == {"composite: unknown inputs", "other: hurst"}
    assert found & WIDE_RUN_CLOSED


def test_unknown_inputs_only_when_a_feature_input_is_unnamed() -> None:
    symbols = dict.fromkeys(["C", "O", "r", "m_s", "c_i_s", "sigma", "beta", "rank_t"], "x")
    assert idea_families.idea_family("ridge_mix", variables=symbols) == "composite: unknown inputs"
    assert idea_families.idea_family("ridge_mix", variables={**symbols, "hurst": "x"}) == (
        "other: hurst"
    )


def test_a_composite_name_still_contributes_its_families() -> None:
    found = idea_families.idea_family("momentum_vol_ensemble", variables={"hurst": "x"})
    assert set(found.split("; ")) == {
        "past return (momentum or reversal)",
        "volatility and beta",
        "other: hurst",
    }


def test_ledger_ridge_mix_with_comma_indices_keeps_its_closed_features() -> None:
    # Real keys of the recorded ml_ridge_composite_7d_resid trial: indices written "_i,t".
    keys = ["1/99", "120", "C_i,s", "D_m(t)", "W_1,99", "ac60_i,t", "alpha", "amihud60_i,t"]
    keys += ["e_i,s", "f_i,t", "hp120_i,t", "m(t)", "m20_i,s", "m60_i,s", "mdd120_i,t"]
    keys += ["min_cross_section", "r_i,s", "rank_s", "skew60_i,t", "vol60_i,s", "vt60_i,t"]
    keys += ["x_i,s,j", "y_i,s", "y_raw_i,s", "z_s"]
    found = idea_families.idea_family("ml_ridge_composite_7d_resid", "ridge", "", keys)
    assert set(found.split("; ")) == {
        "drawdown",
        "illiquidity",
        "past return (momentum or reversal)",
        "price near its high / range position",
        "skewness and lottery returns",
        "volatility and beta",
        "volume level and trend",
    }


def test_an_input_matching_two_families_counts_for_both() -> None:
    # Real keys of the recorded ml_huber_causal_7d trial: volume_autocorr is a volume and an
    # autocorrelation feature, so a mix using it inherits both families, as before this change.
    keys = ["C_{i,s}", "L_delta", "b_0", "entropy_{i,t}", "hat y_{i,t}", "hurst_{i,t}"]
    keys += ["lower_shadow_{i,t}", "rank_t", "upper_shadow_{i,t}", "volume_autocorr_{i,t}"]
    keys += ["volume_skew_{i,t}", "x_{i,s,j}", "y_{i,s}", "z_{i,s,j}"]
    found = idea_families.idea_family("ml_huber_causal_7d", "ridge", "", keys)
    assert set(found.split("; ")) == {
        "past return (momentum or reversal)",
        "skewness and lottery returns",
        "volume level and trend",
        "other: entropy",
        "other: hurst",
        "other: lower_shadow",
        "other: upper_shadow",
    }
