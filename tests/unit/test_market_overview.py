"""``alpha data market-overview``: a read-only display of stored bars on a synthetic store."""

from __future__ import annotations

import json
import statistics
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import market_overview_cmds
from alpha_cli.main import app
from alpha_core import DataError
from alpha_data.store import ParquetStore

runner = CliRunner()
START = date(2020, 1, 1)


def _write(
    root: Path, symbol: str, n: int, close_at: float, step: float, volume: float, last_volume: float
) -> list[float]:
    closes = [close_at + step * i for i in range(n)]
    volumes = [volume] * (n - 1) + [last_volume]
    frame = pl.DataFrame(
        {
            "ts": [
                datetime(START.year, START.month, START.day, tzinfo=UTC) + timedelta(days=i)
                for i in range(n)
            ],
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": volumes,
        }
    )
    ParquetStore(root / "store").write_bars(symbol, frame)
    return closes


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    _write(tmp_path, "AAA", 120, 100.0, 1.0, 1000.0, 5000.0)  # high value, volume spike
    _write(tmp_path, "BBB", 120, 50.0, 0.0, 1000.0, 1000.0)  # flat price, mid value
    _write(tmp_path, "CCC", 120, 10.0, 0.0, 1000.0, 1000.0)  # same volume as BBB, lower value
    _write(tmp_path, "DDD", 10, 10.0, 1.0, 1000.0, 1000.0)  # too few bars
    _write(tmp_path, "EEE", 120, 1000.0, 0.0, 1.0, 1.0)  # big price, tiny volume
    return tmp_path


def test_assets_rank_by_median_traded_value_not_by_price_or_volume(data_dir: Path) -> None:
    result = market_overview_cmds.build_market_overview(data_dir, store="1D", window=30, limit=3)
    assert [row["asset"] for row in result["assets"]] == ["AAA", "BBB", "CCC"]
    values = [row["median_traded_value"] for row in result["assets"]]
    assert values == sorted(values, reverse=True)
    assert result["eligible_assets"] == 4
    assert result["limit"] == 3 and result["window"] == 30


def test_series_is_normalised_to_100_at_the_window_start(data_dir: Path) -> None:
    closes = [100.0 + i for i in range(120)]
    result = market_overview_cmds.build_market_overview(data_dir, store="1D", window=30, limit=15)
    row = result["assets"][0]
    assert row["asset"] == "AAA"
    assert row["series"][0] == pytest.approx(100.0)
    assert row["series"][-1] == pytest.approx(100.0 * closes[-1] / closes[-30])
    assert len(row["series"]) == len(row["series_ts"]) == 30
    assert row["change_window_pct"] == pytest.approx((closes[-1] / closes[-30] - 1) * 100)
    assert row["change_1_pct"] == pytest.approx((closes[-1] / closes[-2] - 1) * 100)
    assert row["change_7_pct"] == pytest.approx((closes[-1] / closes[-8] - 1) * 100)
    assert row["last_close"] == closes[-1]


def test_long_window_series_is_down_sampled_and_keeps_both_ends(data_dir: Path) -> None:
    closes = [100.0 + i for i in range(120)]
    result = market_overview_cmds.build_market_overview(data_dir, store="1D", window=90, limit=15)
    row = result["assets"][0]
    assert len(row["series"]) == market_overview_cmds.MAX_SERIES_POINTS < 90
    assert row["series"][0] == pytest.approx(100.0)
    assert row["series"][-1] == pytest.approx(100.0 * closes[-1] / closes[-90])
    assert row["series_ts"] == sorted(row["series_ts"])


def test_volume_is_compared_with_the_median_of_the_twenty_bars_before(data_dir: Path) -> None:
    result = market_overview_cmds.build_market_overview(data_dir, store="1D", window=30, limit=15)
    by_name = {row["asset"]: row for row in result["assets"]}
    assert by_name["AAA"]["last_volume"] == 5000.0
    assert by_name["AAA"]["volume_vs_median"] == pytest.approx(5.0)
    assert by_name["BBB"]["volume_vs_median"] == pytest.approx(1.0)
    closes = [100.0 + i for i in range(120)]
    traded = [c * (5000.0 if i == 119 else 1000.0) for i, c in enumerate(closes)][-30:]
    assert by_name["AAA"]["median_traded_value"] == pytest.approx(statistics.median(traded))


def test_dates_and_bar_counts_are_reported(data_dir: Path) -> None:
    result = market_overview_cmds.build_market_overview(data_dir, store="1D", window=30, limit=15)
    last = (datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=119)).isoformat()
    assert result["data_to"] == last
    assert result["assets"][0]["last_bar"] == last
    assert result["assets"][0]["bar_count"] == 120
    assert result["bar_unit"] == "day"
    assert result["available_stores"] == ["1D"]


def test_an_asset_with_too_few_bars_is_listed_not_dropped(data_dir: Path) -> None:
    result = market_overview_cmds.build_market_overview(data_dir, store="1D", window=30, limit=15)
    assert "DDD" not in {row["asset"] for row in result["assets"]}
    assert result["too_few_bars"] == [{"asset": "DDD", "bar_count": 10, "needed": 30}]


def test_an_unreadable_file_is_listed_not_dropped(data_dir: Path) -> None:
    bad = data_dir / "store" / "bars" / "ZZZ.parquet"
    bad.write_bytes(b"not parquet")
    result = market_overview_cmds.build_market_overview(data_dir, store="1D", window=30, limit=15)
    assert [row["asset"] for row in result["unreadable"]] == ["ZZZ"]
    assert "ZZZ" not in {row["asset"] for row in result["assets"]}


def test_the_scan_is_capped_and_says_so(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(market_overview_cmds, "MAX_ASSETS_SCANNED", 3)
    result = market_overview_cmds.build_market_overview(data_dir, store="1D", window=30, limit=15)
    assert result["assets_in_store"] == 5
    assert result["assets_scanned"] == 3 and result["scan_cap"] == 3
    assert {row["asset"] for row in result["assets"]} == {"AAA", "BBB", "CCC"}
    assert result["too_few_bars"] == []  # DDD was past the cap, never read


def test_the_bar_cap_refuses_a_longer_window(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(market_overview_cmds, "MAX_BARS_READ", 40)
    with pytest.raises(DataError, match="bar cap"):
        market_overview_cmds.build_market_overview(data_dir, store="1D", window=90, limit=15)


def test_unknown_store_and_window_fail_loud(data_dir: Path) -> None:
    with pytest.raises(DataError, match="no stored bars"):
        market_overview_cmds.build_market_overview(data_dir, store="1h", window=30, limit=15)
    with pytest.raises(DataError, match="window"):
        market_overview_cmds.build_market_overview(data_dir, store="1D", window=45, limit=15)


def _listing(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(root)): (path.stat().st_mtime_ns, path.stat().st_size)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_the_command_changes_no_file_and_prints_json(
    data_dir: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path_factory.mktemp("home")
    (home / "keep.txt").write_text("unchanged")
    monkeypatch.setenv("HOME", str(home))
    before = (_listing(data_dir), _listing(home))
    result = runner.invoke(
        app, ["data", "market-overview", "--window", "30", "--limit", "2", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [row["asset"] for row in payload["assets"]] == ["AAA", "BBB"]
    assert (_listing(data_dir), _listing(home)) == before
    assert not (data_dir / "ledger").exists()


def test_load_bars_last_keeps_only_the_newest_bars(data_dir: Path) -> None:
    from alpha_cli._runner import load_bars

    full, _ = load_bars("AAA", data_dir=data_dir)
    cut, _ = load_bars("AAA", data_dir=data_dir, last=30)
    assert cut == full[-30:]


def test_overview_validates_only_the_window_of_a_long_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import alpha_core

    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    _write(tmp_path, "LONG", 2000, 100.0, 0.01, 1000.0, 1000.0)
    built: list[int] = []
    original_init = alpha_core.Bar.__init__

    def counting_init(self: alpha_core.Bar, **data: object) -> None:
        built.append(1)
        original_init(self, **data)

    monkeypatch.setattr(alpha_core.Bar, "__init__", counting_init)
    result = market_overview_cmds.build_market_overview(tmp_path, store="1D", window=30, limit=5)
    assert result["assets"][0]["asset"] == "LONG"
    assert len(built) <= market_overview_cmds.MAX_BARS_READ


def test_the_text_overview_states_the_period_beside_each_percent(data_dir: Path) -> None:
    result = runner.invoke(app, ["data", "market-overview", "--window", "30", "--limit", "2"])
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if "%" in line]
    assert lines and all("over the last 30 bars" in line for line in lines)
