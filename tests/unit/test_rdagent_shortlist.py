"""Add-only shortlist bookkeeping, using synthetic pre-reserved factor values."""

from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import polars as pl
import pytest

from alpha_cli import _rdagent_judge as judge
from alpha_cli import rdagent_factor_eval as ev
from alpha_cli._rdagent_stats import FACTOR_DEFLATION_RULE
from alpha_core import DataError
from alpha_web._rdagent_run_factor import _factor
from alpha_web._rdagent_run_funnel import _funnel
from tests.unit.test_rdagent_factor_eval import fixture
from tests.unit.test_rdagent_factor_eval import recorded_time as recorded_time

FIELDS = {
    "shortlist",
    "lineage_r2",
    "lineage_regressors",
    "lineage_convention",
    "lineage_reason",
    "composite_suspect",
}


def stored_factors(
    tmp_path: Path, signals: list[np.ndarray]
) -> tuple[list[dict[str, Any]], list[date], list[str]]:
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(signals[0].shape[0])]
    symbols = [f"C{i:03}" for i in range(signals[0].shape[1])]
    frame = pl.DataFrame(
        {
            "date": [day for day in days for _ in symbols],
            "instrument": symbols * len(days),
            **{f"factor{i}": signal.ravel() for i, signal in enumerate(signals)},
        }
    )
    path = tmp_path / "values.parquet"
    frame.write_parquet(path)
    rows = [
        {
            "name": f"factor{i}",
            "status": "SCREEN_FAIL",
            "panel_sha256": "panel",
            "code_sha256": f"{i:064x}",
            "factor_values": {"path": str(path), "sha256": ev.sha(path.read_bytes())},
        }
        for i in range(len(signals))
    ]
    return rows, days, symbols


def test_lineage_exact_three_factor_blend(tmp_path: Path) -> None:
    rng = np.random.default_rng(16)
    signals = [rng.uniform(-1, 1, (100, 40)) for _ in range(3)]
    rows, days, symbols = stored_factors(tmp_path, signals)
    target = 0.8 * signals[0] + 0.1 * signals[1] + 0.1 * signals[2]
    result = judge.lineage(target, rows, "panel", days, symbols)
    assert result["lineage_r2"] > 0.95
    assert result["composite_suspect"] is True
    assert result["lineage_regressors"] == 3
    assert result["lineage_convention"] == "pooled-xs-rank-ols-v1"


def test_lineage_independent_among_thirty_factors(tmp_path: Path) -> None:
    rng = np.random.default_rng(91)
    signals = [rng.normal(size=(100, 40)) for _ in range(30)]
    rows, days, symbols = stored_factors(tmp_path, signals)
    result = judge.lineage(rng.normal(size=(100, 40)), rows, "panel", days, symbols)
    assert 0 <= result["lineage_r2"] < 0.1
    assert result["composite_suspect"] is False
    assert result["lineage_regressors"] == 20


@pytest.mark.parametrize("reason", ["no earlier", "fewer than 1,000", "unavailable"])
def test_lineage_unavailable_is_null(tmp_path: Path, reason: str) -> None:
    signal = np.random.default_rng(3).normal(size=(100, 20))
    rows, days, symbols = stored_factors(tmp_path, [signal])
    if reason == "no earlier":
        rows[0]["panel_sha256"] = "different panel"
    elif reason == "fewer than 1,000":
        signal[40:] = np.nan
    else:
        rows[0].pop("factor_values")
    result = judge.lineage(signal, rows, "panel", days, symbols)
    assert result["lineage_r2"] is None
    assert reason in result["lineage_reason"]
    assert result["composite_suspect"] is None


def test_lineage_hash_mismatch_fails_loud(tmp_path: Path) -> None:
    signal = np.random.default_rng(3).normal(size=(100, 20))
    rows, days, symbols = stored_factors(tmp_path, [signal])
    rows[0]["factor_values"]["sha256"] = "0" * 64
    with pytest.raises(DataError, match="hash"):
        judge.lineage(signal, rows, "panel", days, symbols)


def test_lineage_missing_rows_are_zero_and_adjustment_has_no_intercept(tmp_path: Path) -> None:
    # Hand-ranked cross-sections: ties use their average rank, missing entries stay centred.
    target = np.tile([-2.0, -1.0, 1.0, 2.0], (300, 1))
    earlier = np.tile([0.0, 0.0, np.nan, 1.0], (300, 1))
    rows, days, symbols = stored_factors(tmp_path, [earlier])
    result = judge.lineage(target, rows, "panel", days, symbols)
    y = np.tile([-0.5, -1 / 6, 1 / 6, 0.5], 300)
    x = np.tile([-0.25, -0.25, 0.0, 0.5], 300)
    coefficient = float(x @ y) / float(x @ x)
    residual = y - coefficient * x
    expected = 1 - float(residual @ residual) / float(y @ y) * 1200 / 1199
    assert result["lineage_r2"] == pytest.approx(expected)
    assert result["lineage_regressors"] == 1
    json.dumps(result, allow_nan=False)


def test_lineage_selection_ties_keep_ledger_order(tmp_path: Path) -> None:
    # Every regressor has the same absolute correlation; the 21st must not replace the first.
    signal = np.tile(np.arange(20, dtype=float), (60, 1))
    rows, days, symbols = stored_factors(tmp_path, [signal] * 20 + [-signal])
    solve = np.linalg.lstsq
    with patch.object(np.linalg, "lstsq", wraps=solve) as fit:
        result = judge.lineage(signal, rows, "panel", days, symbols)
    design, target = fit.call_args.args
    assert design.shape == (1200, 20)
    for column in design.T:
        np.testing.assert_allclose(column, target)
    assert result["lineage_r2"] == pytest.approx(1.0)


def test_bookkeeping_uses_only_earlier_rows_and_shortlists_only_two_statuses(
    tmp_path: Path,
) -> None:
    signal = np.random.default_rng(3).normal(size=(100, 20))
    rows, days, symbols = stored_factors(tmp_path, [signal] * 3)
    rows[0]["status"], rows[1]["status"], rows[2]["status"] = (
        "SCREEN_FAIL",
        "DEFLATION_FAIL",
        "CANDIDATE",
    )
    values = pl.read_parquet(tmp_path / "values.parquet")
    ev.record_shortlist(rows, [], values, {"panel_sha256": "panel"}, days, symbols)
    assert [row["shortlist"] for row in rows] == [False, True, True]
    assert [row.get("lineage_regressors") for row in rows] == [None, 1, 2]
    for status in ("REPEAT", "FAILED", "SPREAD_FAIL", "REPLAY_FAIL", "FAST_ONLY", "ERROR"):
        row = {"status": status}
        ev.record_shortlist([row], [], pl.DataFrame(), {}, [], [])
        assert row == {"status": status, "shortlist": False}


@pytest.mark.parametrize("status", ["SCREEN_FAIL", "DEFLATION_FAIL", "CANDIDATE"])
def test_evaluation_and_ledger_are_add_only(
    tmp_path: Path, recorded_time: None, status: str
) -> None:
    run = tmp_path / "run"
    req = fixture(run, noise=status == "SCREEN_FAIL")
    deflated = {
        "dsr": 1.0 if status == "CANDIDATE" else 0.0,
        "threshold": 0.95,
        "n_trials": 2,
        "deflation_rule": FACTOR_DEFLATION_RULE,
    }
    with patch.object(ev, "factor_deflation", return_value=deflated):
        with patch.object(ev, "record_shortlist", create=True):
            baseline = ev.evaluate(run, req, run / "baseline.json", tmp_path / "baseline-ledger")
        result = ev.evaluate(run, req, run / "result.json", tmp_path / "ledger")
    row = result["factors"][0]
    assert row["status"] == status
    assert row["shortlist"] is (status != "SCREEN_FAIL")
    assert json.loads((tmp_path / "ledger").read_bytes()) == row
    for field in FIELDS:
        row.pop(field, None)
    assert ev.canonical(result) == ev.canonical(baseline)


def test_shortlisted_non_candidate_does_not_increase_confirmed(tmp_path: Path) -> None:
    run = tmp_path / "first"
    req = fixture(run)
    with patch.object(ev, "factor_deflation", return_value={"dsr": 0.0, "threshold": 0.95}):
        first = ev.evaluate(run, req, run / "result.json", tmp_path / "first-ledger")
    row = first["factors"][0]
    assert row["shortlist"] is True and row["status"] == "DEFLATION_FAIL"
    old = copy.deepcopy(row)
    for key in FIELDS:
        old.pop(key, None)
    results = []
    run = tmp_path / "next"
    req = fixture(run, seed=19, noise=True)
    for index, previous in enumerate([old, row]):
        ledger = tmp_path / f"ledger{index}"
        ledger.write_bytes(ev.canonical(previous))
        results.append(ev.evaluate(run, req, run / f"result{index}.json", ledger)["factors"][0])
    assert results[0]["screen_confirmed"] == results[1]["screen_confirmed"] == 0
    for key in ("screen_cutoff", "screen_m", "family_size", "total_trials", "q", "p"):
        assert results[0][key] == results[1][key]


def test_workstation_missing_shortlist_is_not_false() -> None:
    row: dict[str, Any] = {"status": "DEFLATION_FAIL", "clocks": {}}
    old = _factor(row)
    assert old.figures["shortlist"].value is None
    assert "not recorded" in str(old.figures["shortlist"].reason)
    assert _funnel({}, [row], None)["shortlisted"].value is None
    row.update(shortlist=True, composite_suspect=True, lineage_r2=0.98)
    new = _factor(row)
    assert new.figures["shortlist"].value is True
    assert "looks like a blend of earlier tries" in new.sentence
    assert "not a pass, not a candidate, and not evidence of profit" in new.sentence
    assert _funnel({}, [row], None)["shortlisted"].value == 1
    row["shortlist"] = False
    assert _factor(row).figures["shortlist"].value is False
    assert _funnel({}, [row], None)["shortlisted"].value == 0


def test_lineage_skips_earlier_trials_that_stored_no_values(tmp_path: Path) -> None:
    # Look-ahead code writes no value column; its row must not void every later lineage figure.
    rng = np.random.default_rng(5)
    signals = [rng.normal(size=(100, 40)) for _ in range(2)]
    rows, days, symbols = stored_factors(tmp_path, signals)
    rows.insert(0, {**rows[0], "name": "refused", "status": "LOOKAHEAD"})
    rows.append({**rows[0], "name": "no_column", "status": "ERROR"})
    result = judge.lineage(signals[0] + signals[1], rows, "panel", days, symbols)
    assert result["lineage_reason"] is None
    assert result["lineage_regressors"] == 2
    assert result["lineage_r2"] > 0.9


def test_lineage_failure_records_null_and_keeps_the_verdict(tmp_path: Path) -> None:
    signal = np.random.default_rng(3).normal(size=(100, 20))
    rows, days, symbols = stored_factors(tmp_path, [signal, signal])
    rows[0]["factor_values"] = {**rows[0]["factor_values"], "sha256": "0" * 64}
    rows[1]["status"] = "DEFLATION_FAIL"
    values = pl.read_parquet(tmp_path / "values.parquet")
    ev.record_shortlist(rows[1:], rows[:1], values, {"panel_sha256": "panel"}, days, symbols)
    row = rows[1]
    assert row["status"] == "DEFLATION_FAIL" and row["shortlist"] is True
    assert row["lineage_r2"] is None and row["composite_suspect"] is None
    assert "differ from their recorded hash" in row["lineage_reason"]
    assert row["lineage_convention"] == "pooled-xs-rank-ols-v1"
