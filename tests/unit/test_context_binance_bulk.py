"""Checksummed synthetic derivatives archives and immutable overlaps."""

import hashlib
import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Never

import polars as pl
import pytest

from alpha_core import DataError
from alpha_data.context.binance_bulk import map_binance_csv, periods, pull_binance
from alpha_data.context.events import FUNDING_SCHEMA, as_known_events, load_events

FIX = Path(__file__).parents[1] / "fixtures/context/binance"
NOW = datetime(2024, 2, 1, tzinfo=UTC)


def zipped(raw: bytes) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("data.csv", raw)
    return stream.getvalue()


class Wire:
    def __init__(self, kind: str = "funding") -> None:
        self.raw = (
            FIX / ("funding_2024-01.csv" if kind == "funding" else "metrics_2024-01-02.csv")
        ).read_bytes()
        self.calls: list[str] = []
        self.bad_checksum = False

    def checksum(self, url: str) -> bytes:
        self.calls.append(url)
        if "2024-02.zip" in url:
            raise DataError("Binance archive request failed with HTTP 404")
        return (
            hashlib.sha256(b"bad" if self.bad_checksum else zipped(self.raw)).hexdigest()
            + "  data.zip"
        ).encode()

    def archive(self, url: str) -> bytes:
        self.calls.append(url)
        return zipped(self.raw)

    def pull(self, path: Path, **kwargs: Any) -> dict[str, Any]:
        return pull_binance(
            data_dir=path,
            symbol="BTCUSDT",
            kind="funding",
            start="2024-01",
            end="2024-02",
            fetched_at=NOW,
            fetch_checksum=self.checksum,
            fetch_archive=self.archive,
            **kwargs,
        )


def test_mapping_clocks_nullable_and_legacy() -> None:
    funding = map_binance_csv("funding", (FIX / "funding_2024-01.csv").read_bytes())
    assert funding["funding_time"].equals(funding["known_from"])
    assert funding["funding_rate"].to_list() == pytest.approx([0.00037409, 0.00027213])
    legacy = map_binance_csv("funding", b"calc_time,last_funding_rate\n1704067200000,0.1\n")
    assert legacy["interval_hours"].to_list() == [None]
    metrics = map_binance_csv("metrics", (FIX / "metrics_2024-01-02.csv").read_bytes())
    gap = (FIX / "metrics_2024-01-02.csv").read_bytes().replace(b"1.02826047", b"")
    assert map_binance_csv("metrics", gap)["top_trader_account_ratio"].to_list()[1] is None
    assert metrics["known_from"].to_list() == [ts + timedelta(minutes=5) for ts in metrics["ts"]]
    assert as_known_events(metrics, as_of=datetime(2024, 1, 2, 0, 4, 59, tzinfo=UTC)).is_empty()
    assert as_known_events(metrics, as_of=datetime(2024, 1, 2, 0, 5, tzinfo=UTC)).height == 1


@pytest.mark.parametrize(
    "raw",
    [
        b"wrong,header\n1,2\n",
        b"1704067200000,8,0.1\n",
        b"calc_time,last_funding_rate\n1704067200000,nan\n",
        b"calc_time,last_funding_rate\n1704067200000,inf\n",
        b"calc_time,last_funding_rate\nwrong,1\n",
    ],
)
def test_invalid_csv_fails(raw: bytes) -> None:
    with pytest.raises(DataError):
        map_binance_csv("funding", raw)


def test_cache_missing_and_overlap(tmp_path: Path) -> None:
    wire = Wire()
    first = wire.pull(tmp_path)
    assert first == dict(
        symbol="BTCUSDT",
        kind="funding",
        periods=["2024-01", "2024-02"],
        fetched=1,
        cached=0,
        missing=["2024-02"],
        rows=2,
    )
    wire.calls.clear()
    assert wire.pull(tmp_path)["cached"] == 1
    assert all(url.endswith(".CHECKSUM") for url in wire.calls)
    path = tmp_path / "context/binance/um/funding/BTCUSDT.parquet"
    before = path.read_bytes()
    wire.raw = wire.raw.replace(b"0.00037409", b"0.00099999")
    with pytest.raises(DataError, match="Binance revised funding BTCUSDT at"):
        wire.pull(tmp_path)
    assert path.read_bytes() == before


def test_checksum_failure_stores_nothing(tmp_path: Path) -> None:
    wire = Wire()
    wire.bad_checksum = True
    with pytest.raises(DataError, match="checksum"):
        wire.pull(tmp_path)
    assert not list(tmp_path.rglob("*"))


def test_all_missing_and_other_errors_fail(tmp_path: Path) -> None:
    for status in [404, 403, 500]:

        def fail(url: str, code: int = status) -> Never:
            raise DataError(f"Binance archive request failed with HTTP {code}")

        with pytest.raises(DataError, match="missing" if status == 404 else str(status)):
            pull_binance(
                data_dir=tmp_path,
                symbol="BTCUSDT",
                kind="funding",
                start="2024-01",
                end="2024-01",
                fetched_at=NOW,
                fetch_checksum=fail,
                fetch_archive=lambda url: pytest.fail("no archive request"),
            )


def test_metrics_bound_and_period_validation() -> None:
    assert periods("funding", "2023-12", "2024-02") == ["2023-12", "2024-01", "2024-02"]
    assert len(periods("metrics", "2024-01-01", "2025-02-03")) == 400
    for kind, start, end in [
        ("metrics", "2024-01-01", "2025-02-04"),
        ("funding", "2024-02", "2024-01"),
        ("funding", "2024-1", "2024-02"),
    ]:
        with pytest.raises(DataError, match="BAD_RANGE"):
            periods(kind, start, end)


def test_future_poison_and_leaky_control(tmp_path: Path) -> None:
    Wire().pull(tmp_path)
    df = load_events(
        tmp_path / "context/binance/um/funding/BTCUSDT.parquet",
        source="binance",
        schema=FUNDING_SCHEMA,
    )
    cutoff = datetime(2024, 1, 1, tzinfo=UTC)
    poisoned = df.with_columns(
        pl.when(pl.col("known_from") > cutoff)
        .then(1e100)
        .otherwise(pl.col("funding_rate"))
        .alias("funding_rate")
    )
    assert as_known_events(df, as_of=cutoff).equals(as_known_events(poisoned, as_of=cutoff))
    assert not df.equals(poisoned)


def test_metrics_pull_cache_and_revisions(tmp_path: Path) -> None:
    from alpha_data.context.events import METRICS_SCHEMA

    wire = Wire("metrics")

    def pull() -> dict[str, Any]:
        return pull_binance(
            data_dir=tmp_path,
            symbol="BTCUSDT",
            kind="metrics",
            start="2024-01-02",
            end="2024-01-02",
            fetched_at=NOW,
            fetch_checksum=wire.checksum,
            fetch_archive=wire.archive,
        )

    assert pull()["fetched"] == 1
    assert pull()["cached"] == 1
    path = tmp_path / "context/binance/um/metrics/BTCUSDT.parquet"
    frame = load_events(path, source="binance", schema=METRICS_SCHEMA)
    assert frame["known_from"][0] == datetime(2024, 1, 2, 0, 5, tzinfo=UTC)
    original = path.read_bytes()
    wire.raw = wire.raw.replace(b",76608.79800000,", b",99999.0,")
    with pytest.raises(DataError, match="Binance revised metrics BTCUSDT at"):
        pull()
    assert path.read_bytes() == original


def test_checksum_failure_in_later_period_publishes_nothing(tmp_path: Path) -> None:
    raw = (FIX / "funding_2024-01.csv").read_bytes()

    def checksum(url: str) -> bytes:
        return hashlib.sha256(zipped(raw) if "2024-01" in url else b"wrong").hexdigest().encode()

    with pytest.raises(DataError, match="checksum"):
        pull_binance(
            data_dir=tmp_path,
            symbol="BTCUSDT",
            kind="funding",
            start="2024-01",
            end="2024-02",
            fetched_at=NOW,
            fetch_checksum=checksum,
            fetch_archive=lambda url: zipped(raw),
        )
    assert not list(tmp_path.rglob("*"))
