"""An owner rule on the engine: warm-up, sizing, surrogate agreement and no look-ahead."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from alpha_backtest.results import BacktestResult
from alpha_cli import _runner
from alpha_cli._strategies import surrogate_for, warmup_for
from alpha_cli.spine.run import assemble_run_spec
from alpha_cli.spine.spec import IdeaSpec
from alpha_core import Bar
from alpha_strategies.rules import (
    canonical_json,
    parse_rule_spec,
    rule_signal,
    rule_spec_from_json,
)

CLOSE_ONLY: dict[str, Any] = {
    "long_when": [
        {"left": {"indicator": "rsi", "params": [14]}, "op": "<", "right": {"value": 55}},
        {"left": {"source": "close"}, "op": ">", "right": {"indicator": "sma", "params": [20]}},
    ]
}
WITH_RANGE: dict[str, Any] = {
    "long_when": [
        {
            "left": {"indicator": "atr", "params": [5]},
            "op": ">",
            "right": {"indicator": "atr", "params": [20]},
        }
    ]
}
FACTORS = (3.0, 0.3)


def bars(n: int, seed: int = 5, poison_from: int | None = None) -> list[Bar]:
    """Synthetic OHLC: a noisy walk with real highs and lows. From ``poison_from`` on, every
    price is scaled by a large alternating factor (still a valid bar)."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1.0 + 0.0004 + rng.normal(0.0, 0.012, n))
    start = datetime(2018, 1, 1, tzinfo=UTC)
    out = []
    for i in range(n):
        previous = close[i - 1] if i else close[i]
        high = max(previous, close[i]) * (1.0 + abs(rng.normal(0.0, 0.004)))
        low = min(previous, close[i]) * (1.0 - abs(rng.normal(0.0, 0.004)))
        scale = FACTORS[i % 2] if poison_from is not None and i >= poison_from else 1.0
        out.append(
            Bar(
                symbol="SPY",
                ts=start + timedelta(days=i),
                open=previous * scale,
                high=high * scale,
                low=low * scale,
                close=float(close[i]) * scale,
                volume=1000.0,
            )
        )
    return out


def idea(spec: dict[str, Any]) -> IdeaSpec:
    return IdeaSpec.model_validate({"assets": ["SPY"], "rule": {"kind": "owner", "spec": spec}})


def signals(result: BacktestResult) -> list[int | None]:
    return [row.signal for row in result.decision_trace]


def test_owner_branch_assembles_the_rules_strategy_with_all_in_sizing() -> None:
    owner = idea(CLOSE_ONLY)
    spec = assemble_run_spec(owner, "SPY", 252, 600)
    rules = rule_spec_from_json(json.dumps(owner.rule.model_dump()["spec"]))
    assert spec.strategy_name == "rules" and spec.sizing == "all_in"
    assert spec.rules_spec == canonical_json(rules)
    assert spec.strategy_params == () and not spec.allow_short
    assert spec.account_type == "CASH"
    assert spec.train_size == spec.min_train == warmup_for(spec) == rules.history == 80
    assert assemble_run_spec(owner, "BTC/USDT", 365, 600).account_type == "MARGIN"


def _vol_target_spec() -> _runner.RunSpec:
    rules = canonical_json(
        parse_rule_spec({"name": "t", "history": 40, **CLOSE_ONLY, "short_when": []})
    )
    return _runner.RunSpec(
        lookback=10, skip=1, vol_window=63, target_vol=0.1, rebalance_every=1,
        max_leverage=1.0, allow_short=True, periods_per_year=252, fee_bps=1.0,
        slippage_bps=1.0, starting_cash=1e6, account_type="MARGIN", train_size=100,
        test_size=20, embargo=2, anchored=False, strategy_name="rules", rules_spec=rules,
    )  # fmt: skip


def test_old_lane_warmup_and_surrogate_are_unchanged() -> None:
    """The vol-target ``rules`` lane keeps its warm-up and its Tier-1 weights exactly."""
    from alpha_cli._surrogate import make_surrogate

    spec = _vol_target_spec()
    rules = rule_spec_from_json(spec.rules_spec or "")
    assert warmup_for(spec) == max(rules.history, spec.vol_window + 1) == 64

    def signal_fn(prefix: Any) -> int:
        prices = prefix[-rules.history :].tolist()
        return rule_signal(rules, prices, prices, prices)

    reference = make_surrogate(
        signal_fn=signal_fn, warmup=63, vol_window=63, target_vol=0.1, rebalance_every=1,
        periods_per_year=252, max_leverage=1.0, allow_short=True, cost_bps=2.0,
    )  # fmt: skip
    pr = np.random.default_rng(3).normal(0.0004, 0.011, 400)
    got, expected = surrogate_for(spec).weights_and_costs(pr), reference.weights_and_costs(pr)
    assert np.array_equal(got[0], expected[0]) and np.array_equal(got[1], expected[1])


def test_old_lane_engine_run_is_pinned() -> None:
    """Written against main: the vol-target ``rules`` engine run does not move."""
    result = _runner.run_full_backtest(bars(300), _vol_target_spec())
    trace = [
        (r.ts.isoformat(), r.signal, round(r.target_quantity, 6)) for r in result.decision_trace
    ]
    digest = hashlib.sha256(json.dumps(trace).encode()).hexdigest()
    assert len(trace) == 300 - 64 + 1
    assert digest == "6d04d57f4e42a021c95f47027f9082dc76599ed30e65180c0fd735603458ca67"
    assert result.equity_curve[-1][1] == pytest.approx(PIN_EQUITY, rel=1e-9, abs=1e-12)


PIN_EQUITY = 1047402.29


def run_owner(spec: dict[str, Any], rows: Sequence[Bar]) -> tuple[BacktestResult, int]:
    owner = idea(spec)
    run_spec = assemble_run_spec(owner, "SPY", 252, len(rows))
    return _runner.run_full_backtest(rows, run_spec), run_spec.min_train


def test_engine_decisions_equal_rule_signal_over_the_same_prefixes() -> None:
    rows = bars(500)
    for spec in (CLOSE_ONLY, WITH_RANGE):
        result, history = run_owner(spec, rows)
        rules = rule_spec_from_json(canonical_json(parse_rule_spec({"name": "x", **spec})))
        highs, lows, closes = (
            [float(getattr(bar, key)) for bar in rows] for key in ("high", "low", "close")
        )
        expected = [
            rule_signal(rules, highs[: i + 1], lows[: i + 1], closes[: i + 1])
            for i in range(history - 1, len(rows))
        ]
        assert signals(result) == expected
        assert set(expected) == {0, 1}, "the fixture must exercise both states"


def test_tier1_surrogate_equals_the_engine_on_the_unshuffled_series() -> None:
    rows = bars(500)
    result, history = run_owner(CLOSE_ONLY, rows)
    closes = np.asarray([bar.close for bar in rows])
    pr = closes[1:] / closes[:-1] - 1.0
    spec = assemble_run_spec(idea(CLOSE_ONLY), "SPY", 252, len(rows))
    weights, costs = surrogate_for(spec).weights_and_costs(pr)
    engine = np.asarray(signals(result)[: len(pr) - history + 1], dtype=float)
    assert np.array_equal(weights[history - 1 :], engine)
    assert not weights[: history - 1].any()
    cost_rate = (spec.fee_bps + spec.slippage_bps) / 10_000.0
    turns = np.abs(np.diff(np.concatenate([[0.0], weights])))
    assert costs == pytest.approx(cost_rate * turns, rel=1e-9, abs=1e-12)


def test_high_low_rule_agrees_with_the_engine_only_on_closes() -> None:
    """The Tier-1 null has no intrabar range: it reads closes for high and low. The label says so."""
    assert idea(WITH_RANGE).rule.labels == ("null-closes-for-high-low",)


def _decisions_to(result: BacktestResult, k: int, history: int) -> list[tuple[Any, ...]]:
    rows = result.decision_trace[: k - history + 2]
    return [(r.ts, r.signal, r.target_quantity, r.reason) for r in rows]


def _fills_to(result: BacktestResult, stamp: datetime) -> list[tuple[Any, ...]]:
    return [(f.ts, f.side, f.quantity, f.price) for f in result.fill_trace if f.ts <= stamp]


def test_prices_after_bar_k_change_no_decision_up_to_k_and_no_fill_up_to_k_plus_1() -> None:
    n, k = 400, 250
    clean = bars(n)
    owner = idea(CLOSE_ONLY)
    spec = assemble_run_spec(owner, "SPY", 252, n)
    history = spec.min_train
    base = _runner.run_full_backtest(clean, spec)
    assert len(base.fill_trace) > 4 and 0 in signals(base) and 1 in signals(base)
    # Bars from k+1 on are poisoned: decisions up to k read nothing of them.
    after = _runner.run_full_backtest(bars(n, poison_from=k + 1), spec)
    assert _decisions_to(after, k, history) == _decisions_to(base, k, history)
    assert signals(after) != signals(base)
    # The fill at the open of k+1 needs that open: poison from k+2 and it still holds.
    later = _runner.run_full_backtest(bars(n, poison_from=k + 2), spec)
    stamp = clean[k + 1].ts
    assert _fills_to(later, stamp) == _fills_to(base, stamp)
    assert _fills_to(later, stamp)


def _leaky_run(rows: Sequence[Bar], future: Sequence[float]) -> BacktestResult:
    """A rule strategy that peeks one bar ahead: the same comparison must catch it."""
    from nautilus_trader.model.enums import AccountType

    from alpha_backtest.engine import run_backtest
    from alpha_backtest.feed import bar_type_for, to_execution_feed
    from alpha_backtest.instruments import instrument_for
    from alpha_strategies.rule_strategy import RuleStrategy

    class Leaky(RuleStrategy):
        def _signal(self) -> int:
            i = len(self._closes) - 1
            return int(i + 1 < len(future) and future[i + 1] > future[i])

    instrument = instrument_for("SPY")
    bar_type = bar_type_for("SPY")
    rules = parse_rule_spec({"name": "x", **CLOSE_ONLY})
    strategy = Leaky(
        instrument_id=instrument.id, bar_type=bar_type, spec=rules, allow_short=False,
        sizing="all_in",
    )  # fmt: skip
    strategy.configure_sizing_costs(fee_bps=1.0, slippage_bps=2.0)
    feed = to_execution_feed(rows, bar_type, slippage_bps=2.0)
    return run_backtest(
        instrument, feed, strategy, starting_cash=1e6, account_type=AccountType.CASH, fee_bps=1.0
    )


def test_a_leaky_variant_does_change_and_is_caught() -> None:
    n, k = 400, 250
    clean, poisoned = bars(n), bars(n, poison_from=k + 1)
    leaky_clean = _leaky_run(clean, [b.close for b in clean])
    leaky_poisoned = _leaky_run(clean, [b.close for b in poisoned])
    history = parse_rule_spec({"name": "x", **CLOSE_ONLY}).history
    assert _decisions_to(leaky_poisoned, k, history) != _decisions_to(leaky_clean, k, history)


def test_inverted_control_accepts_a_rules_spec(tmp_path: Path) -> None:
    from alpha_cli.spine.controls import run_inverted_backtest

    rows = bars(400)
    owner = idea(CLOSE_ONLY)
    spec = assemble_run_spec(owner, "SPY", 252, len(rows))
    original = _runner.run_full_backtest(rows, spec)
    control = run_inverted_backtest(rows, spec, original)
    assert control.decision_trace and control.equity_curve
