"""Invented EDGAR responses; no network and no real declared identity."""

import json
import secrets
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Never

import polars as pl
import pytest

from alpha_core import DataError
from alpha_data.context.edgar import earnings, map_form4, map_submission_arrays, pull_edgar
from alpha_data.context.events import FILINGS_SCHEMA, as_known_events, load_events, store_events
from alpha_data.context.sec_http import SecClient

FIX = Path(__file__).parents[1] / "fixtures/context/edgar"
NOW = datetime(2024, 2, 1, tzinfo=UTC)


@pytest.fixture
def identity(monkeypatch: pytest.MonkeyPatch) -> str:
    value = f"{secrets.token_hex(8)} {secrets.token_hex(8)}@example.invalid"
    monkeypatch.setenv("ALPHA_SEC_USER_AGENT", value)
    return value


class Wire:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []
        self.now = 0.0
        self.body: dict[str, Any] = json.loads((FIX / "submissions_CIK0000000001.json").read_text())

    def clock(self) -> float:
        return self.now

    def sleep(self, delay: float) -> None:
        self.now += delay

    def __call__(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        self.calls.append((url, self.now))
        assert headers["User-Agent"] and timeout == 30
        if url.endswith("company_tickers.json"):
            raw = (FIX / "company_tickers.json").read_bytes()
        elif url.endswith("-001.json"):
            old = {key: [values[0]] for key, values in self.body["filings"]["recent"].items()}
            old.update(
                accessionNumber=["0000000001-23-000001"],
                filingDate=["2023-12-20"],
                acceptanceDateTime=["2023-12-20T16:00:00Z"],
            )
            raw = json.dumps(old).encode()
        elif "/Archives/" in url:
            assert url.endswith("/1/000000000124000002/owner.xml")
            raw = (FIX / "form4_sample.xml").read_bytes()
        else:
            raw = json.dumps(self.body).encode()
        return 200, {}, raw

    def client(self) -> SecClient:
        return SecClient(transport=self, clock=self.clock, sleep=self.sleep)


def test_pull_pages_cache_acceptance_earnings_and_provenance(tmp_path: Path, identity: str) -> None:
    wire = Wire()
    client = wire.client()
    report = pull_edgar(data_dir=tmp_path, ticker="TEST", client=client, fetched_at=NOW)
    assert report == dict(
        cik="0000000001",
        name="Synthetic issuer",
        filings=4,
        earnings_8k=2,
        insider_rows=2,
        documents_fetched=1,
        documents_cached=0,
        rejected_rows={"invalid_acceptance_timestamp": 1},
    )
    assert all(b[1] - a[1] >= 0.2 - 1e-12 for a, b in zip(wire.calls, wire.calls[1:], strict=False))
    path = tmp_path / "context/edgar/0000000001/filings.parquet"
    df = load_events(path, source="edgar", schema=FILINGS_SCHEMA)
    assert df["accepted_at"].equals(df["known_from"])
    assert earnings(df).height == 2
    assert identity not in path.with_suffix(".json").read_text()
    assert json.loads(path.with_suffix(".json").read_text())["user_agent_declared"] is True
    wire.calls.clear()
    second = pull_edgar(data_dir=tmp_path, ticker="TEST", client=client, fetched_at=NOW)
    assert second["documents_cached"] == 1 and second["documents_fetched"] == 0
    assert not any("/Archives/" in url for url, _ in wire.calls)
    assert len(wire.calls) == 3  # ticker, submissions and older page stay fresh


def test_since_and_cik_bypass(tmp_path: Path, identity: str) -> None:
    wire = Wire()
    report = pull_edgar(
        data_dir=tmp_path, cik="1", since=date(2024, 1, 1), client=wire.client(), fetched_at=NOW
    )
    assert report["filings"] == 3
    assert len(wire.calls) == 2


@pytest.mark.parametrize("value", [None, "", "missing-at space", "no-space@example.invalid"])
def test_user_agent_required_before_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("ALPHA_SEC_USER_AGENT", raising=False)
    else:
        monkeypatch.setenv("ALPHA_SEC_USER_AGENT", value)
    with pytest.raises(DataError, match="ALPHA_SEC_USER_AGENT"):
        SecClient(transport=lambda *args: pytest.fail("must not request")).get(
            "https://www.sec.gov/Archives/a.xml", data_dir=tmp_path
        )


@pytest.mark.parametrize("status", [301, 302, 403, 429, 500])
def test_status_redaction(
    identity: str, tmp_path: Path, status: int, caplog: pytest.LogCaptureFixture
) -> None:
    client = SecClient(transport=lambda *args: (status, {}, identity.encode()))
    with pytest.raises(DataError, match=f"HTTP {status}") as exc:
        client.get("https://data.sec.gov/submissions/a.json", data_dir=tmp_path)
    assert identity not in str(exc.value) + caplog.text
    if status in {403, 429}:
        assert "User-Agent" in str(exc.value) and "wait" in str(exc.value)


@pytest.mark.parametrize(
    "url", ["https://evil.invalid/a", "http://www.sec.gov/a", "https://www.sec.gov@evil.invalid/a"]
)
def test_foreign_host_refused(identity: str, tmp_path: Path, url: str) -> None:
    with pytest.raises(DataError, match="URL"):
        SecClient(transport=lambda *a: pytest.fail("no request")).get(url, data_dir=tmp_path)


def test_reflection_and_size_limit(identity: str, tmp_path: Path) -> None:
    for raw, message in [
        (identity.encode(), "identity"),
        (b"x" * (32 * 1024 * 1024 + 1), "32 MiB"),
    ]:
        with pytest.raises(DataError, match=message):
            SecClient(transport=lambda *a, payload=raw: (200, {}, payload)).get(
                "https://www.sec.gov/Archives/a.xml", data_dir=tmp_path
            )
    assert not list(tmp_path.rglob("*"))


def test_form4_and_xml_defenses() -> None:
    rows = map_form4((FIX / "form4_sample.xml").read_bytes())
    assert [row["derivative"] for row in rows] == [False, True]
    assert rows[0]["owner_cik"] == "0000000002"
    assert rows[0]["is_director"] and rows[0]["is_officer"]
    assert rows[0]["shares"] == pytest.approx(10)
    assert rows[1]["price"] is None and rows[1]["shares_after"] is None
    for raw in [b"<!DOCTYPE x><ownershipDocument/>", b'<!ENTITY x "a">', b"<broken>"]:
        with pytest.raises(DataError):
            map_form4(raw)


def test_parallel_arrays_fail_loud() -> None:
    body = json.loads((FIX / "submissions_CIK0000000001.json").read_text())
    body["filings"]["recent"]["form"].pop()
    with pytest.raises(DataError, match="arrays"):
        map_submission_arrays(body["filings"]["recent"])


def test_event_hash_schema_and_future_poison(tmp_path: Path, identity: str) -> None:
    pull_edgar(data_dir=tmp_path, cik="1", client=Wire().client(), fetched_at=NOW)
    path = tmp_path / "context/edgar/0000000001/filings.parquet"
    df = load_events(path, source="edgar", schema=FILINGS_SCHEMA)
    cutoff = datetime(2024, 1, 25, 17, tzinfo=UTC)
    poison = df.with_columns(
        pl.when(pl.col("known_from") > cutoff)
        .then(pl.lit("EXTREME"))
        .otherwise(pl.col("form"))
        .alias("form")
    )
    assert as_known_events(df, as_of=cutoff).equals(as_known_events(poison, as_of=cutoff))
    assert not df.equals(poison)  # leaky control
    for bad in [datetime(2024, 1, 1), datetime(2024, 1, 1, tzinfo=timezone(timedelta(hours=1)))]:
        with pytest.raises(DataError, match="aware UTC"):
            as_known_events(df, as_of=bad)
    with pytest.raises(DataError, match="schema"):
        store_events(
            path,
            df.drop("form"),
            {"source": "edgar", "fetched_at": NOW.isoformat()},
            schema=FILINGS_SCHEMA,
        )
    path.write_bytes(b"corrupt")
    with pytest.raises(DataError, match="sha256"):
        load_events(path, source="edgar", schema=FILINGS_SCHEMA)
    with pytest.raises(DataError, match="not found"):
        load_events(tmp_path / "absent", source="edgar", schema=FILINGS_SCHEMA)


def test_amendment_keeps_original_transactions(tmp_path: Path, identity: str) -> None:
    from alpha_data.context.events import INSIDER_SCHEMA

    wire = Wire()
    arrays = wire.body["filings"]["recent"]
    for values in arrays.values():
        values.append(values[1])
    arrays["form"][-1] = "4/A"
    arrays["accessionNumber"][-1] = "0000000001-24-000005"
    arrays["acceptanceDateTime"][-1] = "2024-01-30T17:00:00Z"

    def transport(
        url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        if "/Archives/" in url:
            return 200, {}, (FIX / "form4_sample.xml").read_bytes()
        return wire(url, headers, timeout)

    report = pull_edgar(
        data_dir=tmp_path,
        cik="1",
        fetched_at=NOW,
        client=SecClient(transport, wire.clock, wire.sleep),
    )
    assert report["insider_rows"] == 4
    df = load_events(
        tmp_path / "context/edgar/0000000001/insider.parquet", source="edgar", schema=INSIDER_SCHEMA
    )
    assert df["form"].to_list() == ["4", "4", "4/A", "4/A"]
    assert as_known_events(df, as_of=datetime(2024, 1, 29, tzinfo=UTC)).height == 2


def test_real_transport_refuses_redirect_without_network(
    tmp_path: Path, identity: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import urllib.error
    import urllib.request
    from email.message import Message
    from http.client import HTTPMessage

    handlers: list[urllib.request.HTTPRedirectHandler] = []

    class Opener:
        def open(self, request: urllib.request.Request, timeout: float) -> Never:
            raise urllib.error.HTTPError(request.full_url, 302, "redirect", Message(), io.BytesIO())

    def opener(handler: urllib.request.HTTPRedirectHandler) -> Opener:
        handlers.append(handler)
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", opener)
    with pytest.raises(DataError, match="HTTP 302"):
        SecClient().get("https://data.sec.gov/submissions/a.json", data_dir=tmp_path)
    assert (
        handlers[0].redirect_request(
            urllib.request.Request("https://data.sec.gov/submissions/a.json"),
            io.BytesIO(),
            302,
            "",
            HTTPMessage(),
            "https://evil.invalid",
        )
        is None
    )


def test_transport_exception_and_encoded_reflection(
    tmp_path: Path, identity: str, caplog: pytest.LogCaptureFixture
) -> None:
    import urllib.error

    def fail(*args: object) -> Never:
        raise urllib.error.URLError(identity)

    with pytest.raises(DataError) as exc:
        SecClient(fail).get("https://data.sec.gov/submissions/a.json", data_dir=tmp_path)
    assert identity not in str(exc.value) + caplog.text
    encoded = identity.replace("@", "&#64;").encode()
    with pytest.raises(DataError, match="identity"):
        SecClient(lambda *a: (200, {}, encoded)).get(
            "https://www.sec.gov/Archives/a.xml", data_dir=tmp_path
        )


def test_storage_null_clock_rows_source_and_atomic_failure(
    tmp_path: Path, identity: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    pull_edgar(data_dir=tmp_path, cik="1", client=Wire().client(), fetched_at=NOW)
    path = tmp_path / "context/edgar/0000000001/filings.parquet"
    df = load_events(path, source="edgar", schema=FILINGS_SCHEMA)
    meta = json.loads(path.with_suffix(".json").read_text())
    with pytest.raises(DataError, match="null"):
        store_events(
            path,
            df.with_columns(pl.lit(None, dtype=pl.Datetime("us", "UTC")).alias("known_from")),
            meta,
            schema=FILINGS_SCHEMA,
        )
    with pytest.raises(DataError, match="source"):
        load_events(path, source="wrong", schema=FILINGS_SCHEMA)
    path.with_suffix(".json").write_text(json.dumps({**meta, "rows": 999}))
    with pytest.raises(DataError, match="rows"):
        load_events(path, source="edgar", schema=FILINGS_SCHEMA)
    path.with_suffix(".json").write_text(json.dumps(meta))
    original = path.read_bytes()

    def fail(*args: object) -> Never:
        raise OSError("replace failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="replace failure"):
        store_events(path, df.head(1), meta, schema=FILINGS_SCHEMA)
    assert path.read_bytes() == original
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize("change", [{"name": None}, {"tickers": "TEST"}, {"tickers": [None]}])
def test_invalid_company_metadata_fails(change: dict[str, Any]) -> None:
    body = json.loads((FIX / "submissions_CIK0000000001.json").read_text())
    with pytest.raises(DataError):
        map_submission_arrays({**body, **change})


def test_repull_amendment_does_not_remove_original(tmp_path: Path, identity: str) -> None:
    from alpha_data.context.events import INSIDER_SCHEMA

    wire = Wire()
    pull_edgar(data_dir=tmp_path, cik="1", client=wire.client(), fetched_at=NOW)
    arrays = wire.body["filings"]["recent"]
    wire.body["filings"]["recent"] = {key: [values[1]] for key, values in arrays.items()}
    amended = wire.body["filings"]["recent"]
    amended["form"] = ["4/A"]
    amended["accessionNumber"] = ["0000000001-24-000005"]
    amended["filingDate"] = ["2024-01-30"]
    amended["acceptanceDateTime"] = ["2024-01-30T17:00:00Z"]

    def transport(
        url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        if "/Archives/" in url:
            return 200, {}, (FIX / "form4_sample.xml").read_bytes()
        return wire(url, headers, timeout)

    pull_edgar(
        data_dir=tmp_path,
        cik="1",
        since=date(2024, 1, 30),
        fetched_at=NOW,
        client=SecClient(transport, wire.clock, wire.sleep),
    )
    df = load_events(
        tmp_path / "context/edgar/0000000001/insider.parquet", source="edgar", schema=INSIDER_SCHEMA
    )
    assert df.height == 4
    assert as_known_events(df, as_of=datetime(2024, 1, 29, tzinfo=UTC)).height == 2
