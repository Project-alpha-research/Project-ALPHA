"""Hand-computed opposite-direction execution and descriptive control contracts."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from alpha_cli import _runner
from alpha_cli.spine import controls
from alpha_cli.spine.run import assemble_run_spec
from alpha_cli.spine.spec import load_spec
from alpha_core import Bar


def _bars() -> list[Bar]:
    prices = [100, 100, 110, 110, 120, 90, 90, 90, 90, 90, 90, 90]
    return [
        Bar(
            symbol="SPY",
            ts=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i),
            open=p,
            high=p,
            low=p,
            close=p,
            volume=1000000,
        )
        for i, p in enumerate(prices)
    ]


@pytest.mark.parametrize(
    "rule,params",
    [
        ("ma_cross", ["fast=1", "slow=2"]),
        ("breakout", ["window=2"]),
        ("tsmom", ["lookback=1", "skip=0"]),
    ],
)
def test_inversion_next_open_known_pnl_and_ledger_unchanged(
    tmp_path: Path, rule: str, params: list[str]
) -> None:
    from alpha_cli.spine.ledger import append_trial

    append_trial(tmp_path, {"run_id": "prior", "labels": []})
    ledger = tmp_path / "ledger/trials.jsonl"
    before = ledger.read_bytes()
    idea = load_spec(None, rule=rule, param=params, asset=["SPY"], fee_bps=0, slippage_bps=0)
    spec = replace(assemble_run_spec(idea, "SPY", 252, 100), starting_cash=11000)
    original = _runner.run_full_backtest(_bars(), spec)
    inverted = controls.run_inverted_backtest(_bars(), spec, original)
    # Entry decided at close 110, filled next open 110; 99 units, flat at next open 120. The
    # control's book is CONTROL_CAPITAL_SCALE times larger: floor(11e6 * 0.998 / 110) = 99,800.
    assert controls.CONTROL_CAPITAL_SCALE == 1000
    assert len(original.trades) == len(inverted.trades) == 2
    assert original.trades[0].realized_pnl == pytest.approx(990)
    assert inverted.trades[0].realized_pnl == pytest.approx(-99_800 * 10)
    assert inverted.trades[0].entry_ts == original.trades[0].entry_ts
    assert inverted.trades[0].exit_ts == original.trades[0].exit_ts
    assert inverted.fill_trace[0].side == "SELL"
    assert original.fill_trace[0].side == "BUY"
    assert ledger.read_bytes() == before
    charged = replace(spec, fee_bps=10, slippage_bps=10)
    full_costs = _runner.run_full_backtest(_bars(), charged)
    inverse_costs = controls.run_inverted_backtest(_bars(), charged, full_costs)
    assert full_costs.trades[0].realized_pnl < 990
    assert inverse_costs.trades[0].realized_pnl < -99_800 * 10


@pytest.mark.parametrize(
    "original,inverted,n,m,label",
    [
        (1, -0.4, 30, 30, "control passed"),
        (1, 0.5, 30, 30, "control failed"),
        (1, 0.49, 30, 30, "inconclusive"),
        (1, 0, 30, 30, "inconclusive"),
        (-1, 0.6, 30, 30, "inconclusive"),
        (0, 0.6, 30, 30, "inconclusive"),
        (-1, -0.6, 30, 30, "control passed"),
        (1, -0.4, 29, 30, "inconclusive"),
        (1, 0.6, 30, 29, "inconclusive"),
        (None, -0.4, 30, 30, "inconclusive"),
    ],
)
def test_label_order(original: float | None, inverted: float, n: int, m: int, label: str) -> None:
    assert controls.control_label(original, inverted, n, m) == label


_ORIGINAL = {"sharpe": 1.0, "total_return": 0.2, "trades": 30}


def test_control_sentence_se_and_hypothetical() -> None:
    section = controls.inverted_summary(
        _ORIGINAL, [100, 110, 98], 30, 2, hypothetical=True, market_return=-0.1
    )
    assert section["inverted_total_return"] == pytest.approx(-0.02)
    sharpe = section["inverted_sharpe"]
    assert sharpe < 0
    # Lo (2002) IID-normal SE, annualised: sqrt((ppy + SR**2 / 2) / n) with ppy = n = 2.
    assert section["inverted_sharpe_se"] == pytest.approx(((2 + sharpe**2 / 2) / 2) ** 0.5)
    assert section["label"] == "control passed"
    assert "Trading the opposite of this rule lost money" in section["sentence"]
    assert "does not prove an edge" in section["sentence"]
    assert "standard error" in section["sentence"]
    assert "Shorts are not tradable here; this is a control only." in section["sentence"]
    assert "No borrowing or funding cost is charged" in section["sentence"]
    assert "weak here" not in section["sentence"]
    flat = controls.inverted_summary(
        _ORIGINAL, [100, 100, 100], 30, 252, hypothetical=False, market_return=0.1
    )
    assert flat["label"] == "inconclusive"
    assert flat["inverted_sharpe_se"] is None
    assert flat["reasons"]["inverted_sharpe_se"]
    assert "Shorts are not tradable" not in flat["sentence"]
    assert "No borrowing or funding cost is charged" in flat["sentence"]


def test_passed_control_on_a_rising_market_says_the_check_is_weak() -> None:
    section = controls.inverted_summary(
        _ORIGINAL, [100, 110, 98], 30, 2, hypothetical=False, market_return=0.5
    )
    assert section["label"] == "control passed"
    assert section["market_total_return"] == pytest.approx(0.5)
    assert "The market rose over this period" in section["sentence"]
    assert "this check is weak here" in section["sentence"]


def test_passed_label_on_a_losing_rule_does_not_read_as_evidence() -> None:
    losing = {"sharpe": -0.3, "total_return": -0.1, "trades": 40}
    section = controls.inverted_summary(
        losing, [100, 110, 98], 40, 2, hypothetical=False, market_return=None
    )
    assert section["label"] == "control passed"  # the binding label order, step 3
    assert "the rule itself did not make money either" in section["sentence"]
    assert "says nothing about an edge" in section["sentence"]


def test_failed_and_few_trade_sentences() -> None:
    failed = controls.inverted_summary(
        _ORIGINAL, [100, 101, 102, 103.5], 30, 2, hypothetical=False, market_return=0.3
    )
    assert failed["label"] == "control failed"
    assert "also made money on average" in failed["sentence"]
    assert "the market's drift" in failed["sentence"]
    few = controls.inverted_summary(
        _ORIGINAL, [100, 110, 99], 12, 2, hypothetical=False, market_return=0.3
    )
    assert few["label"] == "inconclusive"
    assert "fewer than 30 closed trades" in few["sentence"]
    assert "rule 30, opposite 12" in few["sentence"]
    assert "For the record, the opposite had Sharpe" in few["sentence"]


def test_unavailable_control_is_recorded_not_raised() -> None:
    section = controls.unavailable_control(_ORIGINAL, "inverted control had 2 rejected orders")
    assert section["label"] is None
    assert section["inverted_sharpe"] is None
    assert section["reasons"]["label"] == "inverted control had 2 rejected orders"
    assert section["reasons"]["inverted_sharpe"] == "inverted control had 2 rejected orders"
    assert "could not be run" in section["sentence"]
    ruined = controls.unavailable_control(
        _ORIGINAL, "portfolio analytics require positive finite equity, got -5.0"
    )
    assert "lost more than its whole stake" in ruined["sentence"]
    assert ruined["reasons"]["label"].startswith("portfolio analytics")


def _equity(returns: list[float]) -> list[float]:
    values = [100.0]
    for value in returns:
        values.append(values[-1] * (1 + value))
    return values


def _fold(index: int, train_end: int, oos_cagr: float) -> dict[str, Any]:
    return {"index": index, "train_start": 0, "train_end": train_end, "oos_cagr": oos_cagr}


def test_wfe_reads_the_recorded_train_window_after_warm_up() -> None:
    # Three warm-up returns (no position possible), then 1% a period; 10 periods a year.
    equity = _equity([0.0, 0.0, 0.0] + [0.01] * 6)
    rows = controls.in_sample_rows(
        [_fold(0, 3, 0.2), _fold(1, 6, 0.05)], equity, 10, first_tradable=3
    )
    assert rows[0]["is_cagr"] is None
    assert rows[0]["is_reason"] == "in-sample window is warm-up only; the rule could not trade yet"
    assert rows[1]["is_cagr"] == pytest.approx(1.01**10 - 1)
    assert (rows[1]["is_start"], rows[1]["is_end"]) == (3, 6)
    result = controls.walk_forward_efficiency(rows)
    assert result["wfe"] == pytest.approx(0.05 / (1.01**10 - 1))
    assert result["fold_count"] == 1 and result["folds_total"] == 2
    assert "median of 1 of 2 folds" in result["sentence"]
    assert "left out: 1 still warming up" in result["sentence"]


def test_wfe_two_folds() -> None:
    result = controls.walk_forward_efficiency(
        [
            {"index": 0, "is_cagr": 0.2, "oos_cagr": 0.1},
            {"index": 1, "is_cagr": 0.1, "oos_cagr": 0.08},
        ]
    )
    assert [f["wfe"] for f in result["folds"]] == pytest.approx([0.5, 0.8])
    assert result["wfe"] == pytest.approx(0.65)
    assert result["fold_count"] == result["folds_total"] == 2
    assert "practitioner rule of thumb, not a statistical test" in result["basis"]
    assert "65%" in result["sentence"] and "median of 2 folds" in result["sentence"]
    assert "threshold" not in result and "label" not in result


@pytest.mark.parametrize(
    "folds,reason",
    [
        ([], "this run recorded no in-sample segment"),
        ([{"index": 0, "oos_cagr": 0.1}], "this run recorded no in-sample segment"),
        ([{"index": 0, "is_cagr": 0.0, "oos_cagr": 0.1}], "in-sample return is zero or negative"),
        ([{"index": 0, "is_cagr": -0.1, "oos_cagr": 0.1}], "in-sample return is zero or negative"),
        (
            [{"index": 0, "is_cagr": 0.1, "oos_cagr": float("nan")}],
            "this fold recorded no usable out-of-sample return",
        ),
    ],
)
def test_wfe_null(folds: list[dict[str, float]], reason: str) -> None:
    result = controls.walk_forward_efficiency(folds)
    assert result["wfe"] is None
    assert result["reasons"]["wfe"] == reason
    assert reason in result["sentence"]
    assert "practitioner rule of thumb, not a statistical test" in result["sentence"]


def test_wfe_median_uses_defined_folds_and_names_the_rest() -> None:
    result = controls.walk_forward_efficiency(
        [
            {"index": 0, "is_cagr": 0.2, "oos_cagr": 0.1},
            {"index": 1, "is_cagr": -0.1, "oos_cagr": 0.08},
            {"index": 2, "is_cagr": 0.1, "oos_cagr": -0.05},
        ]
    )
    assert result["wfe"] == pytest.approx(0.0)
    assert result["folds"][1]["wfe"] is None
    assert result["folds"][1]["reason"] == "in-sample return is zero or negative"
    assert result["fold_count"] == 2 and result["folds_total"] == 3
    assert "left out: 1 with no in-sample gain" in result["sentence"]


def _rising(n: int) -> list[Bar]:
    return [
        Bar(
            symbol="SPY",
            ts=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i),
            open=100 + i,
            high=100 + i,
            low=100 + i,
            close=100 + i,
            volume=1000000,
        )
        for i in range(n)
    ]


def test_short_is_resized_on_equity_net_of_its_dividend_debit() -> None:
    from alpha_core import ActionType, CorporateAction

    bars = _rising(14)
    idea = load_spec(None, rule="tsmom", param=["lookback=1", "skip=0"], asset=["SPY"])
    spec = replace(
        assemble_run_spec(idea, "SPY", 252, 100), fee_bps=0, slippage_bps=0, starting_cash=11000
    )
    ex = bars[6].ts.date()
    dividend = CorporateAction(
        symbol="SPY", action_type=ActionType.DIVIDEND, ex_date=ex, pay_date=ex, amount=5.0
    )
    original = _runner.run_full_backtest(bars, spec, dividends=[dividend])
    plain = controls.run_inverted_backtest(bars, spec, original)
    debited = controls.run_inverted_backtest(bars, spec, original, dividends=[dividend])
    after = [row for row in debited.decision_trace if row.ts.date() >= ex]
    before = [row for row in plain.decision_trace if row.ts.date() >= ex]
    # The short pays the dividend; sizing sees that debit and holds fewer units from then on.
    assert abs(after[0].target_quantity) < abs(before[0].target_quantity)
    assert min(value for _, value in debited.equity_curve) > 0


def test_a_shrinking_short_book_keeps_trading_whole_units() -> None:
    # The opposite of a long rule on a market that rises ~10x loses most of its book; whole-unit
    # rounding must not round the short to zero units and silently end the control early.
    rise = [100.0 * 1.08**i for i in range(31)]  # 100 -> ~1,006 while the rule is long
    prices = [100.0] * 12 + rise + [900.0, 800.0, 900.0, 1000.0, 1100.0, 1000.0, 900.0]
    bars = [
        Bar(
            symbol="SPY",
            ts=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i),
            open=p,
            high=p,
            low=p,
            close=p,
            volume=1000000,
        )
        for i, p in enumerate(prices)
    ]
    idea = load_spec(None, rule="tsmom", param=["lookback=1", "skip=0"], asset=["SPY"])
    spec = replace(
        assemble_run_spec(idea, "SPY", 252, 100), fee_bps=0, slippage_bps=0, starting_cash=2000
    )
    original = _runner.run_full_backtest(bars, spec)
    inverted = controls.run_inverted_backtest(bars, spec, original)
    assert len(original.trades) >= 2
    assert len(inverted.trades) == len(original.trades)
    assert [t.exit_ts for t in inverted.trades] == [t.exit_ts for t in original.trades]
