"""Independent checks of the judge-honesty statistics, written apart from the code they test.

Each reference below is computed from its textbook definition with plain loops or a closed
form, never by calling the implementation's helpers, so a shared mistake cannot pass both.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pytest

from alpha_cli import rdagent_factor_eval as ev
from alpha_cli._rdagent_stats import (
    clustered_mean_variance,
    factor_deflation,
    newey_west,
    screen_statistics,
)
from alpha_cli._rdagent_twins import rank_twin

NORMAL = NormalDist()
EULER = 0.5772156649015329


def cgm_by_loops(cells: np.ndarray) -> float:
    """Cameron, Gelbach & Miller (2011) two-way variance of the mean of daily cell means."""
    observed = [(t, i, float(v)) for (t, i), v in np.ndenumerate(cells) if math.isfinite(v)]
    per_date: dict[int, list[float]] = {}
    for t, _, v in observed:
        per_date.setdefault(t, []).append(v)
    dates = len(per_date)
    theta = sum(sum(v) / len(v) for v in per_date.values()) / dates
    score = {(t, i): (v - theta) / (len(per_date[t]) * dates) for t, i, v in observed}

    def one_way(key: int) -> float:
        sums: dict[int, float] = {}
        for cell, s in score.items():
            sums[cell[key]] = sums.get(cell[key], 0.0) + s
        groups = len(sums)
        return groups / (groups - 1) * sum(s * s for s in sums.values())

    total = len(score)
    cell = total / (total - 1) * sum(s * s for s in score.values())
    return one_way(0) + one_way(1) - cell


def test_cgm_matches_balanced_closed_form() -> None:
    rng = np.random.default_rng(3)
    cells = rng.normal(size=(9, 6)) + rng.normal(size=6)  # a persistent name effect
    dates, names = cells.shape
    closed = (
        np.var(cells.mean(axis=1), ddof=1) / dates
        + np.var(cells.mean(axis=0), ddof=1) / names
        - np.var(cells, ddof=1) / (dates * names)
    )
    assert clustered_mean_variance(cells) == pytest.approx(closed, rel=1e-12)
    assert clustered_mean_variance(cells) > np.var(cells.mean(axis=1), ddof=1) / dates


def test_cgm_matches_loops_on_unbalanced_panel() -> None:
    rng = np.random.default_rng(11)
    cells = rng.normal(size=(12, 7)) + 0.8 * rng.normal(size=7)
    cells[rng.random(cells.shape) < 0.25] = np.nan
    cells[4] = np.nan  # a date with no usable cell carries no weight
    assert clustered_mean_variance(cells) == pytest.approx(cgm_by_loops(cells), rel=1e-12)


def nonpositive_two_way_cells() -> np.ndarray:
    # A strong negative within-date/within-name pattern: the cell term exceeds the two
    # one-way sums, so V_date + V_name - V_cell is negative while V_date stays positive.
    return np.array([[3.0, -1.0, -1.0], [-1.0, 3.0, -1.0], [-1.0, -1.0, 3.2]])


def test_nonpositive_two_way_variance_falls_back_to_larger_one_way() -> None:
    from alpha_cli._rdagent_stats import clustered_variance

    cells = nonpositive_two_way_cells()
    assert cgm_by_loops(cells) <= 0
    variance, term = clustered_variance(cells)
    finite = cells - np.mean(cells.mean(axis=1))
    dates, names = cells.shape
    v_date = dates / (dates - 1) * float(np.square(finite.mean(axis=1) / dates).sum())
    v_name = names / (names - 1) * float(np.square(finite.sum(axis=0) / (names * dates)).sum())
    assert v_date > 0
    assert term == "one_way_max_fallback"
    assert variance == pytest.approx(max(v_date, v_name), rel=1e-12)


def test_fallback_screen_is_never_less_conservative_than_date_only() -> None:
    rng = np.random.default_rng(5)
    for _ in range(200):
        signal = rng.normal(size=(30, 6))
        outcome = rng.normal(size=(30, 6))
        daily = np.array(
            [
                np.corrcoef(np.argsort(np.argsort(a)), np.argsort(np.argsort(b)))[0, 1]
                for a, b in zip(signal, outcome, strict=True)
            ]
        )
        result = screen_statistics(signal, outcome, daily, 1)
        assert result["clustered_variance_term"] in {"two_way", "one_way_max_fallback"}
        assert result["two_sided_p"] >= result["plain_p"] - 1e-15


def test_newey_west_hand_computed_four_points() -> None:
    # x = 1, 3, 2, 5: mean 2.75; gamma0 = 2.1875, gamma1 = -0.578125, gamma2 = 0.46875;
    # lag ceil(4 * 0.04 ** (2/9)) = 2; LRV = 2.1875 + 2 * (2/3 * gamma1 + 1/3 * gamma2).
    result = newey_west(np.array([1.0, 3.0, 2.0, 5.0]))
    assert result["lag"] == 2
    expected = 2.1875 + 2 * (-0.578125 * 2 / 3 + 0.46875 / 3)
    assert result["long_run_variance"] == pytest.approx(expected)
    assert result["effective_n"] == 4  # 4 * 2.1875 / 1.729 > 4: capped, never extra observations


@pytest.mark.parametrize("phi", [0.5, 0.9])
def test_newey_west_matches_ar1_population_answer(phi: float) -> None:
    n = 200_000
    rng = np.random.default_rng(7)
    shocks = rng.normal(size=n)
    series = np.empty(n)
    series[0] = shocks[0] / math.sqrt(1 - phi * phi)
    for t in range(1, n):
        series[t] = phi * series[t - 1] + shocks[t]
    lag = math.ceil(4 * (n / 100) ** (2 / 9))
    # Population Bartlett-weighted ratio gamma0 / LRV_L for an AR(1) with unit gamma0 scale.
    bartlett = 1 + 2 * sum((1 - k / (lag + 1)) * phi**k for k in range(1, lag + 1))
    result = newey_west(series)
    assert result["lag"] == lag == 22
    assert result["effective_n"] / n == pytest.approx(1 / bartlett, rel=0.05)
    # and close to the infinite-lag answer (1 - phi) / (1 + phi) when the lag is long enough
    if phi == 0.5:
        assert result["effective_n"] / n == pytest.approx(1 / 3, rel=0.05)


def psr_by_hand(returns: np.ndarray, benchmark: float) -> float:
    n, sr = returns.size, float(returns.mean() / returns.std(ddof=1))
    centred = returns - returns.mean()
    m2 = float(np.mean(centred**2))
    skew = float(np.mean(centred**3)) / m2**1.5
    kurt = float(np.mean(centred**4)) / m2**2
    scale = math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr * sr)
    return NORMAL.cdf((sr - benchmark) * math.sqrt(n - 1) / scale)


def expected_max_by_hand(variance: float, trials: int) -> float:
    return math.sqrt(variance) * (
        (1 - EULER) * NORMAL.inv_cdf(1 - 1 / trials)
        + EULER * NORMAL.inv_cdf(1 - 1 / (trials * math.e))
    )


@pytest.mark.parametrize("spread,term", [(0.001, "sampling_floor"), (0.2, "sample_variance")])
def test_deflation_matches_bailey_lopez_de_prado_by_hand(spread: float, term: str) -> None:
    rng = np.random.default_rng(23)
    returns = rng.normal(0.004, 0.02, 1093)
    sharpes = list(rng.normal(-0.04, spread, 36))
    result = factor_deflation(returns, sharpes, 237)
    variance = max(float(np.var(sharpes, ddof=1)), 1 / (returns.size - 1))
    assert result["deflation_variance_term"] == term
    assert result["deflation_n"] == 474
    assert result["expected_max_sharpe"] == pytest.approx(expected_max_by_hand(variance, 474))
    assert result["dsr"] == pytest.approx(
        psr_by_hand(returns, expected_max_by_hand(variance, 474)), abs=1e-9
    )
    assert result["threshold"] == 0.95


def test_rank_twin_ignores_unrelated_factors() -> None:
    rng = np.random.default_rng(31)
    first = rng.normal(size=(400, 40))
    other = 0.3 * first + rng.normal(size=first.shape)  # correlated, but a different idea
    assert not rank_twin(first, other)["is_twin"]
    assert rank_twin(first, -first + 1e-6 * rng.normal(size=first.shape))["is_twin"]


def test_twin_check_skips_failed_rows_without_stored_values(tmp_path: Path) -> None:
    from tests.unit.test_rdagent_judge_honesty import declared_fixture

    run = tmp_path / "batch"
    path = declared_fixture(run)
    request = json.loads(path.read_text())
    broken = {**request["factors"][0], "name": "broken", "status": "FAILED"}
    broken["code_sha256"] = "c" * 64
    request["factors"].insert(0, broken)
    path.write_text(json.dumps(request))
    rows = ev.evaluate(run, path, run / "result.json", tmp_path / "ledger")["factors"]
    assert [row["status"] for row in rows][0] == "FAILED"
    assert rows[1]["status"] != "REPEAT"
    assert rows[1]["twin_check"] == "not available for 1 earlier trials"


def test_batch_counts_whole_request_and_grants_no_batch_credit(tmp_path: Path) -> None:
    from tests.unit.test_rdagent_judge_honesty import declared_fixture

    run = tmp_path / "pair"
    path = declared_fixture(run)
    request = json.loads(path.read_text())
    request["factors"].append({**request["factors"][0], "name": "second", "code_sha256": "d" * 64})
    path.write_text(json.dumps(request))
    import polars as pl

    values = pl.read_parquet(run / "factors.parquet")
    noise = np.random.default_rng(2).normal(size=values.height)
    values.with_columns(second=pl.Series(noise)).write_parquet(run / "factors.parquet")
    rows = ev.evaluate(run, path, run / "result.json", tmp_path / "ledger")["factors"]
    assert rows[0]["status"] == "CANDIDATE"
    # Sequential evaluation would give the first factor m = 1; the batch counts both, and the
    # first factor's CANDIDATE earns the second no credit within the batch.
    assert [row["screen_m"] for row in rows] == [2, 2]
    assert [row["screen_confirmed"] for row in rows] == [0, 0]


def status_rows() -> list[dict[str, Any]]:
    from tests.unit._rdagent_support import clock_rows
    from tests.unit.test_trial_record import factor

    rows = []
    for status in ("CANDIDATE", "SCREEN_FAIL", "DEFLATION_FAIL"):
        for dsr in (0.04, 0.95, 0.96, float("nan"), float("inf"), None):
            for threshold in (0.95, None):
                trials = clock_rows(0.5)
                trials["weekly"]["replay"]["deflated_sharpe"] = {"dsr": dsr, "threshold": threshold}
                rows.append(factor(clocks=trials, status=status))
    old = factor(version=2, status="CANDIDATE", clocks=None)
    old.pop("clocks")
    old.pop("lead_clock")
    old["replay"] = {"deflated_sharpe": {"dsr": 0.1, "threshold": 0.95}}
    return [*rows, old]


def test_status_derivation_agrees_in_ledger_web_and_worker() -> None:
    from alpha_cli._rdagent_stability import recorded_status
    from alpha_web._rdagent_runs import _derived_status
    from tests.unit.test_rdagent_judge_honesty import worker_module

    worker = worker_module("idea_families")
    for row in status_rows():
        expected = recorded_status(row)
        assert _derived_status(row) == expected, row
        assert worker.recorded_status(row) == expected, row


def test_the_prompt_template_is_what_the_parser_reads() -> None:
    from tests.unit._rdagent_support import judge_namespace
    from tests.unit.test_rdagent_judge_honesty import worker_module

    ns = judge_namespace()
    families = worker_module("idea_families")
    simulator = ns["AlphaFactorScenario"].simulator.fget(None)
    for text in (simulator, ns["SWING_BRIEF"]):
        template = (
            r"declared_direction: <\+1 or -1>; primary_clock: <weekly or monthly>; "
            r"direction_reason: [^.]*"
        )
        line = re.search(template, text)
        assert line is not None, text
        filled = (
            line.group()
            .replace("<+1 or -1>", "+1")
            .replace("<weekly or monthly>", "weekly")
            .replace("<one sentence of economic reasoning>", "Losers recover")
        )
        assert families.declaration("[Momentum Factor] text. " + filled + ".") == {
            "declared_direction": 1,
            "primary_clock": "weekly",
            "direction_reason": "Losers recover.",
        }


@pytest.mark.parametrize(
    "text,direction,clock",
    [
        (
            "declared_direction: -1; primary_clock: monthly; direction_reason: Losers.",
            -1,
            "monthly",
        ),
        (
            "declared_direction: \u22121. primary_clock: Weekly. direction_reason: Losers.",
            -1,
            "weekly",
        ),
        ("declared_direction: 1\nprimary_clock: weekly\ndirection_reason: Winners.", 1, "weekly"),
    ],
)
def test_declaration_reads_common_punctuation(text: str, direction: int, clock: str) -> None:
    from tests.unit.test_rdagent_judge_honesty import worker_module

    parsed = worker_module("idea_families").declaration(text)
    assert (parsed["declared_direction"], parsed["primary_clock"]) == (direction, clock)
    assert parsed["direction_reason"]


@pytest.mark.parametrize(
    "text",
    [
        "declared_direction: +1 or -1; primary_clock: weekly; direction_reason: x.",
        "declared_direction: +2; primary_clock: weekly; direction_reason: x.",
        "declared_direction: +1; primary_clock: daily; direction_reason: x.",
        "declared_direction: +1; primary_clock: weekly; direction_reason: ;",
        "declared_direction: +1; primary_clock: weekly or monthly; direction_reason: x.",
    ],
)
def test_declaration_refuses_ambiguous_or_daily_fields(text: str) -> None:
    from tests.unit.test_rdagent_judge_honesty import worker_module

    with pytest.raises(ValueError, match="declared_direction.*primary_clock.*direction_reason"):
        worker_module("idea_families").declaration(text)


def test_every_real_recorded_proposal_is_refused_with_what_to_add() -> None:
    from tests.unit._rdagent_real_proposals import PROPOSALS
    from tests.unit.test_rdagent_judge_honesty import worker_module

    families = worker_module("idea_families")
    for name, proposal in PROPOSALS.items():
        with pytest.raises(ValueError) as refused:
            families.declaration(proposal["description"])
        message = str(refused.value)
        for field in ("declared_direction: +1 or -1", "primary_clock: weekly or monthly"):
            assert field in message, name
        assert "direction_reason:" in message
