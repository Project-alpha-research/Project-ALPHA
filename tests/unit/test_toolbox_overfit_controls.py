"""Overfitting controls: known answers from the published formulas, short histories, repeats."""

import json
import math
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from scipy import stats
from statsmodels.stats.proportion import proportion_confint

from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox.inputs import Inputs, resolve
from alpha_cli.toolbox.registry import get
from alpha_cli.toolbox.runner import run
from tests.unit.test_spine_tools import RUN
from tests.unit.test_toolbox_resampling_checks import write_equity
from tests.unit.test_toolbox_run_level_checks import END, START, stored_run, write_trades

PSR = "overfit_controls.probabilistic_sharpe"
MINTRL = "overfit_controls.min_track_record"
HAIRCUT = "overfit_controls.haircut_sharpe"
MINBTL = "overfit_controls.min_backtest_length"
NOISE = "overfit_controls.noise_best_sharpe"
DEFLATED = "overfit_controls.deflated_at_tries"
HURDLE = "overfit_controls.t_stat_hurdle"
TRADES = "overfit_controls.trade_count"
POWER = "overfit_controls.required_history"
SPRT = "overfit_controls.sequential_test"
SHRINK = "overfit_controls.shrunk_sharpe"
TOOLS = (PSR, MINTRL, HAIRCUT, MINBTL, NOISE, DEFLATED, HURDLE, TRADES, POWER, SPRT, SHRINK)
PPY = 365  # the stored_run manifest's periods per year
TESTS = "tests/unit/test_toolbox_overfit_controls.py::"


def returns_sample() -> np.ndarray:
    return np.random.default_rng(11).normal(0.0008, 0.01, 400)


def prepare(home: Path, returns: np.ndarray | None = None, tries: int | None = 9) -> np.ndarray:
    data = returns_sample() if returns is None else returns
    folder = stored_run(home, PSR)
    write_equity(folder, np.r_[1.0, np.cumprod(1.0 + data)])
    pnls = [2.0, -1.0, 3.0, -1.0, 1.5, 2.0, -0.5, 1.0, -1.0, 2.5] * 3
    write_trades(folder, pnls, ["BUY"] * len(pnls))
    if tries is not None:
        path = folder / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["dsr"] = {"family_id": "f", "n_trials": tries}
        path.write_text(json.dumps(manifest))
    return data


def go(home: Path, tool: str, *settings: str) -> dict[str, Any]:
    """Run one tool; a setting the tool does not have (a shared n_trials) is left out."""
    names = {p.name for p in get(tool).params}
    return run(home, tool, RUN, [s for s in settings if s.partition("=")[0] in names])


def stats_of(data: np.ndarray) -> tuple[int, float, float]:
    n = len(data)
    sr_bar = float(data.mean() / data.std(ddof=1))
    return n, sr_bar, sr_bar * math.sqrt(PPY)


def test_probabilistic_sharpe(tmp_path: Path) -> None:
    data = prepare(tmp_path)
    n, sr, annual = stats_of(data)
    skew = float(stats.skew(data, bias=True))
    kurt = float(stats.kurtosis(data, fisher=False, bias=True))
    variance = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    bench = 0.5 / math.sqrt(PPY)
    expected = stats.norm.cdf((sr - bench) * math.sqrt(n - 1) / math.sqrt(variance))
    doc = go(tmp_path, PSR, "benchmark_sharpe=0.5")
    assert doc["values"]["probability"] == pytest.approx(expected, rel=1e-9, abs=1e-12)
    assert doc["values"]["sharpe"] == pytest.approx(annual, rel=1e-9, abs=1e-12)
    assert doc["values"]["bars"] == n


def test_min_track_record(tmp_path: Path) -> None:
    data = prepare(tmp_path)
    n, sr, _ = stats_of(data)
    skew = float(stats.skew(data, bias=True))
    kurt = float(stats.kurtosis(data, fisher=False, bias=True))
    z = stats.norm.ppf(0.95)
    expected = 1.0 + (1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr) * (z / sr) ** 2
    doc = go(tmp_path, MINTRL)
    assert doc["values"]["min_bars"] == pytest.approx(expected, rel=1e-9, abs=1e-12)
    assert doc["values"]["min_years"] == pytest.approx(expected / PPY, rel=1e-9, abs=1e-12)
    assert doc["values"]["bars"] == n


def test_min_track_record_needs_a_positive_gap(tmp_path: Path) -> None:
    prepare(tmp_path, -returns_sample() + 0.0005)
    doc = go(tmp_path, MINTRL)
    assert doc["values"]["min_bars"] is None
    assert "above" in doc["reasons"]["min_bars"]


def test_haircut_sharpe(tmp_path: Path) -> None:
    data = prepare(tmp_path)
    n, sr, annual = stats_of(data)
    years = n / PPY
    t_stat = sr * math.sqrt(n)
    p = 2.0 * (1.0 - stats.norm.cdf(t_stat))
    adjusted_p = min(1.0, 9 * p)
    adjusted = stats.norm.ppf(1.0 - adjusted_p / 2.0) / math.sqrt(years)
    doc = go(tmp_path, HAIRCUT)  # the nine recorded tries
    values = doc["values"]
    assert values["trials"] == 9
    assert values["t_stat"] == pytest.approx(t_stat, rel=1e-9, abs=1e-12)
    assert values["p_value"] == pytest.approx(p, rel=1e-9, abs=1e-12)
    assert values["adjusted_p_value"] == pytest.approx(adjusted_p, rel=1e-9, abs=1e-12)
    assert values["adjusted_sharpe"] == pytest.approx(adjusted, rel=1e-9, abs=1e-12)
    assert values["haircut"] == pytest.approx((annual - adjusted) / annual, rel=1e-9, abs=1e-12)
    again = go(tmp_path, HAIRCUT, "n_trials=2")
    assert again["values"]["trials"] == 2


def test_haircut_removes_all_evidence_when_the_adjusted_p_value_is_one(tmp_path: Path) -> None:
    raw = np.random.default_rng(5).normal(0.0, 0.01, 400)
    data = raw - raw.mean() + 0.3 * raw.std(ddof=1) / math.sqrt(400)  # t-statistic of 0.3
    prepare(tmp_path, data)
    values = go(tmp_path, HAIRCUT)["values"]
    assert values["adjusted_p_value"] == 1.0
    assert values["adjusted_sharpe"] == pytest.approx(0.0, abs=1e-12)
    assert values["haircut"] == pytest.approx(1.0, rel=1e-9, abs=1e-12)


def test_min_backtest_length_hand_answer(tmp_path: Path) -> None:
    prepare(tmp_path)
    doc = go(tmp_path, MINBTL, "n_trials=100", "target_sharpe=1.0")
    # 2 ln(100) / 1^2 years.
    assert doc["values"]["min_years"] == pytest.approx(2.0 * math.log(100), rel=1e-9, abs=1e-12)
    assert doc["values"]["run_years"] == pytest.approx(400 / PPY, rel=1e-9, abs=1e-12)


def test_min_backtest_length_defaults_to_the_run_sharpe(tmp_path: Path) -> None:
    data = prepare(tmp_path)
    _, _, annual = stats_of(data)
    doc = go(tmp_path, MINBTL)
    assert doc["values"]["trials"] == 9
    assert doc["values"]["target_sharpe"] == pytest.approx(annual, rel=1e-9, abs=1e-12)
    assert doc["values"]["min_years"] == pytest.approx(
        2.0 * math.log(9) / annual**2, rel=1e-9, abs=1e-12
    )


def noise_max(n: int, tries: int) -> float:
    gamma = 0.5772156649015329
    term = (1 - gamma) * stats.norm.ppf(1 - 1 / tries) + gamma * stats.norm.ppf(
        1 - 1 / (tries * math.e)
    )
    return float(term / math.sqrt(n) * math.sqrt(PPY))


def test_noise_best_sharpe(tmp_path: Path) -> None:
    data = prepare(tmp_path)
    n, _, annual = stats_of(data)
    doc = go(tmp_path, NOISE, "n_trials=50")
    assert doc["values"]["noise_sharpe"] == pytest.approx(noise_max(n, 50), rel=1e-9, abs=1e-12)
    assert doc["values"]["sharpe"] == pytest.approx(annual, rel=1e-9, abs=1e-12)
    one = go(tmp_path, NOISE, "n_trials=1")
    assert one["values"]["noise_sharpe"] == pytest.approx(0.0, abs=1e-12)


def test_deflated_at_tries(tmp_path: Path) -> None:
    data = prepare(tmp_path)
    n, sr, _ = stats_of(data)
    skew = float(stats.skew(data, bias=True))
    kurt = float(stats.kurtosis(data, fisher=False, bias=True))
    bench = noise_max(n, 20) / math.sqrt(PPY)
    variance = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    expected = stats.norm.cdf((sr - bench) * math.sqrt(n - 1) / math.sqrt(variance))
    doc = go(tmp_path, DEFLATED, "n_trials=20")
    assert doc["values"]["probability"] == pytest.approx(expected, rel=1e-9, abs=1e-12)
    assert doc["values"]["benchmark"] == pytest.approx(bench * math.sqrt(PPY), rel=1e-9, abs=1e-12)


def test_t_stat_hurdle(tmp_path: Path) -> None:
    data = prepare(tmp_path)
    n = len(data)
    t_stat = float(data.mean() / (data.std(ddof=1) / math.sqrt(n)))
    doc = go(tmp_path, HURDLE)
    assert doc["values"]["t_stat"] == pytest.approx(t_stat, rel=1e-9, abs=1e-12)
    assert doc["values"]["p_value"] == pytest.approx(
        2 * stats.norm.sf(abs(t_stat)), rel=1e-9, abs=1e-12
    )
    assert doc["values"]["hurdle"] == 3.0
    # Two-sided normal p-value of t = 3.
    assert doc["values"]["hurdle_p_value"] == pytest.approx(
        0.0026997960632601866, rel=1e-9, abs=1e-12
    )


def test_trade_count(tmp_path: Path) -> None:
    prepare(tmp_path)  # 30 trades, 19 of 30 positive by construction below
    pnls = [2.0, -1.0, 3.0, -1.0, 1.5, 2.0, -0.5, 1.0, -1.0, 2.5] * 3
    wins = sum(p > 0 for p in pnls)
    low, high = proportion_confint(wins, len(pnls), alpha=0.05, method="wilson")
    doc = go(tmp_path, TRADES)
    values = doc["values"]
    assert values["trades"] == 30 and values["reference"] == 30
    assert values["win_rate"] == pytest.approx(wins / 30, rel=1e-9, abs=1e-12)
    assert values["win_rate_lower"] == pytest.approx(low, rel=1e-9, abs=1e-12)
    assert values["win_rate_upper"] == pytest.approx(high, rel=1e-9, abs=1e-12)
    fewer = go(tmp_path, TRADES, "reference_trades=50")
    assert fewer["values"]["reference"] == 50


def test_required_history(tmp_path: Path) -> None:
    data = prepare(tmp_path)
    z = stats.norm.ppf(0.95) + stats.norm.ppf(0.9)
    effect = 0.5 / math.sqrt(PPY)
    need = max(2, math.ceil((z / effect) ** 2))
    doc = go(tmp_path, POWER)
    values = doc["values"]
    assert values["required_bars"] == need
    assert values["required_years"] == pytest.approx(need / PPY, rel=1e-9, abs=1e-12)
    assert values["run_bars"] == len(data)
    assert values["detectable_sharpe"] == pytest.approx(
        z / math.sqrt(len(data) / PPY), rel=1e-9, abs=1e-12
    )


def test_sequential_test(tmp_path: Path) -> None:
    data = prepare(tmp_path)
    sigma = float(data.std(ddof=1))
    mu = 1.0 / math.sqrt(PPY) * sigma
    llr = np.cumsum(mu * data - mu * mu / 2.0) / sigma**2
    upper, lower = math.log(0.8 / 0.05), math.log(0.2 / 0.95)
    assert upper == pytest.approx(2.772588722239781, rel=1e-9, abs=1e-12)
    assert lower == pytest.approx(-1.5581446180465497, rel=1e-9, abs=1e-12)
    doc = go(tmp_path, SPRT)
    values = doc["values"]
    assert values["llr"] == pytest.approx(llr[-1], rel=1e-9, abs=1e-12)
    assert values["upper_limit"] == pytest.approx(upper, rel=1e-9, abs=1e-12)
    assert values["lower_limit"] == pytest.approx(lower, rel=1e-9, abs=1e-12)
    hit = np.flatnonzero((llr >= upper) | (llr <= lower))
    if hit.size:
        assert values["first_crossing_bar"] == int(hit[0]) + 1
    else:
        assert values["first_crossing_bar"] is None
        assert values["outcome"] == "no limit reached"


def test_sequential_test_crossing_is_named(tmp_path: Path) -> None:
    prepare(tmp_path, np.random.default_rng(3).normal(0.004, 0.01, 400))
    values = go(tmp_path, SPRT)["values"]
    assert values["outcome"] == "favours the target Sharpe"
    assert isinstance(values["first_crossing_bar"], int)


def test_shrunk_sharpe(tmp_path: Path) -> None:
    data = prepare(tmp_path)
    n, sr, annual = stats_of(data)
    error = math.sqrt((1.0 + 0.5 * sr * sr) / n) * math.sqrt(PPY)
    weight = 0.5**2 / (0.5**2 + error**2)
    doc = go(tmp_path, SHRINK)
    values = doc["values"]
    assert values["standard_error"] == pytest.approx(error, rel=1e-9, abs=1e-12)
    assert values["shrink_weight"] == pytest.approx(weight, rel=1e-9, abs=1e-12)
    assert values["shrunk_sharpe"] == pytest.approx(weight * annual, rel=1e-9, abs=1e-12)


NEEDS_RETURNS = tuple(t for t in TOOLS if t != TRADES)


@pytest.mark.parametrize("tool", NEEDS_RETURNS)
def test_too_little_history(tool: str, tmp_path: Path) -> None:
    prepare(tmp_path, np.random.default_rng(2).normal(0.001, 0.01, 12))
    doc = go(tmp_path, tool, "n_trials=5")
    values = doc["values"]
    counts = {"bars", "run_bars", "trials"}
    numeric = [k for k in values if k not in counts and k != "outcome"]
    assert all(values[k] is None for k in numeric if k not in ("hurdle", "reference"))
    assert all("at least" in doc["reasons"][k] for k in doc["reasons"])
    assert doc["reasons"]
    bars = values.get("bars", values.get("run_bars"))
    assert bars == 12


def test_too_few_trades(tmp_path: Path) -> None:
    prepare(tmp_path)
    frame = pl.read_parquet(tmp_path / "runs" / RUN / "trades.parquet").head(0)
    frame.write_parquet(tmp_path / "runs" / RUN / "trades.parquet")
    doc = go(tmp_path, TRADES)
    assert doc["values"]["trades"] == 0
    assert doc["values"]["win_rate"] is None and "at least" in doc["reasons"]["win_rate"]


@pytest.mark.parametrize("tool", TOOLS)
def test_flat_history_has_no_reading(tool: str, tmp_path: Path) -> None:
    if tool in (TRADES, POWER):
        pytest.skip("needs no return spread")
    prepare(tmp_path, np.zeros(60))
    doc = go(tmp_path, tool, "n_trials=5")
    assert doc["reasons"] and all("varying" in r for r in doc["reasons"].values())


@pytest.mark.parametrize("tool", TOOLS)
def test_repeat_is_identical(tool: str, tmp_path: Path) -> None:
    prepare(tmp_path)
    spec = get(tool)
    assert spec.compute is not None
    settings = {p.name: 7 if p.name == "n_trials" else p.default for p in spec.params}
    first = spec.compute(Inputs(resolve(tmp_path, RUN)), settings, None)
    second = spec.compute(Inputs(resolve(tmp_path, RUN)), settings, None)
    assert first == second
    other = tmp_path / "other"
    prepare(other)
    assert go(other, tool, "n_trials=7")["values"] == go(tmp_path, tool, "n_trials=7")["values"]


@pytest.mark.parametrize("tool", TOOLS)
def test_public_function_parity(tool: str, tmp_path: Path) -> None:
    """The numbers equal the published functions or the formulas the tests above restate."""
    prepare(tmp_path)
    spec = get(tool)
    assert spec.family == "overfit_controls" and spec.seeded is False
    assert spec.kind in {"test", "control", "diagnostic"} and spec.question.endswith("?")
    doc = go(tmp_path, tool)
    assert doc["reading"] == spec.render(doc["values"])


def test_the_library_calls_agree(tmp_path: Path) -> None:
    from alpha_research import required_observations_known_sigma
    from alpha_validation import expected_max_sharpe, probabilistic_sharpe_ratio

    data = prepare(tmp_path)
    n = len(data)
    sr = float(data.mean() / data.std(ddof=1))
    assert go(tmp_path, PSR)["values"]["probability"] == pytest.approx(
        probabilistic_sharpe_ratio(data), rel=1e-9, abs=1e-12
    )
    best = expected_max_sharpe(1.0 / n, 30) * math.sqrt(PPY)
    assert go(tmp_path, NOISE, "n_trials=30")["values"]["noise_sharpe"] == pytest.approx(
        best, rel=1e-9, abs=1e-12
    )
    need = required_observations_known_sigma(0.5 / math.sqrt(PPY), 0.0, 1.0, target_power=0.9)
    assert go(tmp_path, POWER)["values"]["required_bars"] == need
    assert sr > 0


@pytest.mark.parametrize("tool", TOOLS)
def test_future_input_rejected(tool: str, tmp_path: Path) -> None:
    prepare(tmp_path)
    folder = tmp_path / "runs" / RUN
    name, field = (
        ("trades.parquet", "exit_ts") if tool == TRADES else ("equity_curve.parquet", "ts")
    )
    path = folder / name
    frame = pl.read_parquet(path)
    frame.vstack(
        frame.tail(1).with_columns(pl.lit(END + timedelta(days=1)).alias(field))
    ).write_parquet(path)
    with pytest.raises(SpineError, match="run period"):
        go(tmp_path, tool)


def test_no_recorded_tries_gives_a_reason(tmp_path: Path) -> None:
    prepare(tmp_path, tries=None)
    for tool in (HAIRCUT, MINBTL, NOISE, DEFLATED):
        doc = go(tmp_path, tool)
        assert doc["values"]["trials"] is None
        assert "n_trials" in doc["reasons"]["trials"]
        assert all(v is None for k, v in doc["values"].items() if k in doc["reasons"])


def test_invalid_recorded_tries_fail_loud(tmp_path: Path) -> None:
    prepare(tmp_path, tries=0)
    with pytest.raises(SpineError, match="n_trials"):
        go(tmp_path, HAIRCUT)


def test_a_negative_sharpe_has_no_haircut(tmp_path: Path) -> None:
    prepare(tmp_path, -returns_sample() * 0.5 - 0.001)
    doc = go(tmp_path, HAIRCUT)
    assert doc["values"]["haircut"] is None and "positive" in doc["reasons"]["haircut"]


def test_the_history_dates_stay_inside_the_run() -> None:
    assert START < END


def test_haircut_survives_a_very_large_t_statistic(tmp_path: Path) -> None:
    data = np.random.default_rng(8).normal(0.02, 0.01, 400)  # t-statistic near 40
    prepare(tmp_path, data)
    values = go(tmp_path, HAIRCUT, "n_trials=1")["values"]
    assert values["t_stat"] > 30
    assert values["adjusted_sharpe"] == pytest.approx(values["sharpe"], rel=1e-9)
    assert values["haircut"] == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_trade_profits_fail_loud(bad: float, tmp_path: Path) -> None:
    prepare(tmp_path)
    folder = tmp_path / "runs" / RUN
    write_trades(folder, [1.0, bad, -1.0], ["BUY"] * 3)
    with pytest.raises(SpineError, match="finite"):
        go(tmp_path, TRADES)


def test_required_history_needs_no_return_spread(tmp_path: Path) -> None:
    prepare(tmp_path, np.zeros(60))
    values = go(tmp_path, POWER)["values"]
    z = stats.norm.ppf(0.95) + stats.norm.ppf(0.9)
    assert values["required_bars"] == math.ceil((z / (0.5 / math.sqrt(PPY))) ** 2)
    assert values["detectable_sharpe"] == pytest.approx(z / math.sqrt(60 / PPY), rel=1e-9)
