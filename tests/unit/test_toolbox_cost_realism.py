"""Known answers for the cost and execution realism checks (family H of the toolbox)."""

import json
import math
import random
import statistics
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox import inputs
from alpha_cli.toolbox.registry import get
from alpha_cli.toolbox.runner import run
from alpha_core import Bar
from tests.unit.test_spine_tools import RUN
from tests.unit.test_toolbox_run_level_checks import END, START, stored_run, write_costs

PREFIX = "cost_realism."
APPROX: dict[str, Any] = {"rel": 1e-9, "abs": 1e-12}
DAY = timedelta(days=1)
STORED = ("cost_sweep", "churn_budget", "financing_cost", "after_tax")
TRADE_TOOLS = (
    *STORED,
    "commission_schedule",
    "share_rounding",
    "market_impact",
    "capacity_curve",
    "volume_share",
    "limit_fill",
)
WINDOWED = ("market_impact", "capacity_curve", "volume_share")
BAR_TOOLS = ("spread_estimates", "gap_stress")


def at(days: int) -> datetime:
    return START + days * DAY


def write_trades(folder: Path, rows: list[dict[str, Any]]) -> None:
    columns = ["side", "quantity", "entry_price", "exit_price", "entry_ts", "exit_ts"]
    columns += ["realized_pnl", "realized_return"]
    frame = {c: [r.get(c) for r in rows] for c in columns}
    schema: dict[str, Any] = {
        c: pl.Float64 for c in ("quantity", "entry_price", "exit_price", "realized_pnl")
    }
    schema |= {"realized_return": pl.Float64, "side": pl.String}
    pl.DataFrame(frame, schema_overrides=schema).write_parquet(folder / "trades.parquet")


def trade(
    entry: int, exit_: int, qty: float, price: float, pnl: float, side: str = "BUY"
) -> dict[str, Any]:
    return {
        "side": side,
        "quantity": qty,
        "entry_price": price,
        "exit_price": price * 1.1,
        "entry_ts": at(entry),
        "exit_ts": at(exit_),
        "realized_pnl": pnl,
        "realized_return": pnl / (qty * price),
    }


def flat_equity(folder: Path, value: float = 1000.0) -> None:
    """A flat curve as the engine stores it: 1.0 at the start, in units of the starting cash."""
    dates = [START + i * DAY for i in range((END - START).days + 1)]
    pl.DataFrame(
        {"ts": dates, "equity": [1.0] * len(dates), "gross_return": [0.0] * len(dates)}
        | {"cost_return": [0.0] * len(dates)}
    ).write_parquet(folder / "equity_curve.parquet")
    path = folder / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["metadata"]["starting_cash"] = value
    path.write_text(json.dumps(manifest))


def make_run(home: Path, rows: list[dict[str, Any]], equity: float = 1000.0) -> Path:
    folder = stored_run(home, "cost_realism")
    flat_equity(folder, equity)
    write_trades(folder, rows)
    return folder


def bars_from(rows: list[tuple[float, float, float, float, float]]) -> tuple[Bar, ...]:
    return tuple(
        Bar(symbol="SPY", ts=at(i), open=o, high=h, low=low, close=c, volume=v)
        for i, (o, h, low, c, v) in enumerate(rows)
    )


def serve_bars(monkeypatch: pytest.MonkeyPatch, home: Path, bars: tuple[Bar, ...]) -> None:
    series = inputs.RunSeries(
        home=home,
        run_id=RUN,
        manifest=json.loads((home / "runs" / RUN / "manifest.json").read_text()),
        asset="SPY@home",
        ppy=365,
        dates=tuple(b.ts for b in bars),
        equity=(1.0,) * len(bars),
        opens={},
        benchmark_equity={},
        bars=bars,
    )
    monkeypatch.setattr(inputs, "load_run", lambda home, target: series)


def values(home: Path, tool: str, *raw: str) -> dict[str, Any]:
    values_: dict[str, Any] = run(home, PREFIX + tool, RUN, list(raw))["values"]
    return values_


def test_cost_sweep(tmp_path: Path) -> None:
    folder = stored_run(tmp_path, "x")
    gross, cost = [0.1, 0.2, 0.1], [0.01, 0.02, 0.01]
    write_costs(folder, gross, cost, 0.0)
    got = values(tmp_path, "cost_sweep")
    for m in (0, 1, 2, 5):
        wealth = math.prod(1 + g - m * c for g, c in zip(gross, cost, strict=True))
        assert got[f"return_x{m}"] == pytest.approx(wealth - 1, **APPROX)
    for m in (1, 2):
        after = [g - m * c for g, c in zip(gross, cost, strict=True)]
        expected = statistics.mean(after) / statistics.stdev(after) * math.sqrt(365)
        assert got[f"sharpe_x{m}"] == pytest.approx(expected, **APPROX)


def test_cost_sweep_ruin_is_total_loss(tmp_path: Path) -> None:
    write_costs(stored_run(tmp_path, "x"), [0.1, 0.1], [0.5, 0.5], 0.0)
    got = values(tmp_path, "cost_sweep")
    assert got["return_x5"] == -1.0 and got["sharpe_x2"] is None


def test_churn_budget(tmp_path: Path) -> None:
    folder = stored_run(tmp_path, "x")
    write_costs(folder, [0.1, 0.1], [0.01, 0.01], 0.0)
    write_trades(folder, [trade(1, 2, 1, 10, 1), trade(1, 2, 1, 10, 1)] * 2)
    got = values(tmp_path, "churn_budget")
    years = 2 / 365.25
    net = 1.09**2 - 1
    assert got["gross_return"] == pytest.approx(0.21, **APPROX)
    assert got["net_return"] == pytest.approx(net, **APPROX)
    assert got["trades_per_year"] == pytest.approx(4 / years, **APPROX)
    drag = (math.log(1.21) - 2 * math.log(1.09)) / years
    assert got["cost_drag_per_year"] == pytest.approx(drag, **APPROX)


def test_financing_cost(tmp_path: Path) -> None:
    make_run(tmp_path, [trade(10, 20, 15, 100, 20), trade(30, 31, 5, 100, -5)])
    got = values(tmp_path, "financing_cost")
    interest = (1500 - 1000) * 0.06 * 10 / 365
    assert got["leveraged_trades"] == 1
    assert got["interest"] == pytest.approx(interest, **APPROX)
    assert got["profit_after_interest"] == pytest.approx(15 - interest, **APPROX)
    higher = values(tmp_path, "financing_cost", "rate_pct=12")
    assert higher["interest"] == pytest.approx(2 * interest, **APPROX)


def test_after_tax(tmp_path: Path) -> None:
    def day(y: int, m: int, d: int) -> datetime:
        return datetime(y, m, d, tzinfo=UTC)

    def row(entry: datetime, exit_: datetime, pnl: float) -> dict[str, Any]:
        return trade(0, 1, 1, 10, pnl) | {"entry_ts": entry, "exit_ts": exit_}

    rows = [
        row(day(2023, 2, 19), day(2023, 3, 1), 100),
        row(day(2022, 4, 27), day(2023, 6, 1), 200),
        row(day(2023, 8, 22), day(2023, 9, 1), -30),
        row(day(2024, 1, 31), day(2024, 2, 10), -50),
        row(day(2024, 2, 20), day(2024, 3, 1), 40),
    ]
    write_trades(stored_run(tmp_path, "x"), rows)
    got = values(tmp_path, "after_tax")
    # 2023: short-term 100 - 30 = 70 at 30%, long-term 200 at 15%. 2024: the -50 is a wash sale.
    tax = 70 * 0.30 + 200 * 0.15 + 40 * 0.30
    assert got["wash_losses"] == 1
    assert got["pre_tax_profit"] == pytest.approx(260, **APPROX)
    assert got["tax"] == pytest.approx(tax, **APPROX)
    assert got["after_tax_profit"] == pytest.approx(260 - tax, **APPROX)


def test_commission_schedule(tmp_path: Path) -> None:
    write_trades(stored_run(tmp_path, "x"), [trade(1, 2, 100, 50, 1), trade(3, 4, 1000, 50, 1)])
    got = values(tmp_path, "commission_schedule")
    # Orders of 100 and 1000 units: 0.5 -> minimum 1.0, and 5.0. Each trade has two orders.
    assert got["commission"] == pytest.approx(12.0, **APPROX)
    traded = 100 * (50 + 55) + 1000 * (50 + 55)
    assert got["commission_bps"] == pytest.approx(12 / traded * 1e4, **APPROX)
    assert got["min_ticket_share"] == pytest.approx(0.5, **APPROX)


def test_share_rounding(tmp_path: Path) -> None:
    rows = [trade(1, 2, 2, 100, 10), trade(3, 4, 0.25, 100, 1), trade(5, 6, 0.05, 100, 0.1)]
    make_run(tmp_path, rows)
    got = values(tmp_path, "share_rounding")
    # Equity 1000, account 10000: targets 2000, 250 and 50 -> 20, 2 and 0 whole shares at 100.
    assert got["trades"] == 3 and got["zero_share_trades"] == 1
    assert got["ideal_profit"] == pytest.approx(0.05 * 2000 + 0.04 * 250 + 0.02 * 50, **APPROX)
    assert got["rounded_profit"] == pytest.approx(0.05 * 2000 + 0.04 * 200, **APPROX)


def walk(n: int, seed: int = 1) -> list[tuple[float, float, float, float, float]]:
    rng, price, rows = random.Random(seed), 100.0, []
    for _ in range(n):
        close = price * (1 + rng.uniform(-0.02, 0.02))
        rows.append((price, max(price, close) * 1.01, min(price, close) * 0.99, close, 1000.0))
        price = close
    return rows


def test_spread_estimates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stored_run(tmp_path, "x")
    rows = walk(60)
    serve_bars(monkeypatch, tmp_path, bars_from(rows))
    got = values(tmp_path, "spread_estimates")
    close = [r[3] for r in rows]
    diff = [b - a for a, b in zip(close, close[1:], strict=False)]
    cov = statistics.covariance(diff[1:], diff[:-1])
    high, low = [r[1] for r in rows], [r[2] for r in rows]
    c = 3 - 2 * math.sqrt(2)
    spreads = []
    for t in range(len(rows) - 1):
        beta = math.log(high[t] / low[t]) ** 2 + math.log(high[t + 1] / low[t + 1]) ** 2
        gamma = math.log(max(high[t], high[t + 1]) / min(low[t], low[t + 1])) ** 2
        alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / c - math.sqrt(gamma / c)
        spreads.append(2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha)))
    mid = [(math.log(h) + math.log(lo)) / 2 for h, lo in zip(high, low, strict=True)]
    prods = [
        4 * (math.log(close[t]) - mid[t]) * (math.log(close[t]) - mid[t + 1])
        for t in range(len(rows) - 1)
    ]
    if cov < 0:
        assert got["roll_bps"] == pytest.approx(2 * math.sqrt(-cov) / statistics.mean(close) * 1e4)
    else:
        assert got["roll_bps"] is None
    assert got["corwin_schultz_bps"] == pytest.approx(statistics.mean(spreads) * 1e4, **APPROX)
    if statistics.mean(prods) > 0:
        assert got["abdi_ranaldo_bps"] == pytest.approx(math.sqrt(statistics.mean(prods)) * 1e4)
    else:
        assert got["abdi_ranaldo_bps"] is None


def test_spread_estimates_roll_known_bounce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored_run(tmp_path, "x")
    # Closes bounce between 99 and 101 around a flat value: serial covariance is negative.
    rows = [(100.0, 101.5, 98.5, 99.0 if i % 2 else 101.0, 1.0) for i in range(40)]
    serve_bars(monkeypatch, tmp_path, bars_from(rows))
    diff = [(-2.0 if i % 2 else 2.0) for i in range(1, 40)]
    cov = statistics.covariance(diff[1:], diff[:-1])
    assert cov < 0
    got = values(tmp_path, "spread_estimates")
    assert got["roll_bps"] == pytest.approx(
        2 * math.sqrt(-cov) / statistics.mean(r[3] for r in rows) * 1e4
    )


def test_gap_stress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stored_run(tmp_path, "x")
    rows = [(100.0, 101.0, 99.0, 100.0, 1.0) for _ in range(31)]
    for i, opened in ((5, 95.0), (12, 90.0), (20, 104.0)):
        rows[i] = (opened, 105.0, 89.0, 100.0, 1.0)
    serve_bars(monkeypatch, tmp_path, bars_from(rows))
    got = values(tmp_path, "gap_stress")
    stop = 100 * (1 - 0.03)
    assert got["down_gap_share"] == pytest.approx(2 / 30, **APPROX)
    assert got["down_extra_loss"] == pytest.approx(((stop - 95) / stop + (stop - 90) / stop) / 2)
    assert got["worst_down_gap"] == pytest.approx(-0.1, **APPROX)
    wide = values(tmp_path, "gap_stress", "stop_pct=20")
    assert wide["down_gap_share"] == 0 and wide["down_extra_loss"] is None


def alternating(n: int = 14) -> list[tuple[float, float, float, float, float]]:
    return [(100.0, 103.0, 99.0, 100.0 if i % 2 == 0 else 102.0, 1000.0) for i in range(n)]


SIGMA = statistics.stdev(
    [math.log(1.02), -math.log(1.02), math.log(1.02), -math.log(1.02)] + [math.log(1.02)]
)
PARAMS = ("window=5",)


def impact_run(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_run(home, [trade(8, 9, 10, 100, 40), trade(9, 10, 40, 100, 60), trade(3, 4, 10, 100, 5)])
    serve_bars(monkeypatch, home, bars_from(alternating()))


def test_market_impact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    impact_run(tmp_path, monkeypatch)
    got = values(tmp_path, "market_impact", *PARAMS)
    # Volume 1000: shares 0.01 and 0.04 of it; the early entry has no five bars before it.
    assert got["measured"] == 2
    assert got["mean_impact_bps"] == pytest.approx(1e4 * SIGMA * 0.15, **APPROX)
    assert got["impact_cost"] == pytest.approx(2 * (1000 * 0.1 + 4000 * 0.2) * SIGMA, **APPROX)
    double = values(tmp_path, "market_impact", *PARAMS, "coefficient=2")
    assert double["impact_cost"] == pytest.approx(2 * got["impact_cost"], **APPROX)


def test_capacity_curve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_run(tmp_path, [trade(8, 9, 10, 100, 40), trade(9, 10, 40, 100, 60)])
    serve_bars(monkeypatch, tmp_path, bars_from(alternating()))
    got = values(tmp_path, "capacity_curve", *PARAMS)
    cost, profit = (1000 * 0.1 + 4000 * 0.2) * SIGMA, 100.0
    for m in (1, 10, 100):
        assert got[f"return_x{m}"] == pytest.approx(
            (m * profit - 2 * m**1.5 * cost) / (m * 1000), **APPROX
        )
    assert got["zero_profit_multiple"] == pytest.approx((profit / (2 * cost)) ** 2, **APPROX)


def test_volume_share(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    impact_run(tmp_path, monkeypatch)
    got = values(tmp_path, "volume_share", *PARAMS, "cap_pct=2")
    assert got["measured"] == 2 and got["over_cap"] == 1
    assert got["max_participation"] == pytest.approx(0.04, **APPROX)


def test_limit_fill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    limit = 100.0 * (1 - 25 / 1e4)
    rows = [(100.0, 101.0, 99.0, 100.0, 1.0) for _ in range(12)]
    rows[3] = (100.0, 101.0, limit - 0.5, 100.0, 1.0)  # passes through the buy limit
    rows[5] = (100.0, 101.0, limit, 100.0, 1.0)  # only touches it
    rows[7] = (100.0, 100.1, 99.9, 100.0, 1.0)  # a short limit above the open is not reached
    make_run(
        tmp_path, [trade(3, 4, 1, 100, 1), trade(5, 6, 1, 100, 1), trade(7, 8, 1, 100, 1, "SELL")]
    )
    serve_bars(monkeypatch, tmp_path, bars_from(rows))
    got = values(tmp_path, "limit_fill")
    assert got["measured"] == 3
    assert got["touch_share"] == pytest.approx(2 / 3, **APPROX)
    assert got["through_share"] == pytest.approx(1 / 3, **APPROX)


@pytest.mark.parametrize("tool", TRADE_TOOLS[1:])
def test_too_little_to_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
    make_run(tmp_path, [])
    serve_bars(monkeypatch, tmp_path, ())
    doc = run(tmp_path, PREFIX + tool, RUN)
    assert doc["reading"] == get(PREFIX + tool).render(doc["values"])
    assert all(v is None and doc["reasons"][k] for k, v in doc["values"].items())


def test_cost_sweep_with_one_bar_has_no_sharpe(tmp_path: Path) -> None:
    write_costs(stored_run(tmp_path, "x"), [0.1], [0.01], 0.0)
    doc = run(tmp_path, PREFIX + "cost_sweep", RUN)
    assert doc["values"]["return_x1"] == pytest.approx(0.09, **APPROX)
    assert doc["values"]["sharpe_x1"] is None and doc["reasons"]["sharpe_x1"]


@pytest.mark.parametrize("tool", ["cost_sweep", "churn_budget"])
def test_run_without_stored_costs(tmp_path: Path, tool: str) -> None:
    stored_run(tmp_path, "x")  # this equity file has no gross and cost columns
    doc = run(tmp_path, PREFIX + tool, RUN)
    assert all(
        v is None and "Run the rule test again" in doc["reasons"][k]
        for k, v in doc["values"].items()
    )


@pytest.mark.parametrize("tool", BAR_TOOLS)
def test_too_few_bars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
    stored_run(tmp_path, "x")
    serve_bars(monkeypatch, tmp_path, bars_from(walk(10)))
    doc = run(tmp_path, PREFIX + tool, RUN)
    assert all(
        v is None and "at least 30 bars" in doc["reasons"][k] for k, v in doc["values"].items()
    )


@pytest.mark.parametrize("tool", [*TRADE_TOOLS, *BAR_TOOLS])
def test_repeat_is_identical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
    results = []
    for name in ("first", "second"):
        home = tmp_path / name
        impact_run(home, monkeypatch)
        if tool in ("cost_sweep", "churn_budget"):
            write_costs(home / "runs" / RUN, [0.1, 0.2, 0.1], [0.01, 0.02, 0.01], 0.0)
        if tool in BAR_TOOLS:
            serve_bars(monkeypatch, home, bars_from(walk(40)))
        doc = run(home, PREFIX + tool, RUN, ["window=5"] if tool in WINDOWED else [])
        results.append(json.dumps(doc["result"], sort_keys=True))
    assert results[0] == results[1]


@pytest.mark.parametrize("tool", ["cost_sweep", "after_tax"])
def test_future_observation_is_rejected(tmp_path: Path, tool: str) -> None:
    folder = stored_run(tmp_path, "x")
    write_costs(folder, [0.1, 0.1], [0.01, 0.01], 0.0)
    frame = pl.read_parquet(folder / "equity_curve.parquet")
    future = frame.tail(1).with_columns(pl.lit(END + DAY).alias("ts"))
    frame.vstack(future).write_parquet(folder / "equity_curve.parquet")
    if tool == "after_tax":
        write_trades(folder, [trade(1, (END - START).days + 1, 1, 10, 1)])
    with pytest.raises(SpineError, match="run period"):
        run(tmp_path, PREFIX + tool, RUN)


def test_registry_lists_every_check() -> None:
    names = {*TRADE_TOOLS, *BAR_TOOLS}
    assert len(names) == 12
    for name in names:
        spec = get(PREFIX + name)
        assert spec.look == "describe" and spec.kind == "diagnostic" and spec.question.endswith("?")
        assert replace(spec) == spec


def test_capacity_curve_refuses_a_partial_profit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    impact_run(tmp_path, monkeypatch)  # the third trade has no volume history
    doc = run(tmp_path, PREFIX + "capacity_curve", RUN, list(PARAMS))
    assert all(v is None and "1 trades lack" in doc["reasons"][k] for k, v in doc["values"].items())
