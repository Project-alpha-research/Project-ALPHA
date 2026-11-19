"""CFTC Commitments of Traders context rows: known-at clock, strict parsing, revisions."""

import json
import urllib.error
import urllib.parse
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_core import DataError
from alpha_data.context import cftc_cot, free_http
from alpha_data.context.events import as_known_events, load_events

FIX = Path(__file__).parents[1] / "fixtures/context/cftc/legacy_futures_sample.json"
NOW = datetime(2024, 2, 1, tzinfo=UTC)


def records() -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = json.loads(FIX.read_text())
    return loaded


class FakeTransport:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, Mapping[str, str], float]] = []

    def __call__(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        self.calls.append((url, headers, timeout))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        offset, limit = int(query["$offset"][0]), int(query["$limit"][0])
        return 200, {}, json.dumps(self.rows[offset : offset + limit]).encode()


@pytest.fixture(autouse=True)
def no_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(free_http, "PAUSE_SECONDS", 0.0)


def pull(tmp_path: Path, rows: list[dict[str, Any]], **kw: Any) -> FakeTransport:
    transport = FakeTransport(rows)
    cftc_cot.pull_cot(
        data_dir=tmp_path,
        markets=["13874A"],
        since=date(2024, 1, 1),
        fetched_at=NOW,
        client=free_http.Client(transport=transport),
        **kw,
    )
    return transport


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (date(2024, 1, 9), datetime(2024, 1, 12, 20, 30, tzinfo=UTC)),  # winter: 15:30 EST
        (date(2024, 1, 2), datetime(2024, 1, 8, 20, 30, tzinfo=UTC)),  # 1 Jan Monday: later
        (date(2024, 6, 4), datetime(2024, 6, 7, 19, 30, tzinfo=UTC)),  # summer: 15:30 EDT
        (date(2024, 1, 16), datetime(2024, 1, 22, 20, 30, tzinfo=UTC)),  # MLK Monday: later
        (date(2024, 7, 2), datetime(2024, 7, 8, 19, 30, tzinfo=UTC)),  # Thursday 4 July: later
        (date(2023, 12, 26), datetime(2024, 1, 2, 20, 30, tzinfo=UTC)),  # skips 1 Jan holiday
        (date(2024, 11, 5), datetime(2024, 11, 8, 20, 30, tzinfo=UTC)),  # Friday, no holiday
    ],
)
def test_known_from_is_publication_time_never_the_as_of_date(
    as_of: date, expected: datetime
) -> None:
    known = cftc_cot.known_from(as_of)
    assert known == expected
    assert known.date() > as_of


STAMP = datetime(2025, 11, 19, 20, 30, 44, 507000, tzinfo=UTC)


@pytest.mark.parametrize(
    ("report", "stamp", "known", "basis"),
    [
        # Shutdown backlog: published weeks after the rule time, the stamp wins (later).
        (date(2025, 9, 30), STAMP, STAMP, "stamp"),
        # History reloaded in bulk in 2022: the stamp says nothing about publication; rule used.
        (date(2016, 3, 1), datetime(2022, 9, 13, 14, 25, tzinfo=UTC), None, "rule"),
        # A stamp before the rule time never moves the time earlier.
        (date(2024, 1, 9), datetime(2024, 1, 10, tzinfo=UTC), None, "rule"),
    ],
)
def test_stamp_is_used_only_when_it_is_later_and_a_live_release(
    report: date, stamp: datetime, known: datetime | None, basis: str
) -> None:
    rule = cftc_cot.known_from(report)
    got, why = cftc_cot.resolve_known(rule, stamp)
    assert (got, why) == (known or rule, basis)
    assert got >= rule


def test_known_from_rejects_a_report_date_after_thursday() -> None:
    with pytest.raises(DataError, match="report_date"):
        cftc_cot.known_from(date(2024, 1, 6))


def test_map_rows_values_and_columns() -> None:
    df = cftc_cot.map_rows(records(), "13874A")
    assert df.schema == cftc_cot.SCHEMA
    first = df.row(0, named=True)
    assert first["market_code"] == "13874A"
    assert first["market_name"] == "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE"
    assert first["report_date"] == date(2024, 1, 9)
    assert first["noncomm_spread"] == 50000 and first["open_interest"] == 2000000
    assert first["known_from"] == datetime(2024, 1, 12, 20, 30, 47, 123000, tzinfo=UTC)
    assert first["known_basis"] == "stamp"
    assert df["report_date"].is_sorted(descending=False)


def test_early_read_cannot_see_a_late_known_row(tmp_path: Path) -> None:
    pull(tmp_path, records())
    table = load_events(
        cftc_cot.table_path(tmp_path, "13874A"), source="cftc-cot", schema=cftc_cot.SCHEMA
    )
    before = datetime(2024, 1, 11, tzinfo=UTC)  # the Thursday after the Tuesday positions
    assert as_known_events(table, as_of=before).is_empty()
    leaky = table.filter(pl.col("report_date") <= before.date())
    assert leaky.height == 1  # a read keyed on the period would leak this row
    just_before = datetime(2024, 1, 12, 20, 30, 47, tzinfo=UTC)
    assert as_known_events(table, as_of=just_before).is_empty()
    exact = as_known_events(table, as_of=datetime(2024, 1, 12, 20, 30, 47, 123000, tzinfo=UTC))
    assert exact["report_date"].to_list() == [date(2024, 1, 9)]
    # 2024-01-16 is a holiday week: known Monday 22 January, not Friday 19 January.
    friday = as_known_events(table, as_of=datetime(2024, 1, 19, 21, 0, tzinfo=UTC))
    assert friday["report_date"].to_list() == [date(2024, 1, 9)]


def test_pull_stores_provenance_and_is_idempotent(tmp_path: Path) -> None:
    pull(tmp_path, records())
    again = pull(tmp_path, records())
    path = cftc_cot.table_path(tmp_path, "13874A")
    meta = json.loads(path.with_suffix(".json").read_text())
    assert meta["source"] == "cftc-cot" and meta["rows"] == 3
    assert "Friday 15:30" in meta["known_from_rule"]
    assert meta["market_code"] == "13874A"
    assert again.calls  # the second pull still asks, then finds identical rows
    assert load_events(path, source="cftc-cot", schema=cftc_cot.SCHEMA).height == 3


def test_request_contract_pacing_and_paging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cftc_cot, "PAGE", 2)
    sleeps: list[float] = []
    monkeypatch.setattr(free_http, "PAUSE_SECONDS", 0.5)
    transport = FakeTransport(records())
    client = free_http.Client(transport=transport, sleep=sleeps.append, clock=lambda: 0.0)
    cftc_cot.pull_cot(
        data_dir=tmp_path,
        markets=["13874A"],
        since=date(2024, 1, 1),
        fetched_at=NOW,
        client=client,
    )
    assert len(transport.calls) == 2 and sleeps == [0.5]
    url, headers, timeout = transport.calls[0]
    assert url.startswith("https://publicreporting.cftc.gov/resource/6dca-aqww.json?")
    assert headers["User-Agent"] == "Project-ALPHA/1.0" and timeout == 30
    assert "13874A" in urllib.parse.unquote(url)
    assert load_events(
        cftc_cot.table_path(tmp_path, "13874A"), source="cftc-cot", schema=cftc_cot.SCHEMA
    )["report_date"].to_list() == [date(2024, 1, 9), date(2024, 1, 16), date(2024, 1, 23)]


def test_revised_value_is_refused_and_nothing_is_replaced(tmp_path: Path) -> None:
    pull(tmp_path, records())
    path = cftc_cot.table_path(tmp_path, "13874A")
    before = path.read_bytes()
    revised = records()
    revised[1]["open_interest_all"] = "2011111"
    with pytest.raises(DataError, match="revised .*13874A.*2024-01-16"):
        pull(tmp_path, revised)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"open_interest_all": "nan"}, "open_interest_all"),
        ({"open_interest_all": "1.5"}, "open_interest_all"),
        ({"comm_positions_long_all": "-3"}, "comm_positions_long_all"),
        ({"noncomm_postions_spread_all": None}, "noncomm_postions_spread_all"),
        ({"report_date_as_yyyy_mm_dd": "2024-13-02T00:00:00.000"}, "report_date_as_yyyy_mm_dd"),
        ({"report_date_as_yyyy_mm_dd": "2024-01-02"}, "report_date_as_yyyy_mm_dd"),
        ({"cftc_contract_market_code": "999999"}, "cftc_contract_market_code"),
        ({":created_at": "2024-01-12 20:30"}, ":created_at"),
        ({":created_at": None}, ":created_at"),
    ],
)
def test_invalid_rows_fail_naming_the_field(change: dict[str, Any], field: str) -> None:
    rows = records()
    rows[0].update(change)
    with pytest.raises(DataError, match=field):
        cftc_cot.map_rows(rows, "13874A")


def test_schema_drift_names_the_missing_field() -> None:
    rows = records()
    del rows[1]["noncomm_positions_long_all"]
    with pytest.raises(DataError, match="noncomm_positions_long_all"):
        cftc_cot.map_rows(rows, "13874A")


def test_duplicate_and_disordered_dates_fail() -> None:
    with pytest.raises(DataError, match="duplicate.*report_date"):
        cftc_cot.map_rows([records()[0], *records()], "13874A")
    rows = records()
    rows[0], rows[1] = rows[1], rows[0]
    with pytest.raises(DataError, match="disordered.*report_date"):
        cftc_cot.map_rows(rows, "13874A")


def test_empty_answer_and_bad_market_code_fail(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="no rows"):
        pull(tmp_path, [])
    with pytest.raises(DataError, match="market"):
        cftc_cot.table_path(tmp_path, "../x")


def test_offline_is_a_clear_error_and_stores_nothing(tmp_path: Path) -> None:
    def offline(url: str, headers: Mapping[str, str], timeout: float) -> Any:
        raise urllib.error.URLError("no route")

    with pytest.raises(DataError, match="offline"):
        cftc_cot.pull_cot(
            data_dir=tmp_path,
            markets=["13874A"],
            since=date(2024, 1, 1),
            fetched_at=NOW,
            client=free_http.Client(transport=offline),
        )
    assert not (tmp_path / "context").exists()


def test_http_error_status_is_reported(tmp_path: Path) -> None:
    def refuse(url: str, headers: Mapping[str, str], timeout: float) -> Any:
        return 503, {}, b"busy"

    with pytest.raises(DataError, match="HTTP 503"):
        cftc_cot.pull_cot(
            data_dir=tmp_path,
            markets=["13874A"],
            since=date(2024, 1, 1),
            fetched_at=NOW,
            client=free_http.Client(transport=refuse),
        )
