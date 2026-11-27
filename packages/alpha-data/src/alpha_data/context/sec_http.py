"""SEC fair-access transport, with immutable archive caching and identity redaction."""

from __future__ import annotations

import hashlib
import html
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from alpha_core import DataError
from alpha_core.atomic import publish, write_text
from alpha_data.context.events import cik10
from alpha_data.context.fred import _NoRedirect

_MAX_BYTES = 32 * 1024 * 1024
type Transport = Callable[[str, Mapping[str, str], float], tuple[int, Mapping[str, str], bytes]]


def _transport(
    url: str, headers: Mapping[str, str], timeout: float
) -> tuple[int, Mapping[str, str], bytes]:
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(
            urllib.request.Request(url, headers=dict(headers)), timeout=timeout
        ) as response:
            return response.status, dict(response.headers), response.read(_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, dict(exc.headers), exc.read(_MAX_BYTES + 1)


class SecClient:
    """One sequential client spaces request starts at least 0.2 seconds apart."""

    def __init__(
        self,
        transport: Transport = _transport,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport, self._clock, self._sleep = transport, clock, sleep
        self._last: float | None = None
        self.documents_fetched = 0
        self.documents_cached = 0

    def get(self, url: str, *, data_dir: Path) -> bytes:
        agent = os.environ.get("ALPHA_SEC_USER_AGENT", "").strip()
        if " " not in agent or "@" not in agent or any(ord(c) < 32 for c in agent):
            raise DataError(
                "EDGAR requires ALPHA_SEC_USER_AGENT, e.g. 'Firstname Lastname name@example.com'"
            )
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc not in {"www.sec.gov", "data.sec.gov"}
            or parsed.query
            or parsed.fragment
            or "%" in parsed.path
            or any(part in {".", ".."} for part in parsed.path.split("/"))
        ):
            raise DataError("invalid SEC URL")
        immutable = url.startswith("https://www.sec.gov/Archives/")
        cache = data_dir / "context/edgar/raw" / hashlib.sha256(url.encode()).hexdigest()
        if immutable and cache.exists():
            raw = cache.read_bytes()
            self._check_body(raw, agent)
            self.documents_cached += 1
            return raw
        if self._last is not None:
            delay = 0.2 - (self._clock() - self._last)
            if delay > 0:
                self._sleep(delay)
        self._last = self._clock()
        try:
            status, _, raw = self._transport(url, {"User-Agent": agent}, 30)
        except (ValueError, http.client.HTTPException, urllib.error.URLError, OSError) as exc:
            raise DataError(f"SEC transport failed: {type(exc).__name__}") from None
        if status != 200:
            detail = "; check the User-Agent and wait" if status in {403, 429} else ""
            raise DataError(f"SEC HTTP {status}{detail}")
        self._check_body(raw, agent)
        if immutable:
            publish(cache, lambda tmp: tmp.write_bytes(raw))
            self.documents_fetched += 1
        return raw

    @staticmethod
    def _check_body(raw: bytes, agent: str) -> None:
        if len(raw) > _MAX_BYTES:
            raise DataError("SEC response exceeds 32 MiB")
        variants = (
            agent,
            urllib.parse.quote(agent, safe=""),
            urllib.parse.quote_plus(agent),
            json.dumps(agent, ensure_ascii=True)[1:-1],
        )
        if any(value.encode() in raw for value in variants) or agent in html.unescape(
            raw.decode("utf-8", errors="replace")
        ):
            raise DataError("SEC response contains declared identity")

    def json(self, url: str, *, data_dir: Path) -> dict[str, Any]:
        raw = self.get(url, data_dir=data_dir)
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise DataError("invalid SEC JSON") from None
        if not isinstance(body, dict):
            raise DataError("SEC JSON must be an object")
        self._check_body(
            json.dumps(body, ensure_ascii=False).encode(),
            os.environ["ALPHA_SEC_USER_AGENT"].strip(),
        )
        return body


def archive_document_url(cik: str, accession: str, document: str | None) -> str:
    if document is None:
        raise DataError("Form 4 requires a primary document")
    document = re.sub(r"^xsl[^/]*/", "", document)
    if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+", document
    ):
        raise DataError("invalid SEC archive document path")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
    return f"{base}/{document}"


def resolve_company(
    data_dir: Path,
    *,
    ticker: str | None,
    cik: str | None,
    client: SecClient | None,
    mapper: Callable[[dict[str, Any]], list[dict[str, Any]]],
) -> str:
    if (ticker is None) == (cik is None):
        raise DataError("provide exactly one of --ticker or --cik")
    if cik is not None:
        return cik10(cik)
    path = data_dir / "context/edgar/company_tickers.json"
    if client is not None:
        body = client.json("https://www.sec.gov/files/company_tickers.json", data_dir=data_dir)
        records = mapper(body)
        write_text(path, json.dumps(body, sort_keys=True))
    else:
        try:
            records = mapper(json.loads(path.read_bytes()))
        except (OSError, ValueError):
            raise DataError("EDGAR ticker map not found or invalid; pull by ticker first") from None
    matches = [r["company_cik"] for r in records if r.get("company_ticker") == str(ticker).upper()]
    if len(matches) != 1:
        raise DataError("EDGAR ticker must match exactly one CIK")
    return str(matches[0])
