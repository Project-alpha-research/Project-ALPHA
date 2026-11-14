"""Intraday next-open execution and immutable CLI runs through the real engine."""

import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import _runner
from alpha_cli._identity import RunIdentity
from alpha_cli.main import app
from alpha_cli.spine.stores import periods_per_year
from alpha_core import Bar
from alpha_data.store import ParquetStore
from alpha_data.timeframe import parse_timeframe


def _bars(symbol: str = "X", timeframe: str = "5m", sessions: int = 2) -> list[Bar]:
    period = parse_timeframe(timeframe)
    if "/" in symbol:
        stamps = [datetime(2024, 1, 2, tzinfo=UTC) + i * period.duration for i in range(156)]
    else:
        stamps = [
            datetime(2024, 1, 2 + day, 14, 30, tzinfo=UTC) + i * period.duration
            for day in range(sessions)
            for i in range(78)
        ]
    return [
        Bar(
            symbol=symbol,
            ts=stamp,
            open=100 + i * 0.03 + math.sin(i / 5),
            high=104 + i * 0.03,
            low=96 + i * 0.03,
            close=100.4 + i * 0.03 + math.sin(i / 5),
            volume=10000.0,
        )
        for i, stamp in enumerate(stamps)
    ]


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bars: list[Bar], timeframe: str) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    root = tmp_path / ("store" if timeframe == "1D" else f"store-{timeframe}")
    ParquetStore(root).write_bars(
        bars[0].symbol, pl.DataFrame([bar.model_dump(exclude={"symbol"}) for bar in bars])
    )


def _command(*extra: str) -> list[str]:
    return ["backtest", "run", "X", "--strategy", "ma_crossover", *extra]


def _manifest(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    paths = list((tmp_path / "runs").glob("*/manifest.json"))
    assert len(paths) == 1
    return paths[0].parent, json.loads(paths[0].read_text())


@pytest.mark.parametrize(
    ("symbol", "timeframe", "account"),
    [
        ("X", "5m", "CASH"),
        ("BTC/USDT", "1h", "MARGIN"),
    ],
)
def test_real_engine_every_fill_is_next_open(symbol: str, timeframe: str, account: str) -> None:
    bars = _bars(symbol, timeframe)
    spec = _runner.RunSpec(
        lookback=252,
        skip=21,
        vol_window=5,
        target_vol=0.15,
        rebalance_every=1,
        max_leverage=1.0,
        allow_short=False,
        periods_per_year=periods_per_year([b.ts for b in bars]),
        fee_bps=0.0,
        slippage_bps=0.0,
        starting_cash=1_000_000.0,
        account_type=account,
        train_size=504,
        test_size=63,
        embargo=5,
        anchored=False,
        strategy_name="ma_crossover",
        strategy_params=(("fast", 2.0), ("slow", 5.0)),
    )
    period = parse_timeframe(timeframe)
    result = _runner.run_full_backtest(bars, spec, timeframe=period)
    assert result.fills > 5
    signals = {row.ts for row in result.decision_trace}
    following = {bar.ts + timedelta(microseconds=1): i for i, bar in enumerate(bars)}
    for fill in result.fill_trace:
        i = following[fill.ts]
        assert i > 0
        assert bars[i - 1].ts + period.duration in signals
        assert fill.price == pytest.approx(
            bars[i].open, abs=0.005 if account == "CASH" else 0.000005
        )
        if account == "CASH":
            assert fill.ts.weekday() < 5
            assert (14, 30) <= (fill.ts.hour, fill.ts.minute) < (21, 0)
    if account == "CASH":
        assert {fill.ts.date() for fill in result.fill_trace} == {bar.ts.date() for bar in bars}


def test_cli_intraday_determinism_and_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bars = _bars()
    _seed(tmp_path, monkeypatch, bars, "5m")
    cli = CliRunner()
    args = _command("--timeframe", "5m")
    first = cli.invoke(app, args)
    assert first.exit_code == 0, first.output
    assert "5m" in first.output
    rdir, manifest = _manifest(tmp_path)
    assert {
        key: manifest[key] for key in ("timeframe", "source_timeframe", "session", "manifest_id")
    } == {
        "timeframe": "5m",
        "source_timeframe": "5m",
        "session": "regular",
        "manifest_id": None,
    }
    # 5m regular session: 78 bars a session, 252 sessions (from the bar size, not the sample)
    assert manifest["params"]["periods_per_year"] == 252 * 78
    equity = (rdir / "equity_curve.parquet").read_bytes()
    second = cli.invoke(app, args)
    assert second.exit_code == 0, second.output
    assert second.output == first.output
    assert _manifest(tmp_path)[1] == manifest
    assert (rdir / "equity_curve.parquet").read_bytes() == equity
    report = cli.invoke(app, ["report", manifest["run_id"]])
    assert report.exit_code == 0, report.output


def test_cli_resamples_stock_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bars = _bars(sessions=4)
    _seed(tmp_path, monkeypatch, bars, "5m")
    result = CliRunner().invoke(
        app,
        _command(
            "--from-timeframe",
            "5m",
            "--timeframe",
            "1h",
            "--periods-per-year",
            "1700",
        ),
    )
    assert result.exit_code == 0, result.output
    rdir, manifest = _manifest(tmp_path)
    assert manifest["timeframe"] == "1h"
    assert manifest["source_timeframe"] == "5m"
    assert manifest["params"]["periods_per_year"] == 1700
    assert pl.read_parquet(rdir / "equity_curve.parquet").height == 28


def test_daily_identity_inputs_and_manifest_keys_are_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bars = [
        bar.model_copy(update={"ts": datetime(2024, 1, 2, tzinfo=UTC) + timedelta(days=i)})
        for i, bar in enumerate(_bars())
    ]
    _seed(tmp_path, monkeypatch, bars, "1D")
    captured: list[Mapping[str, object]] = []
    original = _runner.run_identity_for

    def capture(
        payload: Mapping[str, object],
        *,
        source_fingerprint: str | None = None,
        snapshot_hash: str | None = None,
    ) -> RunIdentity:
        captured.append(payload)
        return original(payload, source_fingerprint=source_fingerprint, snapshot_hash=snapshot_hash)

    monkeypatch.setattr(_runner, "run_identity_for", capture)
    result = CliRunner().invoke(app, _command())
    assert result.exit_code == 0, result.output
    assert captured == [
        {
            "command": "backtest_run",
            "symbol": "X",
            "snapshot_id": None,
            "research_cutoff": None,
            "lookback": 252,
            "skip": 21,
            "vol_window": 63,
            "target_vol": 0.15,
            "rebalance_every": 21,
            "max_leverage": 1.0,
            "allow_short": False,
            "periods_per_year": 252,
            "fee_bps": 1.0,
            "slippage_bps": 2.0,
            "starting_cash": 1_000_000.0,
            "account_type": "CASH",
            "train_size": 504,
            "test_size": 63,
            "embargo": 5,
            "anchored": False,
            "strategy_name": "ma_crossover",
            "strategy_params": (),
            "size_on_equity": False,
            "halt_drawdown": None,
            "forecast_cache": None,
            "rules_spec": None,
            "sizing": "vol_target",
        }
    ]
    _, manifest = _manifest(tmp_path)
    assert set(manifest) == {
        "schema_version",
        "run_id",
        "command",
        "symbol",
        "snapshot_id",
        "research_cutoff",
        "params",
        "orders",
        "fills",
        "rejected",
        "pretrade_rejections",
        "n_trades",
        "starting_equity",
        "final_equity",
        "run_identity_version",
        "execution_fingerprint",
        "strategy_fingerprint",
        "source_fingerprint",
        "snapshot_hash",
        "artifact_contract_version",
        "artifacts",
    }


def test_intraday_annualisation_needs_no_minimum_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bars per year come from the bar size and session, so a short sample runs and is not inflated."""
    _seed(tmp_path, monkeypatch, _bars()[:20], "5m")
    cli = CliRunner()
    short = cli.invoke(app, _command("--timeframe", "5m"))
    assert short.exit_code == 0, short.output
    explicit = cli.invoke(app, _command("--timeframe", "5m", "--periods-per-year", "20000"))
    assert explicit.exit_code == 0, explicit.output


def test_cli_as_of_instant_waits_for_bar_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bars = _bars()
    _seed(tmp_path, monkeypatch, bars, "5m")
    cutoff = bars[40].ts + timedelta(minutes=2)
    result = CliRunner().invoke(app, _command("--timeframe", "5m", "--as-of", cutoff.isoformat()))
    assert result.exit_code == 0, result.output
    rdir, manifest = _manifest(tmp_path)
    assert pl.read_parquet(rdir / "equity_curve.parquet").height == 40
    assert manifest["research_cutoff"] == cutoff.isoformat()


def test_intraday_snapshot_hash_uses_stored_timeframe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, str]] = []

    def snapshot_hash(path: Path, *, timeframe: str = "1D") -> str:
        calls.append({"timeframe": timeframe})
        return "hash"

    monkeypatch.setattr(_runner, "snapshot_manifest_hash", snapshot_hash)
    assert _runner.verified_snapshot_hash(tmp_path, "snapshot", timeframe="5m") == "hash"
    assert calls == [{"timeframe": "5m"}]


@pytest.mark.parametrize(("symbol", "timeframe"), [("X", "5m"), ("BTC/USDT", "1h")])
def test_each_close_signal_fills_at_immediately_following_open(symbol: str, timeframe: str) -> None:
    from nautilus_trader.model.data import Bar as NautilusBar
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.enums import AccountType, OrderSide
    from nautilus_trader.model.events import OrderFilled
    from nautilus_trader.model.objects import Quantity
    from nautilus_trader.trading.strategy import Strategy

    from alpha_backtest.engine import run_backtest
    from alpha_backtest.feed import bar_type_for, to_execution_feed
    from alpha_backtest.instruments import instrument_for

    period = parse_timeframe(timeframe)
    bars = _bars(symbol, timeframe)
    instrument = instrument_for(symbol)
    bar_type = bar_type_for(symbol, period)

    class EveryClose(Strategy):  # type: ignore[misc]  # Cython base is untyped
        def __init__(self) -> None:
            super().__init__()
            self.pending: int | None = None
            self.origin: int | None = None
            self.observed: list[tuple[int | None, int, float]] = []

        def on_start(self) -> None:
            self.subscribe_bars(bar_type)
            self.subscribe_quote_ticks(instrument.id)

        def on_bar(self, bar: NautilusBar) -> None:
            assert self.pending is None
            self.pending = bar.ts_event

        def on_quote_tick(self, quote: QuoteTick) -> None:
            if self.pending is not None:
                self.origin = self.pending
                self.pending = None
                self.submit_order(
                    self.order_factory.market(
                        instrument_id=instrument.id,
                        order_side=OrderSide.BUY,
                        quantity=Quantity(1, instrument.size_precision),
                    )
                )

        def on_order_filled(self, event: OrderFilled) -> None:
            self.observed.append((self.origin, event.ts_event, float(event.last_px)))

    strategy = EveryClose()
    result = run_backtest(
        instrument,
        to_execution_feed(
            bars,
            bar_type,
            timeframe=period,
            price_precision=instrument.price_precision,
            size_precision=instrument.size_precision,
        ),
        strategy,
        account_type=AccountType.MARGIN if "/" in symbol else AccountType.CASH,
        starting_cash=1_000_000.0,
        fee_bps=0.0,
    )
    assert result.fills == len(bars) - 1
    assert len(strategy.observed) == len(bars) - 1
    for index, (origin, stamp, price) in enumerate(strategy.observed):
        assert origin == int((bars[index].ts + period.duration).timestamp() * 1_000_000_000)
        assert stamp == int(bars[index + 1].ts.timestamp() * 1_000_000_000) + 1000
        assert price == pytest.approx(
            bars[index + 1].open,
            rel=0,
            abs=0.5 * 10**-instrument.price_precision,
        )
