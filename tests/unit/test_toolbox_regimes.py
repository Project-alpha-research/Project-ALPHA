"""Family I (regime and conditional) checks: known answers, short histories, repeats."""

import itertools
import math
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from scipy import stats

from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox.families.regimes_search import best_partitions
from alpha_cli.toolbox.runner import run
from tests.unit.test_spine_tools import RUN
from tests.unit.test_toolbox_run_level_checks import END, PRICE_ONLY, START, stored_run

YEAR = "regimes.year_by_year"
HALVES = "regimes.sub_period_stability"
WEEKDAY = "regimes.day_of_week"
MONTH = "regimes.calendar_month"
TURN = "regimes.turn_of_month"
HALLOWEEN = "regimes.halloween"
BULL = "regimes.bull_bear"
BETA = "regimes.asymmetric_beta"
TREND = "regimes.trend_range"
CHOW = "regimes.chow_test"
CUSUM = "regimes.cusum_mean"
SQUARES = "regimes.cusum_variance"
SUPF = "regimes.sup_f"
BREAKS = "regimes.break_count"
TOOLS = (
    YEAR,
    HALVES,
    WEEKDAY,
    MONTH,
    TURN,
    HALLOWEEN,
    BULL,
    BETA,
    TREND,
    CHOW,
    CUSUM,
    SQUARES,
    SUPF,
    BREAKS,
)
PPY = 365
CLOSE = pytest.approx


def prepare(home: Path, returns: Any, market: Any = None) -> Path:
    """Store a run whose scored returns (and buy-and-hold market returns) are given."""
    folder = stored_run(home, "regimes.fixture")
    rets = np.asarray(returns, dtype=float)
    equity = np.r_[1.0, np.cumprod(1.0 + rets)]
    dates = [START + timedelta(days=i) for i in range(equity.size)]
    pl.DataFrame({"ts": dates, "equity": equity}).write_parquet(folder / "equity_curve.parquet")
    mkt = np.full(rets.size, 0.0005) if market is None else np.asarray(market, dtype=float)
    pl.DataFrame(
        {
            "ts": dates,
            "strategy_equity": equity,
            "benchmark_equity": np.r_[1.0, np.cumprod(1.0 + mkt)],
            "available": [True] * equity.size,
            "benchmark_kind": [PRICE_ONLY] * equity.size,
        }
    ).write_parquet(folder / "benchmark_comparison.parquet")
    return folder


def go(home: Path, tool: str, returns: Any, market: Any = None, *params: str) -> dict[str, Any]:
    prepare(home, returns, market)
    return run(home, tool, RUN, list(params))


def start_dates(count: int) -> list[Any]:
    return [START + timedelta(days=i) for i in range(count)]


def noise(count: int, seed: int = 1, scale: float = 0.01) -> Any:
    return np.random.default_rng(seed).normal(0.0, scale, count)


def welch_reference(first: Any, second: Any) -> tuple[float, float]:
    result = stats.ttest_ind(first, second, equal_var=False)
    return float(result.statistic), float(result.pvalue)


def test_year_by_year_known_answer(tmp_path: Path) -> None:
    # 365 bars start in 2022, 365 in 2023 and 69 in 2024.
    rets = np.r_[np.full(365, 0.001), np.full(365, -0.0005), np.full(69, 0.002)]
    doc = go(tmp_path, YEAR, rets)
    totals = [1.001**365 - 1, 0.9995**365 - 1, 1.002**69 - 1]
    assert doc["values"] == CLOSE(
        {
            "years": 3,
            "positive_years": 2,
            "best_return": max(totals),
            "worst_return": min(totals),
            "median_return": sorted(totals)[1],
        }
    )
    assert [r["bars"] for r in doc["result"]["years"]] == [365, 365, 69]


def test_sub_period_known_answer(tmp_path: Path) -> None:
    sign = np.tile([1.0, -1.0], 50)
    first, second = 0.002 + 0.01 * sign[:50], -0.001 + 0.01 * sign[50:]
    doc = go(tmp_path, HALVES, np.r_[first, second])
    _, p_value = welch_reference(first, second)
    assert doc["values"] == CLOSE(
        {
            "first_mean": 0.002,
            "second_mean": -0.001,
            "gap": 0.003,
            "p_value": p_value,
            "first_bars": 50,
            "second_bars": 50,
            "first_sharpe": sharpe_of(first),
            "second_sharpe": sharpe_of(second),
        }
    )
    assert doc["result"]["split_date"] == (START + timedelta(days=50)).date().isoformat()


def sharpe_of(x: Any) -> float:
    return float(x.mean() / x.std(ddof=1) * math.sqrt(PPY))


def groups_by(values: Any, keys: list[int]) -> dict[int, Any]:
    return {k: values[np.array(keys) == k] for k in sorted(set(keys))}


def test_day_of_week_known_answer(tmp_path: Path) -> None:
    keys = [d.weekday() for d in start_dates(399)]
    level = {2: 0.003, 4: -0.002}
    rets = np.array([level.get(k, 0.0) for k in keys]) + noise(399)
    doc = go(tmp_path, WEEKDAY, rets)
    groups = groups_by(rets, keys)
    assert doc["values"]["best_label"] == "Wednesday"
    assert doc["values"]["worst_label"] == "Friday"
    assert doc["values"]["best_mean"] == CLOSE(groups[2].mean())
    assert doc["values"]["worst_mean"] == CLOSE(groups[4].mean())
    assert doc["values"]["p_value"] == CLOSE(stats.kruskal(*groups.values()).pvalue)
    assert doc["values"]["groups"] == 7


def test_month_of_year_known_answer(tmp_path: Path) -> None:
    keys = [d.month for d in start_dates(799)]
    level = {1: 0.004, 8: -0.003}
    rets = np.array([level.get(k, 0.0) for k in keys]) + noise(799, seed=2)
    doc = go(tmp_path, MONTH, rets)
    groups = groups_by(rets, keys)
    assert (doc["values"]["best_label"], doc["values"]["worst_label"]) == ("January", "August")
    assert doc["values"]["best_mean"] == CLOSE(groups[1].mean())
    assert doc["values"]["p_value"] == CLOSE(stats.kruskal(*groups.values()).pvalue)
    assert doc["values"]["groups"] == 12


def test_turn_of_month_known_answer(tmp_path: Path) -> None:
    # 799 bars from 2022-01-01 to 2024-03-09: 27 months, each with the last bar and the first
    # three bars of a month at the turn, so 27 * 4 = 108 turn bars.
    dates = start_dates(799)
    months: dict[tuple[int, int], list[int]] = {}
    for index, d in enumerate(dates):
        months.setdefault((d.year, d.month), []).append(index)
    turn = np.zeros(799, dtype=bool)
    for members in months.values():
        turn[[*members[:3], members[-1]]] = True
    rets = np.where(turn, 0.004, 0.0) + noise(799, seed=3)
    doc = go(tmp_path, TURN, rets)
    assert doc["values"]["turn_bars"] == 108 and doc["values"]["rest_bars"] == 691
    _, p_value = welch_reference(rets[turn], rets[~turn])
    assert doc["values"]["turn_mean"] == CLOSE(rets[turn].mean())
    assert doc["values"]["rest_mean"] == CLOSE(rets[~turn].mean())
    assert doc["values"]["p_value"] == CLOSE(p_value)


def test_halloween_known_answer(tmp_path: Path) -> None:
    winter = np.array([d.month in (11, 12, 1, 2, 3, 4) for d in start_dates(799)])
    rets = np.where(winter, 0.002, 0.0) + noise(799, seed=4)
    doc = go(tmp_path, HALLOWEEN, rets)
    _, p_value = welch_reference(rets[winter], rets[~winter])
    assert doc["values"]["winter_bars"] == int(winter.sum())
    assert doc["values"]["gap"] == CLOSE(rets[winter].mean() - rets[~winter].mean())
    assert doc["values"]["p_value"] == CLOSE(p_value)


def market_states(levels: Any, window: int) -> list[int]:
    """Plain-loop market state per bar: 0 rose, 1 fell over the look-back, -1 not yet known."""
    return [
        -1
        if i < window
        else 0
        if levels[i] > levels[i - window]
        else 1
        if levels[i] < levels[i - window]
        else -1
        for i in range(len(levels))
    ]


def levels_of(market: Any) -> Any:
    return np.r_[1.0, np.cumprod(1.0 + np.asarray(market))][:-1]


def test_bull_bear_known_answer(tmp_path: Path) -> None:
    market = np.r_[np.full(250, 0.002), np.full(250, -0.002), np.full(200, 0.002)] + noise(
        700, 5, 0.001
    )
    rets = np.where(np.arange(700) % 2 == 0, 0.004, -0.001) + noise(700, 6, 0.001)
    doc = go(tmp_path, BULL, rets, market, "lookback=20")
    state = np.array(market_states(levels_of(market), 20))
    _, p_value = welch_reference(rets[state == 0], rets[state == 1])
    assert doc["values"]["bull_bars"] == int((state == 0).sum())
    assert doc["values"]["bear_bars"] == int((state == 1).sum())
    assert doc["values"]["bull_mean"] == CLOSE(rets[state == 0].mean())
    assert doc["values"]["bear_mean"] == CLOSE(rets[state == 1].mean())
    assert doc["values"]["p_value"] == CLOSE(p_value)


def test_asymmetric_beta_known_answer(tmp_path: Path) -> None:
    market = noise(500, 7, 0.01)
    rets = np.where(market > 0, 0.5, 1.5) * market + noise(500, 8, 0.002)
    doc = go(tmp_path, BETA, rets, market)
    up, down = market > 0, market < 0
    fit_up, fit_down = (
        stats.linregress(market[up], rets[up]),
        stats.linregress(market[down], rets[down]),
    )
    ssr = sum(
        float(((rets[k] - fit.intercept - fit.slope * market[k]) ** 2).sum())
        for k, fit in ((up, fit_up), (down, fit_down))
    )
    sxx = [float(((market[k] - market[k].mean()) ** 2).sum()) for k in (up, down)]
    se = math.sqrt(ssr / (market.size - 4) * (1 / sxx[0] + 1 / sxx[1]))
    t_stat = (fit_down.slope - fit_up.slope) / se
    assert doc["values"] == CLOSE(
        {
            "up_beta": fit_up.slope,
            "down_beta": fit_down.slope,
            "difference": fit_down.slope - fit_up.slope,
            "p_value": 2 * stats.t.sf(abs(t_stat), market.size - 4),
            "up_bars": int(up.sum()),
            "down_bars": int(down.sum()),
        }
    )


def test_asymmetric_beta_leaves_flat_market_bars_out(tmp_path: Path) -> None:
    market = noise(500, 7, 0.01)
    rets = np.where(market > 0, 0.5, 1.5) * market + noise(500, 8, 0.002)
    plain = go(tmp_path / "plain", BETA, rets, market)
    # 60 flat-market bars with large positive strategy returns must change nothing.
    flat = go(tmp_path / "flat", BETA, np.r_[rets, np.full(60, 0.02)], np.r_[market, np.zeros(60)])
    assert flat["values"] == CLOSE(plain["values"])
    assert flat["result"]["flat_market_bars"] == 60


def test_trend_range_known_answer(tmp_path: Path) -> None:
    # Straight climb (efficiency 1) for 200 bars, then a zig-zag (efficiency 0) for 200 bars.
    market = np.r_[np.full(200, 0.001), np.tile([0.01, -0.00990099], 100)]
    rets = np.where(np.arange(400) < 200, 0.002, -0.001) + noise(400, 9, 0.001)
    doc = go(tmp_path, TREND, rets, market, "lookback=4", "threshold=0.3")
    levels = levels_of(market)
    marks: list[int] = []
    for i in range(400):
        path = np.abs(np.diff(levels[max(0, i - 4) : i + 1])).sum() if i >= 4 else 0.0
        marks.append(
            -1 if i < 4 or path == 0 else 0 if abs(levels[i] - levels[i - 4]) / path >= 0.3 else 1
        )
    state = np.array(marks)
    _, p_value = welch_reference(rets[state == 0], rets[state == 1])
    assert doc["values"]["trend_bars"] == int((state == 0).sum()) > 150
    assert doc["values"]["range_bars"] == int((state == 1).sum()) > 150
    assert doc["values"]["trend_mean"] == CLOSE(rets[state == 0].mean())
    assert doc["values"]["p_value"] == CLOSE(p_value)


def test_chow_known_answer(tmp_path: Path) -> None:
    # Hand answer: parts [1,3]x10 and [2,4]x10 (scaled): split RSS 20+20, pooled RSS 50,
    # F = (50 - 40) / (40 / 38) = 9.5 on (1, 38) degrees of freedom.
    rets = 0.001 * np.r_[np.tile([1.0, 3.0], 10), np.tile([2.0, 4.0], 10)]
    for params in ([], ["break_date=2022-01-21"]):
        doc = go(tmp_path / str(len(params)), CHOW, rets, None, *params)
        assert doc["values"] == CLOSE(
            {
                "first_mean": 0.002,
                "second_mean": 0.003,
                "f_stat": 9.5,
                "p_value": stats.f.sf(9.5, 1, 38),
                "break_date": "2022-01-21",
                "first_bars": 20,
                "second_bars": 20,
            }
        )


def test_chow_date_outside_history(tmp_path: Path) -> None:
    doc = go(tmp_path, CHOW, noise(100), None, "break_date=2030-01-01")
    assert doc["values"]["f_stat"] is None and doc["reasons"]["f_stat"].startswith("Needs")


def residuals_by_loop(y: list[float]) -> list[float]:
    out = []
    for r in range(1, len(y)):
        prior = sum(y[:r]) / r
        out.append((y[r] - prior) / math.sqrt(1 + 1 / r))
    return out


def test_cusum_mean_known_answer(tmp_path: Path) -> None:
    rets = np.r_[noise(30, 10, 0.002), noise(30, 11, 0.002) + 0.01]
    doc = go(tmp_path, CUSUM, rets)
    w = residuals_by_loop(rets.tolist())
    sigma = math.sqrt(sum(x * x for x in w) / len(w))
    ratios, running = [], 0.0
    for t, x in enumerate(w, start=1):
        running += x
        ratios.append(
            abs(running / sigma) / (0.948 * (math.sqrt(len(w)) + 2 * t / math.sqrt(len(w))))
        )
    assert doc["values"]["peak_ratio"] == CLOSE(max(ratios))
    assert doc["values"]["peak_ratio"] > 1
    assert (
        doc["values"]["peak_date"]
        == (START + timedelta(days=ratios.index(max(ratios)) + 1)).date().isoformat()
    )
    assert doc["values"]["bars"] == 60


def test_cusum_mean_steady_series_stays_inside(tmp_path: Path) -> None:
    doc = go(tmp_path, CUSUM, noise(300, 12, 0.005))
    assert doc["values"]["peak_ratio"] < 1


def test_cusum_variance_known_answer(tmp_path: Path) -> None:
    rets = np.r_[noise(30, 13, 0.001), noise(30, 14, 0.02)]
    doc = go(tmp_path, SQUARES, rets)
    squares = [x * x for x in residuals_by_loop(rets.tolist())]
    total, running, gaps = sum(squares), 0.0, []
    for t, s in enumerate(squares, start=1):
        running += s
        gaps.append(abs(running / total - t / len(squares)))
    peak = max(gaps)
    assert doc["values"]["max_gap"] == CLOSE(peak)
    assert doc["values"]["p_value"] == CLOSE(stats.kstwobign.sf(peak * math.sqrt(len(squares) / 2)))
    assert doc["values"]["p_value"] < 0.01
    assert (
        doc["values"]["gap_date"]
        == (START + timedelta(days=gaps.index(peak) + 1)).date().isoformat()
    )


def sup_f_by_loop(y: list[float], trim: float = 0.15) -> tuple[float, int]:
    n = len(y)
    best = (-1.0, 0)
    for s in range(math.ceil(trim * n), n - math.ceil(trim * n) + 1):
        a, b = y[:s], y[s:]
        rss = sum((x - sum(a) / s) ** 2 for x in a) + sum((x - sum(b) / (n - s)) ** 2 for x in b)
        pooled = sum((x - sum(y) / n) ** 2 for x in y)
        f = (pooled - rss) / (rss / (n - 2))
        best = max(best, (f, s))
    return best


def test_sup_f_known_answer(tmp_path: Path) -> None:
    rets = np.r_[noise(40, 15, 0.002), noise(60, 16, 0.002) + 0.01]
    doc = go(tmp_path, SUPF, rets, None, "n_sims=200")
    f_max, split = sup_f_by_loop(rets.tolist())
    assert doc["values"]["sup_f"] == CLOSE(f_max)
    assert doc["values"]["break_date"] == (START + timedelta(days=split)).date().isoformat()
    assert doc["values"]["first_mean"] == CLOSE(rets[:split].mean())
    # A planted break beats every simulated history: the smallest possible simulated p-value.
    assert doc["values"]["p_value"] == CLOSE(1 / 201)


def test_sup_f_no_break_is_not_small(tmp_path: Path) -> None:
    doc = go(tmp_path, SUPF, noise(200, 17, 0.01), None, "n_sims=500")
    assert 0.05 < doc["values"]["p_value"] <= 1.0  # random draw; fixed seed, stated range


def test_break_count_known_answer(tmp_path: Path) -> None:
    rets = np.r_[np.zeros(100), np.full(100, 0.01), np.full(100, -0.01)] + noise(300, 18, 0.002)
    doc = go(tmp_path, BREAKS, rets)
    parts = doc["result"]["parts"]
    assert doc["values"]["breaks"] == 2
    assert [p["bars"] for p in parts] == [
        pytest.approx(100, abs=3),
        pytest.approx(100, abs=3),
        pytest.approx(100, abs=3),
    ]
    assert doc["values"]["largest_gap"] == CLOSE(
        abs(parts[1]["mean_return"] - parts[2]["mean_return"])
    )


def test_break_count_none_in_noise(tmp_path: Path) -> None:
    doc = go(tmp_path, BREAKS, noise(300, 19, 0.01))
    assert doc["values"]["breaks"] == 0
    assert doc["values"]["first_break"] is None and doc["reasons"]["first_break"]


def test_break_count_none_reads_in_plain_words(tmp_path: Path) -> None:
    doc = go(tmp_path, BREAKS, noise(300, 19, 0.01))
    assert "unavailable" not in doc["reading"]
    assert doc["values"]["largest_gap"] == 0.0


def test_best_partitions_match_brute_force() -> None:
    y = np.array([1.0, 2.0, 1.5, 7.0, 8.0, 7.5, 3.0, 2.0, 2.5, 3.5, 9.0, 8.0, 8.5, 1.0, 0.0, 1.0])
    rss, parts = best_partitions(y, 2, 3)
    n = y.size

    def cost(a: int, b: int) -> float:
        return float(((y[a:b] - y[a:b].mean()) ** 2).sum())

    one = min(cost(0, c) + cost(c, n) for c in range(3, n - 2))
    two = min(
        cost(0, c) + cost(c, d) + cost(d, n)
        for c, d in itertools.combinations(range(3, n - 2), 2)
        if d - c >= 3
    )
    assert rss == CLOSE([cost(0, n), one, two])
    assert len(parts[1]) == 1 and len(parts[2]) == 2


@pytest.mark.parametrize("tool", TOOLS)
def test_too_little_to_read(tool: str, tmp_path: Path) -> None:
    doc = go(tmp_path, tool, noise(10, 20, 0.01), noise(10, 21, 0.01))
    assert all(v is None for v in doc["values"].values())
    assert all(doc["reasons"][k].startswith("Needs") for k in doc["values"])


@pytest.mark.parametrize("tool", TOOLS)
def test_repeat_is_identical(tool: str, tmp_path: Path) -> None:
    rets, market = noise(320, 22, 0.01), noise(320, 23, 0.01)
    docs = [
        go(tmp_path / name, tool, rets, market, *(["n_sims=200"] if tool == SUPF else []))
        for name in "ab"
    ]
    assert docs[0]["values"] == docs[1]["values"]
    assert docs[0]["result"] == docs[1]["result"]


@pytest.mark.parametrize("tool", TOOLS)
def test_future_input_rejected(tool: str, tmp_path: Path) -> None:
    folder = prepare(tmp_path, noise(320, 24, 0.01), noise(320, 25, 0.01))
    for name in ("equity_curve.parquet", "benchmark_comparison.parquet"):
        frame = pl.read_parquet(folder / name)
        late = frame.tail(1).with_columns(pl.lit(END + timedelta(days=1)).alias("ts"))
        frame.vstack(late).write_parquet(folder / name)
    with pytest.raises(SpineError, match="run period"):
        run(tmp_path, tool, RUN)
