"""The family classifier on the real composite proposals of the second and third wide runs.

The proposals' keys and values are copied verbatim from the runs' logs, so these tests judge the
inputs the proposer really wrote, not a tidied synthetic version of them.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from tests.unit._rdagent_real_proposals import PROPOSALS
from tests.unit._rdagent_support import WIDE_RUN_CLOSED, judge_namespace
from tests.unit.test_rdagent_factor_judge import swing_parts
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


# Abridged from the real 2026-11-17 proposal `ml_ridge_composite_28d` (run
# 2026-11-17-rdagent-spread-check, rounds.jsonl iteration 0): its own words and variables.
REAL_COMPOSITE: dict[str, Any] = {
    "name": "ml_ridge_composite_28d",
    "description": "[Machine Learning based Factor] Walk-forward cross-sectional ridge "
    "composite of slow OHLCV features, trained to predict the cross-sectional rank of the next "
    "28-day open-to-open return.",
    "formulation": "m20_{i,t}=ln(C_t/C_{t-20}), vol60_{i,t}=sqrt(...), hp120_{i,t}=C/max H-1, "
    "skew60_{i,t}=..., mdd120_{i,t}=..., ac60_{i,t}=...; f_{i,t}=x_{i,t}^T beta",
    "variables": {
        "ac60_{i,t}": "Lag-1 autocorrelation of the trailing 60 daily log returns.",
        "hp120_{i,t}": "120-day high proximity: close divided by trailing 120-day high minus one.",
        "m20_{i,t}": "20-day log momentum feature.",
        "mdd120_{i,t}": "Maximum peak-to-trough drawdown of close over the trailing 120 days.",
        "skew60_{i,t}": "Adjusted sample skewness of the trailing 60 daily log returns.",
        "vol60_{i,t}": "60-day realized volatility of daily log returns.",
        "vt60_{i,t}": "60-day volume trend: log ratio of 20-day to 60-day mean volume.",
    },
}


def _family(ns: dict[str, Any], row: dict[str, Any]) -> set[str]:
    args = (row["name"], row.get("description", ""), row.get("formulation", ""))
    return set(ns["idea_family"](*args, row.get("variables")).split("; "))


def test_ridge_composite_inherits_every_input_family() -> None:
    ns = swing_parts()
    families = _family(ns, REAL_COMPOSITE)
    assert {
        "volatility and beta",
        "drawdown",
        "skewness and lottery returns",
        "past return (momentum or reversal)",
    } <= families
    # Before the fix this composite was filed as "other: ml" and escaped every family.
    assert not any(family.startswith("other") for family in families)
    # Three failed volatility tries close that family; the composite is named in it, so the
    # proposer is told to leave composites that use it too.
    volatility = {"schema": "AlphaRdagentFactorTrialV2", "status": "SCREEN_FAIL", "screen": {}}
    rows = [{**volatility, "name": f"volatility_{n}d"} for n in (20, 40)]
    rows.append({**REAL_COMPOSITE, "schema": "AlphaRdagentFactorTrialV2", "status": "SCREEN_FAIL"})
    rows[-1]["screen"] = {}
    summary = ns["family_summary"](rows, 3)
    closed = summary.split("no candidate: ")[1]
    assert "volatility and beta" in closed and "composites using ANY" in summary
    assert "- drawdown: 1 try" in summary


def test_composite_family_cannot_be_dodged_by_renaming() -> None:
    ns = swing_parts()
    renamed = {**REAL_COMPOSITE, "name": "signal_alpha_x"}
    assert _family(ns, renamed) == _family(ns, REAL_COMPOSITE)
    plain: dict[str, Any] = {
        "name": "factor_a",
        "description": "Weighted sum of volatility and skewness ranks",
    }
    # Prose may say it is a mix but never supplies families: with no listed input names it
    # is its own "composite: unknown inputs" family, never silently an open "other: ...".
    assert _family(ns, plain) == {"composite: unknown inputs"}
    plain["variables"] = {"volatility": "rank", "skewness": "rank"}
    assert _family(ns, plain) == {"volatility and beta", "skewness and lottery returns"}
    unknown = {"name": "ml_ridge_composite_7d"}  # the real ledger rows carry no description
    assert _family(ns, unknown) == {"composite: unknown inputs"}


def test_single_family_factor_keeps_its_family() -> None:
    ns = swing_parts()
    cases = {
        "amihud_illiquidity_20d": "Mean absolute return per dollar volume over 20 days.",
        "vol_adjusted_momentum_28d": "28-day momentum divided by 60-day volatility.",
        "range_compression_10d": "High-low range over its 60-day mean; a strange arrangement.",
    }
    families = {
        name: _family(ns, {"name": name, "description": text}) for name, text in cases.items()
    }
    assert families == {
        "amihud_illiquidity_20d": {"illiquidity"},
        "vol_adjusted_momentum_28d": {"past return (momentum or reversal)"},
        "range_compression_10d": {"range and compression"},
    }


@pytest.mark.parametrize(
    "name,description,variables,expected",
    [
        (
            "gradient_boosted_mix",
            "mix of inputs",
            {"momentum_30d": "x", "volatility_30d": "x", "volume_30d": "x", "high_prox_30d": "x"},
            "past return (momentum or reversal); price near its high / range position; "
            "volatility and beta; volume level and trend",
        ),
        (
            "price_delay_120d",
            "OLS regression beta slope residual momentum volatility",
            {},
            "other: price_delay",
        ),
        (
            "btc_lag_spillover_5_120d",
            "regression against market beta and volume",
            {},
            "other: btc_lag_spillover",
        ),
        (
            "lightgbm_mix",
            "model using features",
            {"long_term_reversal": "momentum regression", "vwap_distance": "volume weighted"},
            "VWAP distance; past return (momentum or reversal)",
        ),
        ("volume weighted average price distance", "volume trend", {}, "VWAP distance"),
    ],
)
def test_real_proposals_classify_construct_names(
    name: str, description: str, variables: dict[str, str], expected: str
) -> None:
    assert (
        judge_namespace()["idea_family"](name, description, "volume * volatility", variables)
        == expected
    )


def test_single_construct_has_one_family_and_named_abbreviations() -> None:
    family = judge_namespace()["idea_family"]
    assert family("vol_adjusted_momentum_28d") == "past return (momentum or reversal)"
    assert family("vol_scaled_high_prox_252d") == "price near its high / range position"
    assert (
        family("ridge_mix", variables={"vol60": "unread", "mdd120": "unread", "ac60": "unread"})
        == "drawdown; past return (momentum or reversal); volatility and beta"
    )


WIDE_RUN_PROPOSALS: list[tuple[str, str, list[str], bool]] = [
    (
        "gbm_spread_7d",
        "[Machine Learning based Factor] Strictly causal spread-aware gradient-boosted "
        "cross-sectional factor for the 7-day horizon.",
        ["C_{i,s", "H_{i,s", "V_{i,s", "r_{i,s", "m20_{i,t", "m60_{i,t", "vol60_{i,t"]
        + ["vt60_{i,t", "ldv60_{i,t", "hp120_{i,t", "RV60_{i,t", "jv60_{i,t", "svi20_{i,t"]
        + ["R_{i,t", "rank_mom20_{i,t", "m(t)", "D_{m(t)}", "h", "20", "max_depth"],
        True,
    ),
    (
        "price_delay_120d",
        "[Information-Diffusion / Price-Delay Factor] Slow price-delay measure for each coin, "
        "computed as one minus the ratio of the R-squared from a contemporaneous-market "
        "regression to the R-squared from a full distributed-lag regression.",
        ["C_{i,s}", "r_{i,s}", "A_s", "N_s", "m_s", "t", "W_t", "120", "R^2_{full,i,t}"],
        False,
    ),
    (
        "btc_lag_spillover_5_120d",
        "[Lead-Lag Spillover / BTC Factor] For each lag, estimate the OLS slope beta_{i,l,t} of "
        "coin i's daily log return on BTC's l-day-lagged daily log return.",
        ["C_{i,s}", "C_{BTC,s}", "r_{i,s}", "r_{BTC,s}", "\\beta_{i,l,t}", "\\bar{r}_{i,t}"],
        False,
    ),
    (
        "ml_gbdt_topthird_28d",
        "[Machine Learning based Factor] Strictly causal LightGBM binary classifier for the "
        "28-day horizon over long-term reversal ltr and VWAP distance vwap.",
        ["C_{i,s}", "O_{i,s}", "V_{i,s}", "h", "L", "ltr_{i,t}", "vwap_{i,t}", "m(t)"]
        + ["D_{m(t)}", "num_leaves", "learning_rate", "p_{i,t}", "rank_t", "f_{i,t}"],
        True,
    ),
    (
        "max_drawdown_252d",
        "[Distress / Drawdown Factor] Maximum peak-to-trough close drawdown over 252 days.",
        ["C_{i,s}", "t", "252", "a", "b", "f_{i,t}"],
        False,
    ),
]


@pytest.mark.parametrize("name,description,variables,refused", WIDE_RUN_PROPOSALS)
def test_wide_run_proposals_with_their_real_variable_lists(
    name: str, description: str, variables: list[str], refused: bool
) -> None:
    family = judge_namespace()["idea_family"](
        name, description, "", dict.fromkeys(variables, "proposer text")
    )
    assert bool(set(family.split("; ")) & WIDE_RUN_CLOSED) is refused, family
    assert "other: c_" not in family and "other: m" not in family


def test_real_logistic_inputs_stay_open() -> None:
    names = [
        "price_delay",
        "lead_lag_score",
        "lag_lag_score",
        "delay_beta_ratio",
        "hurst",
        "entropy",
    ]
    family = judge_namespace()["idea_family"](
        "logistic_mix", "mix of features", "", dict.fromkeys(names, "feature")
    )
    assert set(family.split("; ")) == {"other: " + name for name in names}


def test_placeholder_values_name_real_inputs() -> None:
    inputs = [
        "ltr_189d_skip21d",
        "max_drawdown_252d",
        "vwap_distance_189d",
        "overnight_drift_60d",
        "variance_ratio_5_120d",
    ]
    variables = {
        f"x{i}_i_s": f"feature {name}, ranked at close" for i, name in enumerate(inputs, 1)
    }
    family = judge_namespace()["idea_family"]("ridge_mix", variables=variables)
    assert set(family.split("; ")) == {
        "past return (momentum or reversal)",
        "drawdown",
        "VWAP distance",
        "other: overnight_drift",
        "other: variance_ratio",
    }


def test_math_symbols_ignored_and_closed_input_retained() -> None:
    family = judge_namespace()["idea_family"]
    symbols = dict.fromkeys(["C", "O", "r", "m_s", "c_i_s", "sigma", "beta"], "momentum prose")
    assert family("ridge_mix", variables=symbols) == "composite: unknown inputs"
    assert (
        family("ridge_mix", variables={**symbols, "mom_60d": "x"})
        == "past return (momentum or reversal)"
    )


@pytest.mark.parametrize(
    "variables,refused",
    [
        (
            dict.fromkeys(
                [
                    "price_delay",
                    "lead_lag_score",
                    "lag_lag_score",
                    "delay_beta_ratio",
                    "hurst",
                    "entropy",
                ],
                "feature",
            ),
            False,
        ),
        (
            {
                f"x{i}_i_s": name
                for i, name in enumerate(
                    [
                        "ltr_189d_skip21d",
                        "max_drawdown_252d",
                        "vwap_distance_189d",
                        "overnight_drift_60d",
                        "variance_ratio_5_120d",
                    ],
                    1,
                )
            },
            True,
        ),
        ({"mom_60d": "momentum"}, True),
    ],
)
def test_third_run_proposals_at_coding_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variables: dict[str, str], refused: bool
) -> None:
    from tests.unit._rdagent_support import WIDE_RUN_CLOSED, proposal

    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    ns = judge_namespace()
    ns["closed_families"] = lambda: WIDE_RUN_CLOSED
    exp = proposal("ridge_mix", "")
    exp.sub_tasks[0].variables = variables
    coder = SimpleNamespace(develop=Mock(return_value="coded"))
    guard = ns["FamilyGuard"](coder)
    if refused:
        with pytest.raises(ValueError, match=r"past return \(momentum or reversal\)"):
            guard.develop(exp)
        coder.develop.assert_not_called()
    else:
        assert guard.develop(exp) == "coded"
        coder.develop.assert_called_once_with(exp)
