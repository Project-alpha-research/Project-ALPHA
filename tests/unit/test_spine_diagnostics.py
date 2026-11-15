"""Hand-computed diagnostic contracts; no engine or network."""

from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import numpy as np
import pytest

from alpha_cli.spine.diagnostics import (
    concentration,
    delay,
    drawdowns,
    flags,
    performance,
    yearly,
)


def test_drawdown_market_share_and_unrecovered() -> None:
    dates = [datetime(2020, 1, day, tzinfo=UTC) for day in range(1, 5)]
    section = drawdowns([100, 80, 90, 110], [100, 90, 95, 105], dates)
    episode = section["episodes"][0]
    assert episode["depth"] == pytest.approx(-0.2)
    assert episode["benchmark_return"] == pytest.approx(-0.1)
    assert episode["share_explained"] == pytest.approx(0.5)
    assert episode["recovery"] == dates[-1].isoformat()
    episode = drawdowns([100, 80, 90], [100, 110, 105], dates[:3])["episodes"][0]
    assert episode["share_explained"] is None
    assert episode["reasons"]["share_explained"]
    assert episode["recovery"] is None
    assert episode["reasons"]["recovery"]


def test_concentration() -> None:
    result = concentration([5, 3, 2, -2])
    assert result["top_1"] == pytest.approx(5 / 8)
    assert result["top_3"] == pytest.approx(10 / 8)
    for profits in ([1, 2], [1, 2, -4]):
        result = concentration(profits)
        assert result["top_1"] is result["top_3"] is None
        assert result["reasons"]["top_3"]


def test_year_boundary_includes_first_return_in_new_year() -> None:
    dates = [
        datetime(y, m, d, tzinfo=UTC)
        for y, m, d in [(2019, 12, 30), (2019, 12, 31), (2020, 1, 1), (2020, 1, 2)]
    ]
    result = yearly([100, 110, 99, 108.9], [100, 90, 99, 99], dates)
    assert result["years"][0]["strategy_return"] == pytest.approx(0.1)
    assert result["years"][1]["strategy_return"] == pytest.approx(-0.01)
    assert result["years"][1]["benchmark_return"] == pytest.approx(0.1)
    assert result["strategy_positive_years"] == 1


def test_delay_uses_only_prior_weight_and_cost() -> None:
    from alpha_validation.metrics import sharpe_ratio

    returns = np.array([0.1, -0.2, 0.3, 0.4])
    weights = np.array([0, 1, 0, 1])
    costs = np.array([0, 0.01, 0.01, 0.01])
    result = delay(returns, weights, costs, 1)
    assert result["delayed_sharpe"] == pytest.approx(
        sharpe_ratio([0, 0, 0.29, -0.01], periods_per_year=1)
    )
    poisoned = delay(returns, np.array([0, 1, 0, 999]), costs, 1)
    assert poisoned["delayed_sharpe"] == pytest.approx(result["delayed_sharpe"])


def test_performance_flat_is_explained() -> None:
    result = performance([100, 100, 100], 252, "full-sample backtest")
    assert result["sharpe"] is None
    assert result["reasons"]["sharpe"]
    assert result["total_return"] == pytest.approx(0)


@pytest.mark.parametrize("value,expected", [(0.49, True), (0.5, False), (0, True)])
def test_sensitivity_thresholds(value: float, expected: bool) -> None:
    result = flags(
        {
            "full_sample": {"sharpe": 1},
            "benchmark": {"sharpe": 0},
            "sensitivity": {
                "variants": [
                    {"kind": "costs", "sharpe": value},
                    {"kind": "parameter", "sharpe": value},
                ]
            },
            "delay": {"base_sharpe": 1, "delayed_sharpe": value},
            "concentration": {"top_3": 0.79},
            "drawdowns": {"episodes": []},
        }
    )
    names = {item["flag"] for item in result}
    assert ("fragile-to-costs" in names) is expected
    assert ("fragile-to-parameters" in names) is expected
    assert ("fragile-to-delay" in names) is expected


def test_audit_missing_traces_and_thresholds() -> None:
    from alpha_cli.spine.audit import audit

    result = audit(
        None,
        None,
        None,
        {},
        fee=0,
        slippage=2,
        trades=29,
        years=2.9,
        labels=["quick"],
        benchmark=False,
        variants=5,
    )
    checks = {item["check"]: item for item in result}
    assert len(checks) == 9
    assert checks["fills-after-decisions"]["status"] == "NOT-CHECKED"
    for name in (
        "costs-charged",
        "enough-trades",
        "history-length",
        "quick-run",
        "benchmark-present",
    ):
        assert checks[name]["status"] == "FLAG"
    assert checks["variants-counted"]["status"] == "PASS"
    assert "5" in checks["variants-counted"]["detail"]


def test_audit_matches_fill_to_its_order_and_decision() -> None:
    import polars as pl

    from alpha_cli.spine.audit import audit

    dates = [datetime(2020, 1, day, tzinfo=UTC) for day in range(1, 4)]
    decisions = pl.DataFrame({"sequence_id": [1, 2], "ts": dates[:2]})
    orders = pl.DataFrame({"sequence_id": [10], "decision_sequence_id": [2]})
    fills = pl.DataFrame({"order_sequence_id": [10], "ts": [dates[1]], "price": [11.0]})
    audit_fills = partial(
        audit, fee=1, slippage=2, trades=30, years=3, labels=[], benchmark=True, variants=1
    )
    checks = {v["check"]: v for v in audit_fills(decisions, orders, fills, {dates[1]: (9.0, 10.0)})}
    assert checks["fills-after-decisions"]["status"] == "FLAG"
    assert checks["fills-inside-bar-range"]["status"] == "FLAG"
    fills = pl.DataFrame({"order_sequence_id": [10], "ts": [dates[2]], "price": [10.0]})
    checks = {v["check"]: v for v in audit_fills(decisions, orders, fills, {dates[2]: (9.0, 10.0)})}
    assert checks["fills-after-decisions"]["status"] == "PASS"
    assert checks["fills-inside-bar-range"]["status"] == "PASS"
    for name in (
        "costs-charged",
        "enough-trades",
        "history-length",
        "quick-run",
        "benchmark-present",
    ):
        assert checks[name]["status"] == "PASS"


def test_variants_skip_equal_and_invalid_neighbours() -> None:
    from alpha_cli.spine.diagnose import variant_specs
    from alpha_cli.spine.run import assemble_run_spec
    from alpha_cli.spine.spec import load_spec

    idea = load_spec(None, rule="ma_cross", param=["fast=4", "slow=5"], asset=["SPY"])
    spec = assemble_run_spec(idea, "SPY", 252, 100)
    variants = variant_specs(idea, spec)
    assert len(variants) == 3  # costs, fast=3, slow=6; fast=5 and slow=4 are invalid
    assert variants[0][2].fee_bps == pytest.approx(2)
    assert variants[0][2].slippage_bps == pytest.approx(4)


def test_ledger_accepts_old_and_new_variant_rows(tmp_path: Path) -> None:
    from alpha_cli.spine.ledger import append_trial, read_trials

    append_trial(tmp_path, {"run_id": "old", "labels": []})
    append_trial(tmp_path, {"run_id": "new", "labels": [], "variants_evaluated": 5})
    rows = read_trials(tmp_path)
    assert "variants_evaluated" not in rows[0]
    assert rows[1]["variants_evaluated"] == 5


@pytest.mark.parametrize(
    "share,top,benchmark,expected", [(0.5, 0.8, 2, True), (0.49, 0.79, 1, False)]
)
def test_observation_thresholds(share: float, top: float, benchmark: float, expected: bool) -> None:
    result = flags(
        {
            "full_sample": {"sharpe": 1},
            "benchmark": {"sharpe": benchmark},
            "sensitivity": {"variants": []},
            "delay": {"base_sharpe": 1, "delayed_sharpe": 1},
            "concentration": {"top_3": top},
            "drawdowns": {"episodes": [{"share_explained": share, "benchmark_return": -0.2}]},
        }
    )
    names = {item["flag"] for item in result}
    for name in ("below-benchmark", "drawdown-with-market", "concentrated-profit"):
        assert (name in names) is expected


def test_trials_normalize_each_frequency_and_count_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from alpha_cli.spine import diagnose
    from alpha_cli.spine.ledger import append_trial

    append_trial(tmp_path, {"symbol": "SPY", "labels": [], "oos_sharpe": 2, "periods_per_year": 4})
    append_trial(
        tmp_path, {"symbol": "OTHER", "labels": [], "oos_sharpe": 999, "periods_per_year": 1}
    )
    seen: list[float] = []

    def dsr(returns: object, *, trial_sharpes: list[float]) -> SimpleNamespace:
        seen.extend(trial_sharpes)
        return SimpleNamespace(dsr=0.75)

    monkeypatch.setattr(diagnose, "deflated_sharpe", dsr)
    result = diagnose.trials(tmp_path, "SPY", [0.1, -0.1, 0.2], 4, [{"sharpe": 4}])
    assert result["total_trials"] == 3
    assert result["dsr"] == pytest.approx(0.75)
    assert seen[0] == pytest.approx(1)
    assert seen[-1] == pytest.approx(2)
    result = diagnose.trials(tmp_path / "empty", "SPY", [0.1, -0.1, 0.2], 4, [])
    assert result["dsr"] is None
    assert result["reasons"]["dsr"]


def test_performance_hand_computed() -> None:
    # Algebraic identities; abs=1e-12 allows binary rounding around zero.
    result = performance([100, 110, 99], 2, "synthetic")
    assert result["total_return"] == pytest.approx(-0.01)
    assert result["cagr"] == pytest.approx(-0.01)
    assert result["max_drawdown"] == pytest.approx(-0.1)
    assert result["sharpe"] == pytest.approx(0, abs=1e-12)


def _flag_sections(base: float | None, delayed: float, variant: float) -> dict:
    return {
        "full_sample": {"sharpe": base},
        "benchmark": {"sharpe": None},
        "sensitivity": {"variants": [{"kind": "costs", "sharpe": variant}]},
        "delay": {"base_sharpe": base, "delayed_sharpe": delayed},
        "concentration": {"top_3": None},
        "drawdowns": {"episodes": []},
    }


@pytest.mark.parametrize("base", [-1.0, 0.0, float("inf"), float("nan")])
def test_delay_flag_needs_a_positive_finite_base(base: float) -> None:
    # A delayed Sharpe of -0.8 is "below half" of a base of -1 arithmetically; that is no finding.
    names = {item["flag"] for item in flags(_flag_sections(base, -0.8, 0.3))}
    assert "fragile-to-delay" not in names
    assert {item["flag"] for item in flags(_flag_sections(1.0, 0.4, 0.6))} == {"fragile-to-delay"}


def test_negative_base_does_not_make_a_better_variant_fragile() -> None:
    assert flags(_flag_sections(-1.0, -1.0, -0.8)) != []  # a losing variant is still flagged
    assert flags(_flag_sections(-1.0, -1.0, 0.2)) == []
    assert flags(_flag_sections(2.0, 2.0, 0.9))[0]["flag"] == "fragile-to-costs"


def test_flag_text_never_prints_none() -> None:
    (flag,) = flags(_flag_sections(None, 0.0, -0.2))
    assert flag["flag"] == "fragile-to-costs"
    assert "None" not in flag["detail"]
    assert flag["detail"].endswith("base Sharpe is unavailable.")
    (rounded,) = flags(_flag_sections(1.23456, 1.0, 0.1))
    assert rounded["detail"].endswith("base Sharpe is 1.23.")


def test_delay_share_is_null_with_a_reason_unless_base_is_positive() -> None:
    returns = np.array([0.01, 0.03, -0.01, 0.02, 0.01, -0.02])
    costs = np.zeros(6)
    winning = delay(returns, np.ones(6), costs, 252)
    assert winning["base_sharpe"] > 0
    assert winning["delayed_share_of_base"] == pytest.approx(
        winning["delayed_sharpe"] / winning["base_sharpe"]
    )
    assert "delayed_share_of_base" not in winning["reasons"]
    losing = delay(-returns, np.ones(6), costs, 252)
    assert losing["base_sharpe"] < 0
    assert losing["delayed_share_of_base"] is None
    assert "not positive" in losing["reasons"]["delayed_share_of_base"]
    flat = delay(returns, np.zeros(6), costs, 252)
    assert flat["delayed_share_of_base"] is None
    assert "unavailable" in flat["reasons"]["delayed_share_of_base"]
