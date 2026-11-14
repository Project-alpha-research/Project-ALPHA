"""Synthetic FRED/ALFRED responses and point-in-time storage checks; no network."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
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
    store_series,
)

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
    df, metadata = FredAdapter(transport=fake).fetch("X")
    assert df.equals(frame()) and metadata == META
    queries = [parse_qs(urlsplit(c[0]).query) for c in fake.calls]
    assert [q.get("offset") for q in queries] == [None, ["0"], ["2"]]
    for q in queries:
        assert q["api_key"] == [key] and q["file_type"] == ["json"]
        assert q["series_id"] == ["X"]
    assert queries[1]["realtime_start"] == ["1776-07-04"]
    assert queries[1]["realtime_end"] == ["9999-12-31"]
    assert queries[1]["limit"] == ["100000"]


def test_full_range_400_retries_five_year_windows_and_merges(key: str) -> None:
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

    df, _ = FredAdapter(transport=transport).fetch("X")
    assert df.height == 1
    assert calls[0]["realtime_start"] == "1776-07-04"
    assert calls[-1]["realtime_end"] == "9999-12-31"
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

    df, metadata = FredAdapter(transport=transport).fetch("X")
    assert metadata["point_in_time"] == "approximate"
    assert df["known_from"].to_list() == [date(2024, 3, 2), date(2024, 3, 5)]
    assert df["known_until"].to_list() == [None, None]
    assert df["value"].to_list() == [4.2, None]


@pytest.mark.parametrize("status", [200, 301, 400, 403, 429, 500])
def test_provider_errors_never_expose_key_or_url(
    key: str, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    url = f"https://api.stlouisfed.org/fred/series?api_key={key}"
    fake = FakeTransport(
        [(status, {}, json.dumps({"error_message": f"refused {url} {key}"}).encode())]
    )
    with pytest.raises(DataError, match="refused") as exc:
        FredAdapter(transport=fake).fetch("X")
    assert key not in str(exc.value) + caplog.text
    assert "https://" not in str(exc.value) + caplog.text


def test_transport_error_and_missing_key(
    monkeypatch: pytest.MonkeyPatch, key: str, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(DataError, match="transport") as exc:
        FredAdapter(transport=FakeTransport([urllib.error.URLError(key)])).fetch("X")
    assert key not in str(exc.value) + caplog.text
    monkeypatch.delenv("FRED_API_KEY")
    fake = FakeTransport([])
    with pytest.raises(DataError, match="FRED_API_KEY"):
        FredAdapter(transport=fake).fetch("X")
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
        FredAdapter(transport=FakeTransport([response])).fetch("X")


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
        FredAdapter(transport=fake).fetch("X")


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
        FredAdapter(transport=fake).fetch("X")


def test_successful_credential_reflection_is_not_stored(key: str, tmp_path: Path) -> None:
    fake = FakeTransport([{"seriess": [{"id": "X", **META, "title": key}]}])
    with pytest.raises(DataError, match="credential"):
        FredAdapter(transport=fake).fetch("X")
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
        FredAdapter().fetch("X")
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
    report = fred.pull_series("X", data_dir=tmp_path)
    assert report["rows"] == 4 and report["vintages"] == 4
    assert load_series("X", data_dir=tmp_path).equals(frame())
