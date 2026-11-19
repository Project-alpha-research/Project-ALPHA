"""Every reader cuts at one instant, and the crypto scan reads no held-back row into Python."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_cli import _crypto_panel, _hypothesis_scan, _runner
from alpha_cli.spine import reserve
from alpha_core.reserve import RESERVED_DAY, RESERVED_START
from alpha_data.store import ParquetStore
from alpha_data.timeframe import parse_timeframe, store_dir
from tests.fixtures.hypothesis_scan_fixtures import crypto_manifest, crypto_store

FIRST = datetime(RESERVED_DAY.year, RESERVED_DAY.month, RESERVED_DAY.day, tzinfo=UTC)
LAST_SECOND = FIRST - timedelta(milliseconds=500)


def _bars(stamps: list[datetime]) -> pl.DataFrame:
    prices = [100.0 + i for i in range(len(stamps))]
    return pl.DataFrame(
        {
            "ts": stamps,
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1.0] * len(stamps),
        }
    )


def test_the_cutoff_is_the_last_instant_before_the_reserved_instant() -> None:
    assert reserve.RESERVED_INSTANT == FIRST
    assert FIRST - timedelta(microseconds=1) == reserve.CUTOFF
    assert (RESERVED_DAY - timedelta(days=1)).isoformat() == reserve.CUTOFF_DATE


def test_a_daily_bar_in_the_last_second_is_used_and_the_first_reserved_bar_is_held(
    tmp_path: Path,
) -> None:
    store = ParquetStore(tmp_path / "store")
    stamps = [FIRST - timedelta(days=3 - i) for i in range(3)] + [LAST_SECOND, FIRST]
    store.write_bars("AAA", _bars(stamps))
    held = reserve.hold("AAA", data_dir=tmp_path)
    bars, _ = _runner.load_bars("AAA", data_dir=tmp_path, as_of=held.as_of)
    assert held.held_back == 1
    assert max(bar.ts for bar in bars) == LAST_SECOND


def test_an_intraday_store_keeps_the_bar_that_closes_at_the_reserved_instant(
    tmp_path: Path,
) -> None:
    frame = parse_timeframe("5m")
    store = ParquetStore(store_dir(tmp_path, frame))
    step = timedelta(minutes=5)
    stamps = [FIRST - step * (4 - i) for i in range(4)] + [FIRST, FIRST + step]
    store.write_bars("BTC/USDT", _bars(stamps))
    held = reserve.hold("BTC/USDT", data_dir=tmp_path, timeframe="5m", instant=True)
    bars, _ = _runner.load_bars(
        "BTC/USDT", data_dir=tmp_path, as_of=held.as_of, timeframe="5m", source_timeframe="5m"
    )
    # A crypto pair trades all day. Every stored bar is used (it closed by the reserved
    # instant) or held back; none is lost between the two.
    assert held.as_of == reserve.RESERVED_INSTANT and held.held_back == 2
    assert [bar.ts for bar in bars] == stamps[:4]


def _crypto_home(root: Path) -> None:
    store = crypto_store(root)
    start = FIRST - timedelta(days=60)
    for column, symbol in enumerate(("AAAUSDT", "BBBUSDT", "CCCUSDT")):
        for family, (frequency, units, convention, name) in _crypto_panel.FAMILIES.items():
            step = {"1d": timedelta(days=1), "1h": timedelta(hours=1)}.get(
                frequency, timedelta(hours=8)
            )
            count = int(timedelta(days=90) / step)
            stamps = [start + step * i for i in range(count)]
            values = [
                (1.0 + 0.01 * column + 0.001 * (i % (column + 3))) * (1000.0 if s >= FIRST else 1)
                for i, s in enumerate(stamps)
            ]
            dataset = {
                "schema_version": 1,
                "provider": "bybit",
                "venue": "bybit",
                "market_type": "linear",
                "family": family,
                "instrument": symbol,
                "base_asset": symbol[:-4],
                "quote_asset": "USDT",
                "frequency": frequency,
                "units": units,
                "timestamp_convention": convention,
            }
            rows = {
                "timestamp": stamps,
                "symbol": [symbol] * count,
                "category": ["linear"] * count,
                name: values,
            }
            crypto_manifest(store, dataset, pl.DataFrame(rows))


def test_the_crypto_panel_read_returns_no_row_from_the_reserved_period(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _crypto_home(tmp_path)
    store = crypto_store(tmp_path)
    monkeypatch.setattr(_crypto_panel, "bulk_store", lambda _: store)
    request: dict[str, Any] = {
        "lane": "crypto",
        "symbols": ["AAAUSDT", "BBBUSDT", "CCCUSDT"],
        "universe": None,
        "snapshot": None,
        "signals": ["mom_30d", "funding_z_30d", "oi_chg_7d"],
        "cost_bps": 10.0,
        "category": "linear",
        "as_of": (RESERVED_DAY + timedelta(days=20)).isoformat(),
        "horizons": [1],
        "min_names": 3,
        "quantiles": 3,
    }
    spec = _hypothesis_scan.freeze_spec(tmp_path, request)
    reached: list[datetime] = []
    real = _crypto_panel.read_before_reserved

    def read(path: Path) -> tuple[int, pl.DataFrame]:
        height, frame = real(path)
        reached.extend(frame["timestamp"].to_list())
        return height, frame

    monkeypatch.setattr(_crypto_panel, "read_before_reserved", read)
    days, _, _ = _crypto_panel.crypto_panel(tmp_path, spec)
    assert reached and max(reached) < FIRST
    assert max(days) == RESERVED_DAY  # the last 2023 bar, known when it closes at midnight
    assert spec["reserve"]["held_back_rows"] > 0 and "held_back_bars" not in spec["reserve"]
    sentence = reserve.describe(spec["reserve"])
    assert "rows" in sentence and " bars from" not in sentence


def test_the_standard_sentence_still_counts_bars() -> None:
    assert reserve.describe(reserve.record(3)) == reserve.sentence(3)
    assert reserve.sentence(3).startswith("Held back 3 bars from")
    assert reserve.record(3) == {"reserved_start": RESERVED_START, "held_back_bars": 3}


def test_a_user_cutoff_before_the_reserved_day_is_kept(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path / "store")
    store.write_bars("AAA", _bars([FIRST - timedelta(days=2), FIRST]))
    early = (FIRST - timedelta(days=1)).date().isoformat()
    held = reserve.hold("AAA", data_dir=tmp_path, as_of=early)
    assert (held.held_back, held.research_cutoff) == (0, early)
    assert held.as_of is not None and held.as_of.date() == date.fromisoformat(early)
