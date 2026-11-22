"""The judge and the daily rule study read their costs from the one cost table."""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from typing import Any

import numpy as np
import polars as pl
import pytest

from alpha_cli import _rdagent_costs as costs
from alpha_cli import _rdagent_judge as judge
from alpha_cli._native_daily_rule_study import daily_rule_terms_proposal
from alpha_cli.spine import cost_classes


def _bars() -> pl.DataFrame:
    rows = []
    for j in range(5):
        for i in range(40):
            price = 100.0 + 10 * j + i
            rows.append(
                {
                    "date": date(2020, 12, 1) + timedelta(days=i),
                    "instrument": f"C{j}",
                    "open": price,
                    "close": price,
                    "high": price,
                    "low": price,
                    "volume": 1.0,
                    "quote_volume": 1.0,
                }
            )
    return pl.DataFrame(rows)


def _annual_cost() -> float:
    days = [date(2021, 1, 1) + timedelta(days=i) for i in range(5)]
    scores = np.tile(np.array([5.0, 1.0, 2.0, 3.0, 4.0]), (5, 1))
    metrics, _ = judge.replay(_bars(), scores, days, 1, series={}, gap_policy=True)
    return float(metrics["annual_cost"])


def test_judge_uses_the_crypto_spot_row() -> None:
    row = cost_classes.ROWS["crypto_spot"]
    assert costs.judge_costs() == {
        "fee_bps": row.fee_bps,
        "slippage_bps": row.slippage_bps,
        "source": "class-default",
        "asset_class": "crypto_spot",
    }
    assert (row.fee_bps, row.slippage_bps) == (10.0, 5.0)


def test_judge_keeps_no_cost_constants_of_its_own() -> None:
    assert not hasattr(judge, "FEE_BPS") and not hasattr(judge, "SLIPPAGE_BPS")
    assert "fee_bps" not in judge.CONFIG and "slippage_bps" not in judge.CONFIG


def test_a_table_change_reaches_the_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    before = _annual_cost()
    row = dataclasses.replace(cost_classes.ROWS["crypto_spot"], fee_bps=40.0, slippage_bps=20.0)
    monkeypatch.setitem(cost_classes.ROWS, "crypto_spot", row)
    assert costs.judge_costs()["fee_bps"] == pytest.approx(40.0, rel=1e-9, abs=1e-12)
    assert _annual_cost() > before * 2


def test_a_us_etf_row_would_be_read_by_class(monkeypatch: pytest.MonkeyPatch) -> None:
    etf = cost_classes.ROWS["us_large_etf"]
    monkeypatch.setattr(costs, "JUDGE_COST_CLASS", "us_large_etf")
    got = costs.judge_costs()
    assert (got["fee_bps"], got["slippage_bps"]) == (etf.fee_bps, etf.slippage_bps)
    assert got["asset_class"] == "us_large_etf"


def test_old_stored_scores_are_not_altered_and_are_named() -> None:
    now = costs.judge_costs()
    old: dict[str, Any] = {"status": "CANDIDATE", "replay": {"net": {"x": 1}}}
    same = {"status": "PASS", "costs": dict(now)}
    repeat = {"status": "REPEAT"}
    history = [old, same, repeat]
    snapshot = repr(history)
    assert costs.other_cost_rows(history, now) == 1
    assert repr(history) == snapshot
    assert "1 earlier scores were made under other costs" in costs.other_cost_note(1)
    assert costs.other_cost_note(0) == ""


def test_daily_rule_study_terms_match_the_table() -> None:
    # The study file is hash-bound for daily approvals, so it cannot import the unbound table;
    # its stated terms must equal the crypto spot row.
    economics, _ = daily_rule_terms_proposal()
    row = cost_classes.ROWS["crypto_spot"]
    assert economics.fee_bps_per_side == row.fee_bps
    assert economics.slippage_bps_per_side == row.slippage_bps
