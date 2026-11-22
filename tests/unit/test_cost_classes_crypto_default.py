"""A spec without costs on a crypto asset takes the crypto class default (M112)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from alpha_cli import _gauntlet
from alpha_cli.spine import cost_classes as cc
from alpha_cli.spine.run import prepare_bars
from alpha_cli.spine.spec import IdeaSpec
from alpha_cli.spine.stores import resolve_asset
from alpha_core import Bar
from tests.unit.test_cost_classes import _asset


def _bars(symbol: str) -> list[Bar]:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    return [
        Bar(
            symbol=symbol,
            ts=start + timedelta(days=i),
            open=100.0 + i * 0.01,
            high=101.0 + i * 0.01,
            low=99.0 + i * 0.01,
            close=100.5 + i * 0.01,
            volume=1000.0,
        )
        for i in range(400)
    ]


@pytest.mark.parametrize(
    ("source", "dataset"),
    [("binance", {"asset_class": "crypto", "venue": "BINANCE"}), ("ccxt:binance", None)],
)
def test_crypto_without_costs_takes_the_crypto_default(
    tmp_path: Path, source: str, dataset: dict[str, str] | None
) -> None:
    _asset(tmp_path, "BTC/USDT", source, dataset)
    idea = IdeaSpec.model_validate(
        {"assets": ["BTC/USDT"], "rule": {"kind": "tsmom", "lookback": "20", "skip": "1"}}
    )
    result: dict[str, Any] = {
        "labels": [],
        "data_health": {"series": [{"asset": "BTC/USDT"}], "override_reason": None},
    }
    prepared = prepare_bars(
        idea,
        resolve_asset("BTC/USDT", data_dir=tmp_path),
        (_bars("BTC/USDT"), [], None),
        tmp_path,
        _gauntlet.GauntletParams(seed=1),
        result,
        {},
    )
    assert prepared.spec.fee_bps == pytest.approx(
        cc.ROWS["crypto_spot"].fee_bps, rel=1e-9, abs=1e-12
    )
    assert prepared.spec.slippage_bps == pytest.approx(
        cc.ROWS["crypto_spot"].slippage_bps, rel=1e-9, abs=1e-12
    )
    assert "crypto spot" in result["costs"]["line"]


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [("BTC-USD", "crypto_spot"), ("ETH-USDT", "crypto_spot"), ("AAPL", None)],
)
def test_class_costs_know_a_yfinance_crypto_ticker_by_its_symbol(
    tmp_path: Path, symbol: str, expected: str | None
) -> None:
    _asset(tmp_path, symbol, "yfinance", None)
    resolved = resolve_asset(symbol, data_dir=tmp_path)
    assert cc.asset_class(resolved, by_symbol=True) == expected
    assert cc.asset_class(resolved) is None
