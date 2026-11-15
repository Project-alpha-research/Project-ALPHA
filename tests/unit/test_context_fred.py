"""Synthetic FRED/ALFRED responses and point-in-time storage checks; no network."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from email.message import Message
from http.client import HTTPMessage
from pathlib import Path
from typing import Any, Never
from urllib.parse import parse_qs, urlsplit

import polars as pl
import pytest

from alpha_core import DataError
from alpha_data.context.fred import (
    DEFAULT_SERIES,
    FredAdapter,
    as_known,
    first_release,
    latest,
    load_series,
    parse_observations,
    pull_series,
    store_series,
)
from alpha_data.context.views import SCHEMA, validate

META = dict(
    title="Example",
    units="Percent",
    frequency="Monthly",
    seasonal_adjustment="Not Seasonally Adjusted",
    last_updated="2024-04-01 12:00:00-05",
)
NOW = datetime(2024, 4, 1, tzinfo=UTC)


def observation(
    day: str = "2024-01-01", value: str = "1", start: str = "2024-02-01", end: str = "9999-12-31"
) -> dict[str, str]:
    return dict(date=day, value=value, realtime_start=start, realtime_end=end)


def observations() -> list[dict[str, str]]:
    return [
        observation(end="2024-03-14"),
        observation(value="2", start="2024-03-15"),
        observation("2024-02-01", ".", "2024-03-01"),
        observation("2024-03-01", "4", "2024-04-01"),
    ]


def frame() -> pl.DataFrame:
    return parse_observations("X", observations())


class FakeTransport:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, Mapping[str, str], float]] = []

    def __call__(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        self.calls.append((url, headers, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, tuple) else (200, {}, json.dumps(response).encode())


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> str:
    # Generated only in memory: no actual or fixed credential fixture.
    import secrets

    value = secrets.token_hex(16)
    monkeypatch.setenv("FRED_API_KEY", value)
    return value


def test_parse_vintages_and_missing_values() -> None:
    df = frame()
    assert df.schema == {
        "series_id": pl.String,
        "obs_date": pl.Date,
        "value": pl.Float64,
        "known_from": pl.Date,
        "known_until": pl.Date,
    }
    assert df["value"].to_list() == [1.0, 2.0, None, 4.0]
    assert df["known_until"].to_list() == [date(2024, 3, 14), None, None, None]
    assert len(DEFAULT_SERIES) == 18 and DEFAULT_SERIES["DFF"] == "Fed funds rate"


def test_as_known_first_and_latest() -> None:
    assert as_known(frame(), as_of=date(2024, 3, 10))["value"].to_list() == [1.0, None]
    assert as_known(frame(), as_of=date(2024, 3, 15))["value"].to_list() == [2.0, None]
    assert as_known(frame(), as_of=date(2024, 1, 1)).is_empty()
    assert first_release(frame())["value"].to_list() == [1.0, None, 4.0]
    assert latest(frame())["value"].to_list() == [2.0, None, 4.0]


def expiry_frame() -> pl.DataFrame:
    return parse_observations(
        "X",
        [
            observation(value="1", start="2024-02-01", end="2024-02-10"),
            observation(value="2", start="2024-02-11", end="2024-02-20"),
            observation(value="3", start="2024-03-01", end="2024-03-05"),
        ],
    )


@pytest.mark.parametrize(
    ("cutoff", "values"),
    [
        ("2024-01-31", []),
        ("2024-02-01", [1.0]),
        ("2024-02-10", [1.0]),
        ("2024-02-11", [2.0]),
        ("2024-02-20", [2.0]),
        ("2024-02-21", []),
        ("2024-02-29", []),
        ("2024-03-01", [3.0]),
        ("2024-03-05", [3.0]),
        ("2024-03-06", []),
    ],
)
def test_as_known_validity_intervals(cutoff: str, values: list[float]) -> None:
    # Adjacent revisions share no day; the later gap and terminal expiry have no row.
    result = as_known(expiry_frame(), as_of=date.fromisoformat(cutoff))
    assert result["value"].to_list() == values
    assert result.schema == expiry_frame().schema


@pytest.mark.parametrize("value", ["7", "."])
@pytest.mark.parametrize("end", ["2024-02-10", "9999-12-31"])
@pytest.mark.parametrize("cutoff", ["2024-02-10", "2024-02-11"])
def test_as_known_null_value_and_open_end_are_distinct(value: str, end: str, cutoff: str) -> None:
    df = parse_observations("X", [observation(value=value, end=end)])
    result = as_known(df, as_of=date.fromisoformat(cutoff))
    expected = [] if end < cutoff else [None if value == "." else 7.0]
    assert result["value"].to_list() == expected


def test_expiry_preserves_explicit_first_release_and_latest_contracts() -> None:
    df = pl.concat(
        [
            expiry_frame(),
            parse_observations(
                "X",
                [
                    observation("2024-02-01", "4", "2024-02-02", "2024-02-10"),
                    observation("2024-02-01", ".", "2024-02-11"),
                ],
            ),
        ]
    )
    assert first_release(df).select("obs_date", "value", "known_from").rows() == [
        (date(2024, 1, 1), 1.0, date(2024, 2, 1)),
        (date(2024, 2, 1), 4.0, date(2024, 2, 2)),
    ]
    # Finite-ended rows are excluded even when they end after a historical cutoff.
    assert latest(df).select("obs_date", "value", "known_from").rows() == [
        (date(2024, 2, 1), None, date(2024, 2, 11)),
    ]


@pytest.mark.bias_guard
def test_as_known_expiry_future_poison_and_leaky_control() -> None:
    cutoff = date(2024, 2, 25)
    original = pl.concat(
        [
            expiry_frame(),
            parse_observations("X", [observation("2023-12-01", "4", "2024-01-01")]),
            parse_observations("X", [observation("2024-02-01", "5", "2024-03-01")]),
        ]
    )
    poisoned = original.with_columns(
        pl.when(pl.col("known_from") > cutoff)
        .then(999999.0)
        .otherwise(pl.col("value"))
        .alias("value")
    )
    expected = parse_observations("X", [observation("2023-12-01", "4", "2024-01-01")])
    assert as_known(original, as_of=cutoff).equals(expected)
    assert as_known(poisoned, as_of=cutoff).equals(expected)
    with pytest.raises(AssertionError):
        assert latest(original).equals(latest(poisoned))
    # The prior start-only selection leaks an expired vintage even without future values.
    leaky = (
        original.filter(pl.col("known_from") <= cutoff)
        .sort("known_from")
        .unique(subset=["series_id", "obs_date"], keep="last")
        .sort("series_id", "obs_date")
    )
    with pytest.raises(AssertionError):
        assert leaky.equals(expected)


@pytest.mark.bias_guard
def test_as_known_future_poison_and_leaky_control() -> None:
    cutoff = date(2024, 3, 10)
    original = frame()
    poisoned = original.with_columns(
        pl.when(pl.col("known_from") > cutoff)
        .then(999999.0)
        .otherwise(pl.col("value"))
        .alias("value")
    )
    assert as_known(original, as_of=cutoff).equals(as_known(poisoned, as_of=cutoff))
    with pytest.raises(AssertionError):
        assert latest(original).equals(latest(poisoned))


def test_paging_and_request_contract(key: str) -> None:
    fake = FakeTransport(
        [
            {"seriess": [{"id": "X", **META}]},
            {"count": 4, "offset": 0, "observations": observations()[:2]},
            {"count": 4, "offset": 2, "observations": observations()[2:]},
        ]
    )
    df, metadata = FredAdapter(transport=fake).fetch("X", as_of=NOW.date())
    assert df.equals(frame()) and metadata == META
    queries = [parse_qs(urlsplit(c[0]).query) for c in fake.calls]
    assert [q.get("offset") for q in queries] == [None, ["0"], ["2"]]
    for q in queries:
        assert q["api_key"] == [key] and q["file_type"] == ["json"]
        assert q["series_id"] == ["X"]
    assert queries[1]["realtime_start"] == ["1776-07-04"]
    assert queries[1]["realtime_end"] == ["9999-12-31"]
    assert queries[1]["limit"] == ["100000"]


@pytest.mark.parametrize(
    ("as_of", "last_start"),
    [(date(1998, 12, 31), "1995-01-01"), (date(2024, 4, 1), "2025-01-01")],
)
def test_full_range_400_retries_five_year_windows_and_merges(
    key: str, as_of: date, last_start: str
) -> None:
    calls: list[dict[str, str]] = []

    def transport(
        url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        if urlsplit(url).path.endswith("/series"):
            body: dict[str, Any] = {"seriess": [{"id": "X", **META}]}
        elif q["realtime_start"] == "1776-07-04" and q["realtime_end"] == "9999-12-31":
            return 400, {}, b'{"error_message":"too many vintages"}'
        else:
            calls.append(q)
            # Identical vintage repeated by adjacent windows must occur once in storage.
            body = {"count": 1, "offset": 0, "observations": [observation()]}
        return 200, {}, json.dumps(body).encode()

    df, _ = FredAdapter(transport=transport).fetch("X", as_of=as_of)
    assert df.height == 1
    assert calls[0]["realtime_start"] == "1776-07-04"
    assert calls[-1]["realtime_end"] == "9999-12-31"
    assert calls[-1]["realtime_start"] == last_start
    assert calls[0]["realtime_end"] == "1919-12-31"
    assert len(calls) < 40  # bounded: one early window, then five-year windows from 1920
    for left, right in zip(calls, calls[1:], strict=False):
        next_start = date.fromisoformat(right["realtime_start"])
        assert date.fromisoformat(left["realtime_end"]) + timedelta(days=1) == next_start


def test_series_without_vintage_history_is_known_the_day_after(key: str) -> None:
    def transport(
        url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        if urlsplit(url).path.endswith("/series"):
            body: dict[str, Any] = {"seriess": [{"id": "X", **META}]}
        elif "realtime_start" in q:
            return 400, {}, b'{"error_message":"The series does not exist in ALFRED but may"}'
        else:
            rows = [
                {
                    "date": "2024-03-01",
                    "value": "4.2",
                    "realtime_start": "2026-01-01",
                    "realtime_end": "2026-01-01",
                },
                {
                    "date": "2024-03-04",
                    "value": ".",
                    "realtime_start": "2026-01-01",
                    "realtime_end": "2026-01-01",
                },
            ]
            body = {"count": 2, "offset": 0, "observations": rows}
        return 200, {}, json.dumps(body).encode()

    df, metadata = FredAdapter(transport=transport).fetch("X", as_of=NOW.date())
    assert metadata["point_in_time"] == "approximate"
    assert df["known_from"].to_list() == [date(2024, 3, 2), date(2024, 3, 5)]
    assert df["known_until"].to_list() == [None, None]
    assert df["value"].to_list() == [4.2, None]


@pytest.mark.parametrize(
    ("as_of", "last_start", "window_count"),
    [
        (date(1800, 1, 1), date(1920, 1, 1), 2),
        (date(1919, 12, 31), date(1920, 1, 1), 2),
        (date(1920, 1, 1), date(1920, 1, 1), 2),
        (date(2026, 11, 15), date(2025, 1, 1), 23),
        (date(9999, 12, 31), date(9995, 1, 1), 1617),
    ],
)
def test_retry_windows_cover_full_range_at_date_extremes(
    key: str, as_of: date, last_start: date, window_count: int
) -> None:
    windows: list[tuple[date, date]] = []

    def transport(
        url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        query = parse_qs(urlsplit(url).query)
        if urlsplit(url).path.endswith("/series"):
            body: dict[str, Any] = {"seriess": [{"id": "X", **META}]}
        else:
            start = date.fromisoformat(query["realtime_start"][0])
            end = date.fromisoformat(query["realtime_end"][0])
            if (start, end) == (date(1776, 7, 4), date.max):
                return 400, {}, b'{"error_message":"too many vintages"}'
            windows.append((start, end))
            body = {"count": 1, "offset": 0, "observations": [observation()]}
        return 200, {}, json.dumps(body).encode()

    df, metadata = FredAdapter(transport=transport).fetch("X", as_of=as_of)
    assert df.equals(parse_observations("X", [observation()]))
    assert metadata == META
    assert windows[0] == (date(1776, 7, 4), date(1919, 12, 31))
    assert windows[-1] == (last_start, date.max)
    assert len(windows) == window_count
    for start, end in windows:
        assert start <= end
    for (_, previous_end), (start, _) in zip(windows, windows[1:], strict=False):
        assert previous_end + timedelta(days=1) == start
    for start, end in windows[1:-1]:
        assert end == date(start.year + 4, 12, 31)


@pytest.mark.parametrize("status", [200, 301, 400, 403, 429, 500])
def test_provider_errors_never_expose_key_or_url(
    key: str, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    url = f"https://api.stlouisfed.org/fred/series?api_key={key}"
    fake = FakeTransport(
        [(status, {}, json.dumps({"error_message": f"refused {url} {key}"}).encode())]
    )
    with pytest.raises(DataError, match="refused") as exc:
        FredAdapter(transport=fake).fetch("X", as_of=NOW.date())
    assert key not in str(exc.value) + caplog.text
    assert "https://" not in str(exc.value) + caplog.text


def test_transport_error_and_missing_key(
    monkeypatch: pytest.MonkeyPatch, key: str, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(DataError, match="transport") as exc:
        FredAdapter(transport=FakeTransport([urllib.error.URLError(key)])).fetch(
            "X", as_of=NOW.date()
        )
    assert key not in str(exc.value) + caplog.text
    monkeypatch.delenv("FRED_API_KEY")
    fake = FakeTransport([])
    with pytest.raises(DataError, match="FRED_API_KEY"):
        FredAdapter(transport=fake).fetch("X", as_of=NOW.date())
    assert not fake.calls


@pytest.mark.parametrize(
    "response",
    [
        [],
        {},
        {"seriess": []},
        {"seriess": [META]},
        {"seriess": [{"id": "X", **META, "units": None}]},
    ],
)
def test_bad_metadata_fails(key: str, response: Any) -> None:
    with pytest.raises(DataError):
        FredAdapter(transport=FakeTransport([response])).fetch("X", as_of=NOW.date())


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"count": 1, "offset": 0, "observations": []},
        {"count": True, "offset": 0, "observations": []},
        {"count": 1, "offset": 1, "observations": [observation()]},
        {"count": 0, "offset": 0, "observations": [observation()]},
    ],
)
def test_bad_pagination_fails(key: str, response: Any) -> None:
    fake = FakeTransport([{"seriess": [{"id": "X", **META}]}, response])
    with pytest.raises(DataError):
        FredAdapter(transport=fake).fetch("X", as_of=NOW.date())


@pytest.mark.parametrize(
    "change",
    [
        {"value": "NaN"},
        {"value": "inf"},
        {"value": 3},
        {"date": "20240101"},
        {"realtime_start": "bad"},
        {"realtime_end": "2020-01-01"},
    ],
)
def test_bad_observations_fail(change: dict[str, object]) -> None:
    with pytest.raises(DataError):
        parse_observations("X", [{**observation(), **change}])


def test_conflicting_vintage_fails() -> None:
    with pytest.raises(DataError, match="conflict|duplicate"):
        parse_observations("X", [observation(), observation(value="9")])


def test_storage_round_trip_provenance_and_atomic_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replacements: list[str] = []
    real_replace = os.replace

    def replace(src: Path, dst: Path) -> None:
        assert Path(src).parent == Path(dst).parent and Path(src) != Path(dst)
        replacements.append(Path(dst).suffix)
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    provenance = store_series("X", frame(), META, data_dir=tmp_path, fetched_at=NOW)
    assert load_series("X", data_dir=tmp_path).equals(frame())
    path = tmp_path / "context/fred/X.parquet"
    assert provenance == json.loads(path.with_suffix(".json").read_text())
    assert provenance == {
        **META,
        "series_id": "X",
        "source": "fred",
        "fetched_at": NOW.isoformat(),
        "rows": 4,
        "first_obs": "2024-01-01",
        "last_obs": "2024-03-01",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "licence_note": (
            "FRED data; some series are copyrighted by their providers "
            "and are for personal use only"
        ),
        "point_in_time": "vintages",
    }
    store_series("X", first_release(frame()), META, data_dir=tmp_path, fetched_at=NOW)
    assert load_series("X", data_dir=tmp_path).height == 3
    assert replacements == [".parquet", ".json", ".parquet", ".json"]
    assert not list(path.parent.glob("*.tmp"))
    path.write_bytes(b"corrupt")
    with pytest.raises(DataError, match="hash|sha256"):
        load_series("X", data_dir=tmp_path)


@pytest.mark.parametrize("series_id", ["../X", "X/Y", "", "X\\Y"])
def test_series_id_path_safety(tmp_path: Path, series_id: str) -> None:
    with pytest.raises(DataError):
        load_series(series_id, data_dir=tmp_path)


@pytest.mark.parametrize("offset", [False, 0.0, "0"])
def test_offset_requires_integer(key: str, offset: object) -> None:
    fake = FakeTransport(
        [
            {"seriess": [{"id": "X", **META}]},
            {"count": 1, "offset": offset, "observations": [observation()]},
        ]
    )
    with pytest.raises(DataError, match="pagination"):
        FredAdapter(transport=fake).fetch("X", as_of=NOW.date())


def test_successful_credential_reflection_is_not_stored(key: str, tmp_path: Path) -> None:
    fake = FakeTransport([{"seriess": [{"id": "X", **META, "title": key}]}])
    with pytest.raises(DataError, match="credential"):
        FredAdapter(transport=fake).fetch("X", as_of=NOW.date())
    assert not list(tmp_path.iterdir())


def test_urllib_transport_refuses_redirects_without_network(
    key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    handlers: list[urllib.request.HTTPRedirectHandler] = []

    class Opener:
        def open(self, request: urllib.request.Request, timeout: float) -> Never:
            assert timeout == 30
            raise urllib.error.HTTPError(
                request.full_url,
                302,
                "redirect",
                Message(),
                io.BytesIO(b'{"error_message":"redirect refused"}'),
            )

    def build_opener(handler: urllib.request.HTTPRedirectHandler) -> Opener:
        handlers.append(handler)
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build_opener)
    with pytest.raises(DataError, match="HTTP 302") as exc:
        FredAdapter().fetch("X", as_of=NOW.date())
    assert key not in str(exc.value)
    assert (
        handlers[0].redirect_request(
            urllib.request.Request("https://api.stlouisfed.org/fred/series"),
            io.BytesIO(),
            302,
            "",
            HTTPMessage(),
            "https://elsewhere.invalid",
        )
        is None
    )


def test_atomic_write_failure_preserves_old_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_series("X", frame(), META, data_dir=tmp_path, fetched_at=NOW)

    def fail_replace(src: Path, dst: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failure"):
        store_series("X", first_release(frame()), META, data_dir=tmp_path, fetched_at=NOW)
    assert load_series("X", data_dir=tmp_path).equals(frame())
    assert not list((tmp_path / "context/fred").glob("*.tmp"))


def test_interrupted_provenance_publication_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_series("X", frame(), META, data_dir=tmp_path, fetched_at=NOW)
    real_replace = os.replace

    def fail_json(src: Path, dst: Path) -> None:
        if Path(dst).suffix == ".json":
            raise OSError("simulated provenance failure")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fail_json)
    with pytest.raises(OSError, match="provenance failure"):
        store_series("X", first_release(frame()), META, data_dir=tmp_path, fetched_at=NOW)
    with pytest.raises(DataError, match="sha256"):
        load_series("X", data_dir=tmp_path)


def test_pull_reports_vintages_and_replaces_series(
    key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import alpha_data.context.fred as fred

    fake = FakeTransport(
        [
            {"seriess": [{"id": "X", **META}]},
            {"count": 4, "offset": 0, "observations": observations()},
        ]
    )
    monkeypatch.setattr(fred, "FredAdapter", lambda: FredAdapter(transport=fake))
    report = fred.pull_series("X", data_dir=tmp_path, fetched_at=NOW)
    assert report["rows"] == 4 and report["vintages"] == 4
    assert report["fetched_at"] == NOW.isoformat()
    assert load_series("X", data_dir=tmp_path).equals(frame())


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "prior_end", [None, date(2024, 2, 10), date(2024, 2, 11), date(2024, 2, 12)]
)
def test_overlap_validation_with_multiple_groups(prior_end: date | None, reverse: bool) -> None:
    # Single open-ended rows are first rows, not null-ended predecessors. Both group keys matter.
    rows = [
        ("A", date(2024, 1, 1), 1.0, date(2024, 2, 1), None),
        ("X", date(2024, 1, 1), 2.0, date(2024, 2, 1), prior_end),
        ("X", date(2024, 1, 1), 3.0, date(2024, 2, 11), None),
        ("X", date(2024, 2, 1), 4.0, date(2024, 2, 1), None),
    ]
    df = pl.DataFrame(rows[::-1] if reverse else rows, schema=SCHEMA, orient="row")
    if prior_end is None or prior_end >= date(2024, 2, 11):
        with pytest.raises(DataError, match="overlapping"):
            validate(df)
    else:
        validate(df)
        assert as_known(df, as_of=date(2024, 2, 11))["value"].to_list() == [1.0, 3.0, 4.0]


def test_unsorted_gap_and_group_first_rows() -> None:
    df = expiry_frame().reverse()
    validate(df)
    assert as_known(df, as_of=date(2024, 2, 25)).is_empty()
    assert as_known(df, as_of=date(2024, 3, 5))["value"].to_list() == [3.0]
    assert as_known(df, as_of=date(2024, 3, 6)).is_empty()
    singles = pl.concat(
        [
            parse_observations("A", [observation()]),
            parse_observations("X", [observation(), observation(day="2024-02-01")]),
        ]
    ).reverse()
    validate(singles)
    assert as_known(singles, as_of=NOW.date()).height == 3


@pytest.mark.parametrize(
    "intervals",
    [
        [],
        [(1, None)],
        [(1, 1)],
        [(1, 1), (2, None)],
        [(1, 1), (3, 4)],
        [(1, 2), (2, 3)],
        [(1, 3), (2, 4)],
        [(1, None), (2, 3)],
        [(1, 1), (2, None), (3, 4)],
        [(1, 1), (2, 2), (4, None)],
    ],
)
def test_overlap_validation_matches_inclusive_interval_semantics(
    intervals: list[tuple[int, int | None]],
) -> None:
    # Independent all-pairs contract: two inclusive periods must never share a day.
    overlaps = any(
        (left_end is None or right_start <= left_end)
        and (right_end is None or left_start <= right_end)
        for index, (left_start, left_end) in enumerate(intervals)
        for right_start, right_end in intervals[index + 1 :]
    )
    rows = [
        (
            "X",
            date(2024, 1, 1),
            float(start),
            date(2024, 2, start),
            None if end is None else date(2024, 2, end),
        )
        for start, end in intervals
    ]
    for ordered_rows in (rows, rows[::-1]):
        df = pl.DataFrame(ordered_rows, schema=SCHEMA, orient="row")
        if overlaps:
            with pytest.raises(DataError, match="overlapping"):
                validate(df)
        else:
            validate(df)
            for day in range(1, 6):
                expected = [
                    float(start)
                    for start, end in intervals
                    if start <= day and (end is None or day <= end)
                ]
                assert as_known(df, as_of=date(2024, 2, day))["value"].to_list() == expected


@pytest.mark.parametrize(
    "fetched_at",
    [
        None,
        "2024-04-01T00:00:00+00:00",
        date(2024, 4, 1),
        datetime(2024, 4, 1),
        datetime(2024, 4, 1, tzinfo=timezone(timedelta(hours=1))),
    ],
)
@pytest.mark.parametrize("operation", ["pull", "store"])
def test_invalid_fetch_timestamp_before_transport_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fetched_at: Any, operation: str
) -> None:
    import alpha_data.context.fred as fred

    fake = FakeTransport([])
    monkeypatch.setattr(fred, "FredAdapter", lambda: FredAdapter(transport=fake))
    with pytest.raises(DataError, match="fetched_at must be aware UTC"):
        if operation == "pull":
            fred.pull_series("X", data_dir=tmp_path, fetched_at=fetched_at)
        else:
            store_series("X", frame(), META, data_dir=tmp_path, fetched_at=fetched_at)
    assert not fake.calls
    assert not list(tmp_path.iterdir())


def test_storage_requires_explicit_timestamp(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="fetched_at"):
        store_series("X", frame(), META, data_dir=tmp_path)  # type: ignore[call-arg]
    assert not list(tmp_path.iterdir())


def test_pull_requires_explicit_timestamp_before_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import alpha_data.context.fred as fred

    fake = FakeTransport([])
    monkeypatch.setattr(fred, "FredAdapter", lambda: FredAdapter(transport=fake))
    with pytest.raises(TypeError, match="fetched_at"):
        fred.pull_series("X", data_dir=tmp_path)  # type: ignore[call-arg]
    assert not fake.calls
    assert not list(tmp_path.iterdir())


def test_pull_passes_timestamp_date_to_fetch_and_preserves_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[date] = []
    fetched_at = datetime(1998, 12, 31, 23, 59, 59, 123456, tzinfo=UTC)

    def fetch(
        self: FredAdapter, series_id: str, *, as_of: date
    ) -> tuple[pl.DataFrame, dict[str, str]]:
        assert series_id == "X"
        calls.append(as_of)
        return frame(), META

    monkeypatch.setattr(FredAdapter, "fetch", fetch)
    first = pull_series("X", data_dir=tmp_path, fetched_at=fetched_at)
    second = pull_series("X", data_dir=tmp_path, fetched_at=fetched_at)
    assert calls == [date(1998, 12, 31), date(1998, 12, 31)]
    assert first == second
    stored = json.loads((tmp_path / "context/fred/X.json").read_text())
    assert stored == {key: value for key, value in first.items() if key != "vintages"}
    assert stored["fetched_at"] == fetched_at.isoformat()
