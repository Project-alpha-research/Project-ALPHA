"""FRED/ALFRED keyed HTTP acquisition; vintage rows never enter the bar pipeline."""

from __future__ import annotations

import http.client
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_data.context.views import (
    SCHEMA,
    metadata_fields,
    series_path,
    validate,
    validate_fetched_at,
)
from alpha_data.context.views import (
    as_known as as_known,
)
from alpha_data.context.views import (
    first_release as first_release,
)
from alpha_data.context.views import (
    latest as latest,
)
from alpha_data.context.views import (
    load_series as load_series,
)
from alpha_data.context.views import (
    store_series as store_series,
)

DEFAULT_SERIES = {
    "DFF": "Fed funds rate",
    "DGS2": "Two-year Treasury yield",
    "DGS10": "Ten-year Treasury yield",
    "T10Y2Y": "Ten-year minus two-year Treasury slope",
    "T10Y3M": "Ten-year minus three-month Treasury slope",
    "CPIAUCSL": "Consumer price inflation",
    "CPILFESL": "Consumer price inflation excluding food and energy",
    "UNRATE": "Unemployment rate",
    "PAYEMS": "Nonfarm payroll jobs",
    "ICSA": "Initial unemployment claims",
    "INDPRO": "Industrial production",
    "BAMLH0A0HYM2": "High-yield credit spread",
    "VIXCLS": "VIX volatility index",
    "DTWEXBGS": "Broad US dollar index",
    "WALCL": "Federal Reserve balance sheet",
    "NFCI": "National financial conditions index",
    "M2SL": "M2 money supply",
    "DCOILWTICO": "West Texas Intermediate oil price",
}
_HOST = "https://api.stlouisfed.org/fred/series"
_MAX_BYTES = 64 * 1024 * 1024
_START, _END = date(1776, 7, 4), date(9999, 12, 31)
type Transport = Callable[[str, Mapping[str, str], float], tuple[int, Mapping[str, str], bytes]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def _transport(
    url: str, headers: Mapping[str, str], timeout: float
) -> tuple[int, Mapping[str, str], bytes]:
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(
            urllib.request.Request(url, headers=dict(headers)), timeout=timeout
        ) as response:
            return response.status, dict(response.headers), response.read(_MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, dict(error.headers), error.read(_MAX_BYTES + 1)


class _HTTPError(DataError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


def _date(raw: object) -> date:
    if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise DataError("FRED dates must be YYYY-MM-DD")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise DataError("FRED returned an invalid date") from None


def parse_observations(series_id: str, observations: list[Any]) -> pl.DataFrame:
    """Strictly parse provider vintage rows; identical window duplicates count once."""
    series_path(series_id, Path("."))
    rows = []
    for row in observations:
        if not isinstance(row, dict) or not isinstance(row.get("value"), str):
            raise DataError("FRED observation requires an object with a string value")
        try:
            value = None if row["value"] == "." else float(row["value"])
        except ValueError:
            raise DataError("FRED value must be numeric or '.'") from None
        if value is not None and not math.isfinite(value):
            raise DataError("FRED value must be finite")
        until = _date(row.get("realtime_end"))
        rows.append(
            (
                series_id,
                _date(row.get("date")),
                value,
                _date(row.get("realtime_start")),
                None if until == _END else until,
            )
        )
    df = pl.DataFrame(rows, schema=SCHEMA, orient="row").unique().sort("obs_date", "known_from")
    validate(df)
    return df


_NO_VINTAGES = "does not exist in ALFRED"


class FredAdapter:
    """Environment-only credentials; injected transport for offline response tests."""

    def __init__(self, *, transport: Transport = _transport) -> None:
        self._transport = transport

    def _request(self, path: str, query: dict[str, str], key: str) -> dict[str, Any]:
        url = (
            _HOST
            + path
            + "?"
            + urllib.parse.urlencode({**query, "api_key": key, "file_type": "json"})
        )
        try:
            status, _, raw = self._transport(
                url, {"Accept": "application/json", "User-Agent": "Project-ALPHA/1.0"}, 30
            )
        except (ValueError, http.client.HTTPException, urllib.error.URLError, OSError) as exc:
            raise DataError(f"FRED transport failed: {type(exc).__name__}") from None
        if len(raw) > _MAX_BYTES:
            raise DataError("FRED response exceeds 64 MiB")
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise _HTTPError(status, f"FRED HTTP {status}: invalid JSON") from None
        if not isinstance(body, dict):
            raise DataError("FRED JSON must be an object")
        message = body.get("error_message")
        if status != 200 or message is not None:
            detail = message if isinstance(message, str) else "no provider error_message"
            detail = re.sub(r"https?://\S+", "[redacted URL]", detail)
            for secret in (key, urllib.parse.quote(key, safe=""), urllib.parse.quote_plus(key)):
                detail = detail.replace(secret, "[redacted]")
            raise _HTTPError(status, f"FRED HTTP {status}: {detail[:500]}")
        # Never persist credential reflection, including escaped JSON or percent encoding.
        decoded = json.dumps(body, ensure_ascii=False)
        if any(secret in decoded for secret in (key, urllib.parse.quote_plus(key))):
            raise DataError("FRED response contains a credential")
        return body

    def _pages(self, series_id: str, key: str, start: date | None, end: date | None) -> list[Any]:
        """All pages for one real-time window; ``start is None`` asks for current values only."""
        offset, total = 0, None
        rows: list[Any] = []
        window = {} if start is None else {"realtime_start": str(start), "realtime_end": str(end)}
        while total is None or offset < total:
            body = self._request(
                "/observations",
                {"series_id": series_id, **window, "limit": "100000", "offset": str(offset)},
                key,
            )
            count, page = body.get("count"), body.get("observations")
            if (
                type(count) is not int
                or count < 0
                or type(body.get("offset")) is not int
                or body.get("offset") != offset
                or not isinstance(page, list)
                or len(page) > 100000
                or (total is not None and count != total)
                or offset + len(page) > count
                or (not page and offset < count)
            ):
                raise DataError("invalid FRED pagination count, offset or observations")
            total = count
            rows.extend(page)
            offset += len(page)
        return rows

    def fetch(self, series_id: str, *, as_of: date) -> tuple[pl.DataFrame, dict[str, str]]:
        key = os.environ.get("FRED_API_KEY", "").strip()
        if not key:
            raise DataError("FRED requires FRED_API_KEY in the environment")
        series_path(series_id, Path("."))
        body = self._request("", {"series_id": series_id}, key)
        entries = body.get("seriess")
        if (
            not isinstance(entries, list)
            or len(entries) != 1
            or not isinstance(entries[0], dict)
            or entries[0].get("id") != series_id
        ):
            raise DataError("FRED series response must contain one matching entry in 'seriess'")
        metadata = metadata_fields(entries[0])
        try:
            try:
                rows = self._pages(series_id, key, _START, _END)
            except _HTTPError as exc:
                if exc.status != 400 or _NO_VINTAGES in str(exc):
                    raise
                rows = self._windowed_rows(series_id, key, as_of=as_of)
        except _HTTPError as exc:
            if exc.status != 400 or _NO_VINTAGES not in str(exc):
                raise
            rows = self._current_rows(series_id, key)
            metadata["point_in_time"] = "approximate"
        df = parse_observations(series_id, rows)
        if df.is_empty():
            raise DataError("FRED returned no observations")
        return df, metadata

    def _windowed_rows(self, series_id: str, key: str, *, as_of: date) -> list[Any]:
        """Five-year windows through the year after as_of, plus early and open-ended tails."""
        rows = self._pages(series_id, key, _START, date(1919, 12, 31))
        years = list(range(1920, max(1921, min(10000, as_of.year + 2)), 5))
        for year in years:
            end = _END if year == years[-1] else date(year + 4, 12, 31)
            rows.extend(self._pages(series_id, key, date(year, 1, 1), end))
        return rows

    def _current_rows(self, series_id: str, key: str) -> list[Any]:
        """A series with no vintage history: each value counts as known the day after its date."""
        rows = []
        for row in self._pages(series_id, key, None, None):
            if not isinstance(row, dict):
                raise DataError("FRED observation requires an object with a string value")
            known = _date(row.get("date")) + timedelta(days=1)
            rows.append({**row, "realtime_start": str(known), "realtime_end": str(_END)})
        return rows


def pull_series(series_id: str, *, data_dir: Path, fetched_at: datetime) -> dict[str, Any]:
    """Fetch and replace one stored series; report distinct publication dates as vintages."""
    validate_fetched_at(fetched_at)
    df, metadata = FredAdapter().fetch(series_id, as_of=fetched_at.date())
    provenance = store_series(series_id, df, metadata, data_dir=data_dir, fetched_at=fetched_at)
    return {**provenance, "vintages": df["known_from"].n_unique()}
