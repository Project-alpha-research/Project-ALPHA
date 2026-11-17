"""Deflation and clock presentation regressions; recorded inputs only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from alpha_cli import _rdagent_clocks as clocks
from alpha_cli._rdagent_stability import writeoff_summary
from alpha_cli.spine.trial_record import map_row
from tests.unit.test_trial_record import factor


def clock_rows(dsr: float) -> dict[str, Any]:
    return {
        c: {
            "status": "PASS" if c == "weekly" else "SCREEN_FAIL",
            "p": p,
            "q": p,
            "screen": {"mean_ic": p},
            "spread": {"status": "PASS", "horizon_days": 7, "decision_days": 50},
            "replay": {"deflated_sharpe": {"dsr": dsr, "threshold": 0.95, "n_trials": 42}}
            if c == "weekly"
            else {},
        }
        for c, p in (("daily", 0.5), ("weekly", 0.04), ("monthly", 0.7))
    }


@pytest.mark.parametrize(
    "value,status", [(0.04, "DEFLATION_FAIL"), (0.95, "CANDIDATE"), (0.96, "CANDIDATE")]
)
def test_candidate_requires_recorded_deflation(value: float, status: str) -> None:
    assert clocks.overall_status(clock_rows(value)) == (status, "weekly")


def test_missing_deflation_cannot_be_candidate() -> None:
    trials = clock_rows(0.99)
    trials["weekly"]["replay"] = {}
    assert clocks.overall_status(trials)[0] != "CANDIDATE"


def test_old_candidate_derived_without_rewriting_and_counts(tmp_path: Path) -> None:
    row = factor(clocks=clock_rows(0.04))
    record = map_row("rdagent", tmp_path / "ledger", 1, row)
    assert record.raw_status == "DEFLATION_FAIL" and record.outcome == "rejected"
    assert record.counts_for_deflation and row["status"] == "CANDIDATE"
    assert record.reason is not None
    assert all(s in record.reason for s in ("derived", "0.04", "0.95", "42 trials"))


def test_reader_figures_come_from_one_named_clock(tmp_path: Path) -> None:
    record = map_row("rdagent", tmp_path / "ledger", 1, factor(clocks=clock_rows(0.99)))
    assert record.measures["q"] == record.measures["mean_ic"] == 0.04
    assert record.measure_clock == "weekly"


def test_feedback_contains_deflation_for_every_replay() -> None:
    row = factor(clocks=clock_rows(0.04), status="DEFLATION_FAIL")
    assert all(s in clocks.clock_feedback(row) for s in ("0.04", "0.95", "42 trials"))


def test_every_factor_status_has_reason(tmp_path: Path) -> None:
    from alpha_cli.spine.trial_record import FACTOR_OUTCOMES

    for status in FACTOR_OUTCOMES:
        record = map_row(
            "rdagent", tmp_path / "ledger", 1, factor(status=status, clocks=clock_rows(0.04))
        )
        assert record.reason, status
    record = map_row("rdagent", tmp_path / "ledger", 1, factor(status="FAST_ONLY"))
    assert record.reason == "passed the fast screen only; the slower clocks failed"


def test_writeoffs_positions_in_coins() -> None:
    row = {
        "name": "idea",
        "clocks": {
            "weekly": {"replay": {"haircuts_applied": 4, "writeoff_instruments": ["A", "B"]}}
        },
    }
    assert "4 positions in 2 coins were written off" in writeoff_summary(row, 0.3)[1]


def test_plain_factor_stems() -> None:
    from alpha_cli.rdagent_factor_eval import plain_name

    assert (
        plain_name("ltr_mdd_vwap_60d")
        == "Long-term reversal max drawdown VWAP distance over 60 days"
    )


def test_plain_ledger_names_clock_beside_figures(tmp_path: Path) -> None:
    from dataclasses import asdict

    from alpha_cli.ledger_cmds import _render

    record = map_row("rdagent", tmp_path / "ledger", 1, factor(clocks=clock_rows(0.99)))
    assert "weekly: IC 0.04, q 0.04" in _render({"records": [asdict(record)]})
