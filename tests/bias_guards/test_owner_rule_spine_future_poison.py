"""An owner rule run through `alpha test` (the spine) cannot see a bar after its decision bar.

The subject is the real spine path: an idea spec with `[rule] kind = "owner"`, the stored bars of a
synthetic home, `run_idea` (store read, reserve cut, run spec, gauntlet, published run folder). The
harness compares the published run files of a clean home and a poisoned home row by row:

1. Poisoning every bar after bar K (prices and volume to absurd values) changes no decision,
   order, fill, trade, equity or indicator row stamped at or before the close of K.
2. A decision on the close of bar t fills at the open of bar t + 1, never at t.
3. A leaky control (a data path that shows each bar the next bar's prices, built here) changes rows
   at or before K under the same harness: the guard can fail.
4. The Tier-1 speed path (`alpha_strategies.rule_paths`, through the surrogate) gives the same
   positions as the bar-by-bar engine on the unpoisoned prefix, and poison after K does not move it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from alpha_cli import _runner
from alpha_cli._strategies import surrogate_for
from alpha_cli.spine.run import assemble_run_spec, run_idea
from alpha_cli.spine.spec import IdeaSpec
from alpha_core import Bar
from alpha_data.store import ParquetStore
from alpha_strategies.rule_paths import path_signals
from alpha_strategies.rules import parse_rule_spec, rule_signal

pytestmark = pytest.mark.bias_guard

N = 320
K = 250  # the last bar whose close may be read; every bar after it is poisoned
START = datetime(2020, 1, 1, tzinfo=UTC)
# Absurd level (x1000) with a zig-zag on top. Larger swings compound the equity of an all-in
# rule past the engine money limit (about 1.7e11) and abort the process, so no larger poison.
FACTORS = (1_050.0, 950.0)
POISON_VOLUME = 1e9  # absurd; far larger values abort the engine (Rust quantity limits)
RULE: dict[str, Any] = {
    "history": 40,
    "long_when": [
        {"left": {"indicator": "rsi", "params": [14]}, "op": "<", "right": {"value": 60}},
        {"left": {"source": "close"}, "op": ">", "right": {"indicator": "sma", "params": [20]}},
    ],
}
IDEA = IdeaSpec.model_validate(
    {
        "name": "owner-poison-guard",
        "assets": ["SPY"],
        "rule": {"kind": "owner", "spec": RULE},
        "costs": {"fee_bps": 1.0, "slippage_bps": 0.0},  # a fill price is then the open itself
    }
)
# Published files and the column that stamps each row in time.
STAMPED: dict[str, str] = {
    "decision_trace.parquet": "ts",
    "orders.parquet": "ts",
    "fills.parquet": "ts",
    "execution_trace.parquet": "ts",
    "equity_curve.parquet": "ts",
    "indicator_series.parquet": "ts",
    "benchmark_comparison.parquet": "ts",
    "tradable_comparison.parquet": "ts",
    "rolling_metrics.parquet": "ts",
    "exposure_turnover.parquet": "end_ts",
    "trades.parquet": "exit_ts",
}


def _bars(poison_after: int | None = None) -> list[Bar]:
    """A noisy walk with distinct open, high, low and close, on the cent grid. Every bar with an
    index above ``poison_after`` has its prices scaled by an absurd factor and absurd volume."""
    rng = np.random.default_rng(11)
    close = 100.0 * np.cumprod(1.0 + 0.0005 + rng.normal(0.0, 0.012, N))
    gap = rng.normal(0.0, 0.004, N)
    wick = np.abs(rng.normal(0.0, 0.004, (2, N)))
    out: list[Bar] = []
    for i in range(N):
        open_ = (close[i - 1] if i else close[0]) * (1.0 + gap[i])
        high = max(open_, close[i]) * (1.0 + wick[0, i])
        low = min(open_, close[i]) * (1.0 - wick[1, i])
        poisoned = poison_after is not None and i > poison_after
        scale = FACTORS[i % 2] if poisoned else 1.0
        out.append(
            Bar(
                symbol="SPY",
                ts=START + timedelta(days=i),
                open=round(open_ * scale, 2),
                high=round(high * scale, 2),
                low=round(low * scale, 2),
                close=round(float(close[i]) * scale, 2),
                volume=POISON_VOLUME if poisoned else 1_000.0,
            )
        )
    return out


def _home(root: Path, rows: Sequence[Bar]) -> Path:
    home = root / "home"
    frame = pl.DataFrame(
        {
            "ts": [bar.ts for bar in rows],
            "open": [bar.open for bar in rows],
            "high": [bar.high for bar in rows],
            "low": [bar.low for bar in rows],
            "close": [bar.close for bar in rows],
            "volume": [bar.volume for bar in rows],
        }
    )
    store = ParquetStore(home / "store")
    store.write_bars("SPY", frame)
    store.write_provenance("SPY", source="alpaca", adapter_version="1", parser_version="1")
    return home


def _decided(index: int) -> datetime:
    """The engine reads bar ``index`` at its session close (``ts + 23 h``)."""
    return START + timedelta(days=index, hours=23)


@dataclass(frozen=True)
class Run:
    folder: Path
    files: dict[str, pl.DataFrame]


def _run(root: Path, rows: Sequence[Bar]) -> Run:
    result = run_idea(IDEA, home=_home(root, rows), quick=True, no_diagnose=True)["results"][0]
    assert result["error"] is None, result["error"]
    folder = Path(result["run_dir"])
    return Run(folder, {name: pl.read_parquet(folder / name) for name in STAMPED})


def _upto(run: Run, stamp: datetime) -> dict[str, pl.DataFrame]:
    return {name: frame.filter(pl.col(STAMPED[name]) <= stamp) for name, frame in run.files.items()}


def _after(run: Run, stamp: datetime) -> dict[str, pl.DataFrame]:
    return {name: frame.filter(pl.col(STAMPED[name]) > stamp) for name, frame in run.files.items()}


def _changed(a: dict[str, pl.DataFrame], b: dict[str, pl.DataFrame]) -> list[str]:
    """The harness: names of the files whose rows differ (shape, order or any value)."""
    return [name for name in STAMPED if not a[name].equals(b[name])]


def _peek_one_bar_ahead(rows: Sequence[Bar]) -> list[Bar]:
    """The leaky control: each bar carries the next bar's prices (the last keeps its own)."""
    return [
        bar.model_copy(
            update={
                key: getattr(rows[min(i + 1, len(rows) - 1)], key)
                for key in ("open", "high", "low", "close", "volume")
            }
        )
        for i, bar in enumerate(rows)
    ]


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Run]:
    return {
        "clean": _run(tmp_path_factory.mktemp("clean"), _bars()),
        "poisoned": _run(tmp_path_factory.mktemp("poisoned"), _bars(poison_after=K)),
    }


@pytest.fixture(scope="module")
def leaky_runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Run]:
    original = _runner.load_bars

    def leaky_load(symbol: str, **kwargs: Any) -> tuple[list[Bar], str | None]:
        rows, snapshot = original(symbol, **kwargs)
        return _peek_one_bar_ahead(rows), snapshot

    # The leak is undone as soon as both runs exist: a module-scoped fixture that stays patched
    # would make `runs` leaky too whenever a worker builds `leaky_runs` first (pytest-xdist).
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(_runner, "load_bars", leaky_load)
        return {
            "clean": _run(tmp_path_factory.mktemp("leaky-clean"), _bars()),
            "poisoned": _run(tmp_path_factory.mktemp("leaky-poisoned"), _bars(poison_after=K)),
        }


def test_poison_after_bar_k_changes_nothing_stamped_up_to_its_close(runs: dict[str, Run]) -> None:
    clean, poisoned = runs["clean"], runs["poisoned"]
    stamp = _decided(K)
    before = _upto(clean, stamp)
    assert _changed(before, _upto(poisoned, stamp)) == []
    # The guard looks at real rows: K is inside the scored period, both states and fills occur.
    decisions = before["decision_trace.parquet"]
    assert decisions.height > 100 and set(decisions["signal"].to_list()) == {0, 1}
    assert before["fills.parquet"].height > 4 and before["trades.parquet"].height > 2
    # The poison is potent: rows after the close of K do move.
    moved = _changed(_after(clean, stamp), _after(poisoned, stamp))
    assert {"decision_trace.parquet", "fills.parquet", "equity_curve.parquet"} <= set(moved)


def test_a_decision_on_the_close_of_t_fills_at_the_open_of_t_plus_1(runs: dict[str, Run]) -> None:
    rows = _bars()
    opens = {bar.ts: bar.open for bar in rows}
    closes = {bar.ts: bar.close for bar in rows}
    run = runs["clean"]
    orders = run.files["orders.parquet"]
    decisions = run.files["decision_trace.parquet"].select(
        pl.col("sequence_id").alias("decision_sequence_id"), pl.col("ts").alias("decided")
    )
    fills = run.files["fills.parquet"].join(
        orders.select(pl.col("sequence_id").alias("order_sequence_id"), "decision_sequence_id"),
        on="order_sequence_id",
    )
    fills = fills.join(decisions, on="decision_sequence_id")
    assert fills.height == run.files["fills.parquet"].height > 4
    for row in fills.iter_rows(named=True):
        decided: datetime = row["decided"]
        filled: datetime = row["ts"]
        bar_t = decided - timedelta(hours=23)
        assert decided.hour == 23 and bar_t in opens  # read at the close of bar t
        assert filled == bar_t + timedelta(days=1)  # filled at the open of bar t + 1
        assert filled > decided
        assert row["price"] == pytest.approx(opens[filled], rel=1e-9, abs=1e-12)
        # The open differs from the decision close, so a same-bar fill could not pass the check.
        assert opens[filled] != closes[bar_t]


def test_the_same_harness_catches_a_data_path_that_peeks_one_bar_ahead(
    leaky_runs: dict[str, Run],
) -> None:
    stamp = _decided(K)
    changed = _changed(_upto(leaky_runs["clean"], stamp), _upto(leaky_runs["poisoned"], stamp))
    assert "indicator_series.parquet" in changed
    assert "decision_trace.parquet" in changed or "equity_curve.parquet" in changed


def test_the_tier1_speed_path_gives_the_engine_positions_and_ignores_the_poison(
    runs: dict[str, Run],
) -> None:
    rows = _bars()
    spec = assemble_run_spec(IDEA, "SPY", 252, N)
    rules = parse_rule_spec({"name": "owner-rule", **RULE})
    closes = np.asarray([bar.close for bar in rows], dtype=np.float64)
    poisoned = np.asarray([bar.close for bar in _bars(poison_after=K)], dtype=np.float64)

    # The engine's position decided on each bar's close, as the spine run published it.
    engine = {
        int((ts - START) / timedelta(days=1)): signal
        for ts, signal in runs["clean"]
        .files["decision_trace.parquet"]
        .select("ts", "signal")
        .iter_rows()
    }
    prefix = [i for i in sorted(engine) if i <= K]
    assert len(prefix) > 100

    # The speed path itself, closes only (the rule reads no high or low).
    fast = path_signals(rules, closes, closes, closes)
    fast_poisoned = path_signals(rules, poisoned, poisoned, poisoned)
    assert [fast[i] for i in prefix] == [engine[i] for i in prefix]
    assert fast_poisoned[: K + 1] == fast[: K + 1]
    assert fast_poisoned[K + 1 :] != fast[K + 1 :]  # the poison is potent here too
    # The bar-by-bar definition on the same prefix.
    slow = [rule_signal(rules, closes[: i + 1], closes[: i + 1], closes[: i + 1]) for i in prefix]
    assert slow == [engine[i] for i in prefix]

    # The surrogate the Tier-1 null runs: weights[t] is the position decided on the close of t.
    returns = closes[1:] / closes[:-1] - 1.0
    returns_poisoned = poisoned[1:] / poisoned[:-1] - 1.0
    weights, _ = surrogate_for(spec).weights_and_costs(returns)
    weights_poisoned, _ = surrogate_for(spec).weights_and_costs(returns_poisoned)
    assert [float(weights[i]) for i in prefix] == [float(engine[i]) for i in prefix]
    assert np.array_equal(weights_poisoned[: K + 1], weights[: K + 1])
