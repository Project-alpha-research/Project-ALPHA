"""FINRA daily short sale volume context rows: known-at clock, strict parsing, revisions."""

import urllib.error
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_core import DataError
from alpha_data.context import finra_short, free_http
from alpha_data.context.events import as_known_events, load_events

FIX = Path(__file__).parents[1] / "fixtures/context/finra"
NOW = datetime(2024, 2, 1, tzinfo=UTC)


class FakeTransport:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.calls: list[tuple[str, Mapping[str, str], float]] = []

    def __call__(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        self.calls.append((url, headers, timeout))
        name = url.rsplit("/", 1)[1]
        # The real host answers 403 for a day that has no file (weekend, holiday).
        return (200, {}, self.files[name]) if name in self.files else (403, {}, b"<Error/>")


def files() -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in FIX.glob("CNMSshvol*.txt")}


@pytest.fixture(autouse=True)
def no_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(free_http, "PAUSE_SECONDS", 0.0)


def pull(tmp_path: Path, served: dict[str, bytes], **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = dict(
        data_dir=tmp_path,
        symbols=["SPY", "TEST"],
        start=date(2024, 1, 2),
        end=date(2024, 1, 3),
        fetched_at=NOW,
        client=free_http.Client(transport=FakeTransport(served)),
    )
    return finra_short.pull_short_volume(**{**args, **kw})


def test_known_from_is_the_next_utc_midnight() -> None:
    assert finra_short.known_from(date(2024, 1, 2)) == datetime(2024, 1, 3, tzinfo=UTC)
    assert finra_short.known_from(date(2024, 12, 31)) == datetime(2025, 1, 1, tzinfo=UTC)


def test_map_file_values_filter_and_trailer() -> None:
    df = finra_short.map_file(files()["CNMSshvol20240102.txt"], date(2024, 1, 2), {"SPY"})
    assert df.schema == finra_short.SCHEMA
    row = df.row(0, named=True)
    assert df.height == 1 and row["symbol"] == "SPY" and row["trade_date"] == date(2024, 1, 2)
    assert row["short_volume"] == pytest.approx(5000000.5, rel=1e-9, abs=1e-12)
    assert row["short_exempt_volume"] == pytest.approx(100.0, rel=1e-9, abs=1e-12)
    assert row["total_volume"] == pytest.approx(12000000.25, rel=1e-9, abs=1e-12)
    assert row["markets"] == "B,Q,N"
    assert row["known_from"] == datetime(2024, 1, 3, tzinfo=UTC)


def test_pull_stores_each_symbol_with_the_facility_caveat(tmp_path: Path) -> None:
    report = pull(tmp_path, files())
    assert report["rows"] == 4 and report["missing_days"] == []
    assert "FINRA facilities only" in report["caveat"]
    path = finra_short.table_path(tmp_path, "SPY")
    stored = load_events(path, source="finra-short-volume", schema=finra_short.SCHEMA)
    assert stored["trade_date"].to_list() == [date(2024, 1, 2), date(2024, 1, 3)]
    meta = path.with_suffix(".json")
    assert "FINRA facilities only" in meta.read_text() and "next UTC midnight" in meta.read_text()


def test_early_read_cannot_see_a_late_known_row(tmp_path: Path) -> None:
    pull(tmp_path, files())
    table = load_events(
        finra_short.table_path(tmp_path, "SPY"),
        source="finra-short-volume",
        schema=finra_short.SCHEMA,
    )
    evening = datetime(2024, 1, 2, 23, 59, tzinfo=UTC)  # trading day 2 Jan has ended
    assert as_known_events(table, as_of=evening).is_empty()
    assert table.filter(pl.col("trade_date") <= evening.date()).height == 1  # leaky control
    midnight = as_known_events(table, as_of=datetime(2024, 1, 3, tzinfo=UTC))
    assert midnight["trade_date"].to_list() == [date(2024, 1, 2)]


def test_weekend_and_holiday_without_file_are_listed_not_fatal(tmp_path: Path) -> None:
    transport = FakeTransport({"CNMSshvol20240102.txt": files()["CNMSshvol20240102.txt"]})
    report = finra_short.pull_short_volume(
        data_dir=tmp_path,
        symbols=["SPY"],
        start=date(2024, 1, 2),
        end=date(2024, 1, 7),
        fetched_at=NOW,
        client=free_http.Client(transport=transport),
    )
    assert report["missing_days"] == ["2024-01-03", "2024-01-04", "2024-01-05"]
    assert len(transport.calls) == 4  # Saturday and Sunday are never requested
    url, headers, timeout = transport.calls[0]
    assert url == "https://cdn.finra.org/equity/regsho/daily/CNMSshvol20240102.txt"
    assert headers["User-Agent"] == "Project-ALPHA/1.0" and timeout == 30


def test_revised_value_is_refused_and_nothing_is_replaced(tmp_path: Path) -> None:
    pull(tmp_path, files())
    path = finra_short.table_path(tmp_path, "SPY")
    before = path.read_bytes()
    revised = files()
    revised["CNMSshvol20240102.txt"] = revised["CNMSshvol20240102.txt"].replace(
        b"5000000.5", b"5000001.5"
    )
    with pytest.raises(DataError, match="revised .*SPY.*2024-01-02"):
        pull(tmp_path, revised)
    assert path.read_bytes() == before


def test_unchanged_repull_is_idempotent(tmp_path: Path) -> None:
    pull(tmp_path, files())
    assert pull(tmp_path, files())["rows"] == 4


@pytest.mark.parametrize(
    ("old", "new", "field"),
    [
        (b"5000000.5", b"nan", "ShortVolume"),
        (b"5000000.5", b"-1", "ShortVolume"),
        (b"|100|", b"|inf|", "ShortExemptVolume"),
        (b"12000000.25", b"abc", "TotalVolume"),
        (b"12000000.25", b"4000000", "TotalVolume"),  # short volume above total
        (b"20240102|SPY", b"20240103|SPY", "Date"),
        (b"20240102|SPY", b"2024-01-02|SPY", "Date"),
        (b"20240102|TEST", b"20240102|SPY", "Symbol"),  # duplicate symbol
        (b"|B,Q,N\r\n", b"|1\r\n", "Market"),
    ],
)
def test_invalid_rows_fail_naming_the_field(old: bytes, new: bytes, field: str) -> None:
    raw = files()["CNMSshvol20240102.txt"].replace(old, new, 1)
    with pytest.raises(DataError, match=field):
        finra_short.map_file(raw, date(2024, 1, 2), None)


def test_real_symbol_shapes_are_accepted_but_junk_is_not() -> None:
    raw = (
        files()["CNMSshvol20240102.txt"]
        .replace(b"|ZZZ|", b"|AAC/WS|")
        .replace(b"|TEST|", b"|ABCp|")
    )
    assert finra_short.map_file(raw, date(2024, 1, 2), None)["symbol"].to_list() == [
        "AAC/WS",
        "ABCp",
        "SPY",
    ]
    with pytest.raises(DataError, match="Symbol"):
        finra_short.map_file(raw.replace(b"|ABCp|", b"|A B|"), date(2024, 1, 2), None)


def test_schema_drift_and_trailer_mismatch_fail() -> None:
    raw = files()["CNMSshvol20240102.txt"]
    with pytest.raises(DataError, match="header"):
        finra_short.map_file(raw.replace(b"TotalVolume", b"Total"), date(2024, 1, 2), None)
    with pytest.raises(DataError, match="record count"):
        finra_short.map_file(raw.replace(b"\r\n3\r\n", b"\r\n9\r\n"), date(2024, 1, 2), None)
    with pytest.raises(DataError, match="record count"):
        finra_short.map_file(raw.rsplit(b"3\r\n", 1)[0], date(2024, 1, 2), None)


def test_offline_is_a_clear_error_and_stores_nothing(tmp_path: Path) -> None:
    def offline(url: str, headers: Mapping[str, str], timeout: float) -> Any:
        raise urllib.error.URLError("no route")

    with pytest.raises(DataError, match="offline"):
        finra_short.pull_short_volume(
            data_dir=tmp_path,
            symbols=["SPY"],
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            fetched_at=NOW,
            client=free_http.Client(transport=offline),
        )
    assert not (tmp_path / "context").exists()


def test_bad_symbol_and_range_fail(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="symbol"):
        finra_short.table_path(tmp_path, "../x")
    with pytest.raises(DataError, match="range"):
        pull(tmp_path, files(), start=date(2024, 1, 5), end=date(2024, 1, 2))
