"""Regression contracts for fractional thirds and honest proposer diagnostics."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest

from alpha_cli import _rdagent_clocks as clocks
from alpha_cli import _rdagent_judge as judge
from alpha_cli import _rdagent_membership as membership
from alpha_cli import rdagent_factor_eval as ev
from tests.unit.test_rdagent_loop_fixups_3 import judge_namespace


def test_tie_diagnostics_count_names_and_preserve_all_tied_guard() -> None:
    rng = np.random.default_rng(18)
    scores = rng.normal(size=(40, 10))
    scores[:, :3] = 0
    # Exactly three of ten names tied, with two above and five below: boundary at rank 3.
    scores[:, 3:5] = np.abs(scores[:, 3:5]) + 1
    scores[:, 5:] = -np.abs(scores[:, 5:]) - 1
    outcome = rng.normal(size=scores.shape)
    result = judge.screen(scores, outcome, "a" * 64, n_resamples=20)
    assert result["tie_share"] == pytest.approx(0.3)
    assert result["boundary_tie_share"] == pytest.approx(0.3)
    assert result["all_tied_day_share"] == 0.0
    assert result["status"] == "OK"
    scores[:3] = 0
    result = judge.screen(scores, outcome, "a" * 64, n_resamples=20)
    assert result["all_tied_day_share"] == 3 / 40
    assert result["status"] == "DEGENERATE"


def test_boundary_ties_are_order_independent_in_spread_and_replays() -> None:
    rng = np.random.default_rng(32)
    signal = np.tile([3.0, 2.0, 0.0, 0.0, 0.0, -1.0, -2.0, -3.0, -4.0, -5.0], (12, 1))
    outcome = rng.normal(0, 0.02, signal.shape)
    symbols = list("ABCDEFGHIJ")
    result = judge.spread(signal, outcome, 1, symbols, "a" * 64, horizon=7, n_resamples=20)
    expected = np.array([1.0, 1.0, 1 / 3, 1 / 3, 1 / 3, 0.0, 0.0, 0.0, 0.0, 0.0]) / 3
    for _ in range(12):
        order = rng.permutation(10)
        permuted = judge.spread(
            signal[:, order], outcome[:, order], 1, symbols, "a" * 64, horizon=7, n_resamples=20
        )
        assert permuted == result
        row = signal[0, order]
        targets, _, _, _ = clocks.clock_targets(
            row[None, :],
            np.ones((1, 10)),
            [date(2021, 1, 1)],
            symbols,
            1,
            "weekly",
            top_fraction=1 / 3,
            min_names=5,
        )
        assert [t.target_weight for t in targets] == pytest.approx(expected[order])
        weights = membership.replay_weights(
            row,
            np.ones(10),
            np.zeros(10),
            np.ones(10),
            rebalance=True,
            direction=1,
            min_names=5,
            fraction=1 / 3,
        )
        np.testing.assert_array_equal(weights, [t.target_weight for t in targets])


def test_tie_free_spread_matches_pinned_original_bytes() -> None:
    rng = np.random.default_rng(18)
    signal = rng.normal(size=(12, 10))
    outcome = rng.normal(0, 0.02, (12, 10))
    result = judge.spread(
        signal, outcome, 1, list("ABCDEFGHIJ"), "a" * 64, horizon=7, n_resamples=50
    )
    assert judge.sha(judge.canonical(result)) == (
        "315cb19a122ce72443879870b0045652711a943ac00bec5a8f58ac4a753e79e8"
    )


@pytest.mark.parametrize("direction", [1, -1])
def test_tie_free_replay_weights_are_exact(direction: int) -> None:
    rng = np.random.default_rng(40)
    signal = rng.normal(size=(15, 10))
    closes = rng.uniform(80, 120, signal.shape)
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(15)]
    targets, _, _, _ = clocks.clock_targets(
        signal,
        closes,
        days,
        list("ABCDEFGHIJ"),
        direction,
        "weekly",
        top_fraction=1 / 3,
        min_names=5,
    )
    base = np.zeros(10)
    base_closes = closes[0]
    for i, row in enumerate(signal):
        if i % 7 == 0:
            selected = sorted(range(10), key=lambda j: (-direction * row[j], j))[:3]
            base = np.array([1 / 3 if j in selected else 0.0 for j in range(10)])
            base_closes = closes[i]
            expected = base
        else:
            expected = base * (closes[i] / base_closes)
            expected /= expected.sum()
        actual = [t.target_weight for t in targets[i * 10 : (i + 1) * 10]]
        np.testing.assert_array_equal(actual, expected)
        weights = membership.replay_weights(
            row,
            closes[i],
            base,
            base_closes,
            rebalance=i % 7 == 0,
            direction=direction,
            min_names=5,
            fraction=1 / 3,
        )
        np.testing.assert_array_equal(weights, expected)


@pytest.mark.parametrize(
    "selector",
    [
        "df['$funding_sum']",
        "df.get('$funding_sum')",
        "df.filter(items=['$funding_sum'])",
        "df.__getitem__('$funding_sum')",
    ],
)
def test_input_columns_only_read_selectors(tmp_path: Path, selector: str) -> None:
    code = ("# df['$funding_last']\nnote = '$funding_count'\nx = " + selector).encode()
    digest = judge.sha(code)
    (tmp_path / "code").mkdir()
    (tmp_path / "code" / f"{digest}.py").write_bytes(code)
    (tmp_path / "panel").mkdir()
    (tmp_path / "panel/funding.parquet").write_bytes(b"funding")
    row: dict[str, Any] = {}
    with patch.object(ev, "funding_eligibility", return_value=np.ones((1, 5), dtype=bool)):
        ev._factor_eligibility(
            tmp_path,
            {"code_sha256": digest, "status": "OK"},
            row,
            [date(2021, 1, 1)],
            list("ABCDE"),
            None,
        )
    assert row["input_columns"] == ["$funding_sum"]
    assert row["input_columns_method"] == "source-selectors"
    assert row["eligibility"] == "perp-funding"


def test_input_columns_detection_miss_is_disclosed(tmp_path: Path) -> None:
    code = b"column = '$' + 'close'\nx = df[column]"
    digest = judge.sha(code)
    (tmp_path / "code").mkdir()
    (tmp_path / "code" / f"{digest}.py").write_bytes(code)
    row: dict[str, Any] = {}
    ev._factor_eligibility(tmp_path, {"code_sha256": digest, "status": "OK"}, row, [], [], None)
    assert row["input_columns_method"].startswith("fallback:")
    assert row.get("input_columns", []) == []


def test_feedback_separates_global_looks_from_family_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALPHA_FACTOR_TRIAL_LEDGER", raising=False)
    ns = judge_namespace()
    rows = [
        {
            "schema": "AlphaRdagentFactorTrialV1",
            "name": f"funding_{i}d",
            "status": "SCREEN_FAIL",
            "screen": {},
            "q": 1.0,
            "run_id": "r",
            "code_sha256": str(i),
            "family_size": 240,
            "screen_m": 240,
        }
        for i in range(2)
    ]
    text = ns["family_summary"](rows, 3)
    assert "failed tries in this idea family (futures funding): 2 of the limit 3" in text
    line = ns["ledger_summary"](rows[0])
    assert "looks so far across all ideas: 240 (sets the screen cutoff)" in line


@pytest.mark.parametrize("source,offered", [("binance-spot", False), ("alpaca-us-equities", True)])
def test_proposer_families_follow_universe_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str, offered: bool
) -> None:
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    monkeypatch.delenv("ALPHA_FACTOR_TRIAL_LEDGER", raising=False)
    (tmp_path / "panel").mkdir()
    spec = {"source": source}
    (tmp_path / "panel/universe.json").write_bytes(judge.canonical(spec))
    (tmp_path / "panel/panel-receipt.json").write_text(
        json.dumps(
            {
                "instruments": {"A": {}},
                "universe_text": "synthetic",
                "universe_sha256": judge.sha(judge.canonical(spec)),
            }
        )
    )
    ns = judge_namespace()
    families = {
        "other: overnight_drift",
        "other: intraday_drift",
        "other: overnight_minus_intraday",
    }
    text = ns["family_permissions"](set(), families)
    opened = text.split("open families: ")[1].split(". ")[0]
    for family in families:
        assert (family in opened) is offered
    if not offered:
        assert "24/7" in text and "midnight" in text


def test_bucket_report_uses_fractional_thirds() -> None:
    signal = np.array([[3.0, 2.0, 0.0, 0.0, 0.0, -1.0, -2.0, -3.0, -4.0, -5.0]])
    returns = np.array([[0.1, 0.2, 0.9, -0.3, 0.6, 0.0, 0.0, -0.1, -0.2, -0.3]])
    buckets, daily = ev._bucket_frames(signal, returns, [date(2021, 1, 1)], list("ABCDEFGHIJ"), 1)
    expected = (0.1 + 0.2 + (0.9 - 0.3 + 0.6) / 3) / 3
    assert buckets.filter(buckets["bucket"] == 3)["mean_outcome"][0] == pytest.approx(expected)
    assert daily.filter(daily["bucket"] == 3)["mean_outcome"][0] == pytest.approx(expected)


def test_fractional_turnover_and_cost_are_weighted() -> None:
    a = np.array([3.0, 2.0, 0.0, 0.0, 0.0, -1.0, -2.0, -3.0, -4.0, -5.0])
    b = np.array([3.0, 2.0, -1.0, 0.0, 0.0, 0.0, -2.0, -3.0, -4.0, -5.0])
    signal = np.stack([a, b, a])
    returns = np.random.default_rng(8).normal(0, 0.02, signal.shape)
    result = judge.spread(
        signal, returns, 1, list("ABCDEFGHIJ"), "b" * 64, horizon=7, n_resamples=20
    )
    # One third of one slot in a three-slot portfolio changes per rebalance.
    assert result["top_share_changed_per_rebalance"] == pytest.approx(1 / 9)
    assert result["estimated_annual_cost"] == pytest.approx((1 / 9) * 2 * 16 / 10000 * 365 / 7)


def test_rendered_ledger_row_has_both_counts_without_recounting_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ALPHA_FACTOR_RUN_DIR", raising=False)
    ns = judge_namespace()
    rows = [
        {
            "schema": "AlphaRdagentFactorTrialV1",
            "name": f"funding_{i}d",
            "status": status,
            "screen": {},
            "q": 1.0,
            "run_id": "r",
            "code_sha256": str(i),
            "family_size": 240,
            "screen_m": 240,
        }
        for i, status in enumerate(["SCREEN_FAIL", "SPREAD_FAIL", "FAILED", "CANDIDATE"])
    ]
    rows += [dict(rows[0]), {**rows[0], "status": "REPEAT"}]
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
    monkeypatch.setenv("ALPHA_FACTOR_TRIAL_LEDGER", str(ledger))
    monkeypatch.setenv("ALPHA_FACTOR_FAMILY_SWITCH_AFTER", "3")
    context: dict[str, Any] = {"hypothesis_and_feedback": ""}
    ns["append_ledger_context"](context, str(ledger), "synthetic", 0)
    line = next(
        line
        for line in context["hypothesis_and_feedback"].splitlines()
        if line.startswith("funding_1d:")
    )
    assert "looks so far across all ideas: 240 (sets the screen cutoff)" in line
    assert "failed tries in this idea family (futures funding): 2 of the limit 3" in line
    assert ns["closed_families"]() == set()


def replay_inputs() -> tuple[Any, np.ndarray, list[date]]:
    import polars as pl

    rng = np.random.default_rng(57)
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(16)]
    prices = 100 * np.cumprod(1 + rng.normal(0, 0.02, (18, 10)), axis=0)
    signal = rng.normal(size=(16, 10))
    panel = pl.DataFrame(
        {
            "date": [days[0] + timedelta(days=i) for i in range(18) for _ in range(10)],
            "instrument": list("ABCDEFGHIJ") * 18,
            "open": prices.ravel(),
            "close": prices.ravel(),
            "high": (prices * 1.01).ravel(),
            "low": (prices * 0.99).ravel(),
            "volume": [100.0] * 180,
            "quote_volume": [10000.0] * 180,
        }
    )
    return panel, signal, days


def test_tied_replay_returns_costs_turnover_ignore_name_order() -> None:
    import polars as pl

    panel, signal, days = replay_inputs()
    signal[:] = [3.0, 2.0, 0.0, 0.0, 0.0, -1.0, -2.0, -3.0, -4.0, -5.0]
    order = [4, 2, 9, 0, 8, 3, 7, 1, 6, 5]
    names = list("ABCDEFGHIJ")
    mapping = {names[j]: names[i] for i, j in enumerate(order)}
    renamed = panel.with_columns(pl.col("instrument").replace_strict(mapping))
    for gaps in (False, True):
        # Supply membership directly so this short fixture can exercise the gap replay account.
        with patch.object(
            judge, "panel_membership", return_value=np.ones(signal.shape, dtype=bool)
        ):
            before, net_before = judge.replay(
                panel, signal, days, 1, clock="weekly", gap_policy=gaps
            )
            after, net_after = judge.replay(
                renamed, signal[:, order], days, 1, clock="weekly", gap_policy=gaps
            )
        for key in ("annual_cost", "mean_turnover", "turnover_per_rebalance"):
            assert after[key] == pytest.approx(before[key], abs=1e-12)
        np.testing.assert_allclose(net_after, net_before, atol=1e-12, rtol=0)
        assert before["annual_cost"] > 0


@pytest.mark.parametrize(
    "gaps,digest",
    [
        (False, "1f7a0ab804563b076d8045c4019764b5c6c826211a26587fe2158ed8ac81e460"),
        (True, "49cb008b5989a77654702f8f1c629fdbb00767b6f1568b3d9589c83d6ce795ab"),
    ],
)
def test_tie_free_replay_metrics_match_original_bytes(gaps: bool, digest: str) -> None:
    # Pinned using HEAD's original clock_targets and replay_weights before this change.
    panel, signal, days = replay_inputs()
    with patch.object(judge, "panel_membership", return_value=np.ones(signal.shape, dtype=bool)):
        metrics, returns = judge.replay(panel, signal, days, 1, clock="weekly", gap_policy=gaps)
    metrics.pop(
        "tie_break", None
    )  # Wording changed; every numerical figure remains byte-identical.
    assert judge.sha(judge.canonical({"metrics": metrics, "returns": returns.tolist()})) == digest


def test_unknown_trial_schema_does_not_enter_family_failure_counts() -> None:
    ns = judge_namespace()
    assert (
        ns["family_definitions"]().family_failure_counts(
            [{"schema": "AlphaRdagentFactorTrialV999"}]
        )
        == {}
    )


def test_failed_spread_feedback_prints_the_checked_figure() -> None:
    signal = np.tile([3.0, 2.0, 0.0, 0.0, 0.0, -1.0, -2.0, -3.0, -4.0, -5.0], (3, 1))
    outcome = np.tile([0.0, 0.0, -0.9, 0.1, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0], (3, 1))
    outcome *= np.array([[1.0], [0.5], [2.0]])
    result = judge.spread(
        signal, outcome, 1, list("ABCDEFGHIJ"), "b" * 64, horizon=7, n_resamples=20
    )
    assert result["status"] == "FAIL"
    assert result["mean_spread"] == result["alternate_tie_order_mean_spread"] < 0
    ns = judge_namespace()
    assert ns["percent"](result["annualized_spread"], signed=True) in ns["spread_line"](
        "weekly", result
    )
    assert clocks.figure(result["annualized_spread"], percent=True) in clocks.spread_note(result)


def test_family_permissions_without_source_keep_existing_suggestions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_FACTOR_RUN_DIR", str(tmp_path))
    monkeypatch.delenv("ALPHA_FACTOR_TRIAL_LEDGER", raising=False)
    ns = judge_namespace()
    family = "other: overnight_drift"
    assert family in ns["family_permissions"](set(), {family})
    (tmp_path / "panel").mkdir()
    (tmp_path / "panel/universe.json").write_text(json.dumps({"survivorship": "survivors only"}))
    (tmp_path / "panel/panel-receipt.json").write_text(json.dumps({"instruments": {"A": {}}}))
    assert family in ns["family_permissions"](set(), {family})


def test_tie_free_screen_restores_original_bytes_without_new_fields() -> None:
    rng = np.random.default_rng(18)
    signal = rng.normal(size=(40, 10))
    outcome = rng.normal(size=signal.shape)
    result = judge.screen(signal, outcome, "a" * 64, n_resamples=20)
    assert result.pop("all_tied_day_share") == result["tie_share"] == 0
    assert result.pop("boundary_tie_share") == 0
    # Pinned from main's screen; ten significant digits absorb last-bit platform differences.
    assert judge.sha(judge.canonical(_rounded(result))) == (
        "9600c8d01a110e9c93c2c7a810930fa99279d7c2bac769c957704f5ab165fbe6"
    )


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return float(f"{value:.10g}")
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_rounded(item) for item in value]
    return value


def test_family_filter_rejects_changed_frozen_source(tmp_path: Path) -> None:
    ns = judge_namespace()
    (tmp_path / "panel").mkdir()
    spec = {"source": "binance-spot"}
    (tmp_path / "panel/panel-receipt.json").write_text(
        json.dumps({"universe_sha256": judge.sha(judge.canonical(spec))})
    )
    (tmp_path / "panel/universe.json").write_text(json.dumps({"source": "alpaca-us-equities"}))
    with pytest.raises(ValueError, match="differs from the frozen receipt"):
        ns["family_definitions"]().universe_source(str(tmp_path))


def test_single_name_day_stays_in_the_top_bucket_only() -> None:
    signal = np.full((2, 6), np.nan)
    signal[0, 2] = 0.7
    signal[1] = np.arange(6.0)
    returns = np.full(signal.shape, 0.01)
    _, daily = ev._bucket_frames(
        signal, returns, [date(2021, 1, 1), date(2021, 1, 2)], list("ABCDEF"), 1
    )
    first = daily.filter(daily["date"] == date(2021, 1, 1))
    assert first.filter(first["bucket"] == 3)["mean_outcome"][0] == pytest.approx(0.01)
    assert first.filter(first["bucket"] == 1)["mean_outcome"][0] is None
