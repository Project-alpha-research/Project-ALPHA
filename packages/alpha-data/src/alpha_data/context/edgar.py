"""SEC filings and Form 4 transactions as accepted, using documented synthetic formats."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_data.context import events as ev
from alpha_data.context.sec_http import SecClient, archive_document_url, resolve_company


def map_submission_arrays(arrays: dict[str, Any]) -> list[dict[str, Any]]:
    """Map SEC arrays, envelopes and ticker maps here only; rejected clocks stay explicit."""
    try:
        if "filings" in arrays:
            if (
                not isinstance(arrays["name"], str)
                or not arrays["name"]
                or not isinstance(arrays["tickers"], list)
                or any(not isinstance(t, str) or not t for t in arrays["tickers"])
            ):
                raise DataError("invalid SEC company metadata")
            company = {
                "company_cik": ev.cik10(arrays["cik"]),
                "company_name": arrays["name"],
                "company_tickers": arrays["tickers"],
            }
            pages = [
                {"page": p["name"], "through": ev.day(p["filingTo"])}
                for p in arrays["filings"]["files"]
            ]
            return [company, *pages, *map_submission_arrays(arrays["filings"]["recent"])]
        if arrays and all(key.isdigit() for key in arrays):
            return [
                {
                    "company_cik": ev.cik10(v["cik_str"]),
                    "company_ticker": v["ticker"],
                    "company_name": v["title"],
                }
                for v in arrays.values()
            ]
        fields = dict(
            accession="accessionNumber",
            filing_date="filingDate",
            report_date="reportDate",
            accepted_at="acceptanceDateTime",
            form="form",
            items="items",
            primary_document="primaryDocument",
        )
        columns = [arrays[field] for field in fields.values()]
        if any(not isinstance(c, list) for c in columns) or len({len(c) for c in columns}) != 1:
            raise DataError("invalid SEC parallel arrays")
        result = []
        for values in zip(*columns, strict=True):
            row = dict(zip(fields, values, strict=True))
            try:
                accepted = ev.utc_time(datetime.fromisoformat(row["accepted_at"]))
            except (TypeError, ValueError, DataError):
                result.append({"rejected": "invalid_acceptance_timestamp"})
                continue
            if not isinstance(row["accession"], str) or not re.fullmatch(
                r"[0-9]{10}-[0-9]{2}-[0-9]{6}", row["accession"]
            ):
                raise DataError("invalid SEC accession")
            if not isinstance(row["form"], str) or not row["form"]:
                raise DataError("invalid SEC form")
            row.update(
                filing_date=ev.day(row["filing_date"]),
                report_date=ev.day(row["report_date"]) if row["report_date"] else None,
                accepted_at=accepted,
                known_from=accepted,
            )
            for key in ("items", "primary_document"):
                if row[key] is not None and not isinstance(row[key], str):
                    raise DataError("invalid SEC optional text")
                row[key] = row[key] or None
            result.append(row)
        return result
    except (KeyError, TypeError, AttributeError):
        raise DataError("invalid SEC submission arrays or envelope") from None


def map_form4(xml_bytes: bytes) -> list[dict[str, Any]]:
    """Map each transaction for each reporting owner; reject DTDs before XML parsing."""
    if b"\x00" in xml_bytes or re.search(rb"<!DOCTYPE|<!ENTITY", xml_bytes, re.I):
        raise DataError("SEC XML DOCTYPE or ENTITY is forbidden")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        raise DataError("invalid SEC Form 4 XML") from None
    if root.tag != "ownershipDocument" or not root.findall("reportingOwner"):
        raise DataError("Form 4 requires ownershipDocument and reporting owners")
    rows = []
    for owner in root.findall("reportingOwner"):
        identity: dict[str, Any] = {
            "owner_cik": ev.cik10(owner.findtext("reportingOwnerId/rptOwnerCik")),
            "owner_name": owner.findtext("reportingOwnerId/rptOwnerName"),
            "officer_title": owner.findtext("reportingOwnerRelationship/officerTitle") or None,
        }
        if not identity["owner_name"]:
            raise DataError("Form 4 requires owner name")
        for key, field in (
            ("is_director", "isDirector"),
            ("is_officer", "isOfficer"),
            ("is_ten_percent", "isTenPercentOwner"),
        ):
            flag = owner.findtext(f"reportingOwnerRelationship/{field}")
            if flag not in {"0", "1", "false", "true"}:
                raise DataError("invalid Form 4 relationship boolean")
            identity[key] = flag in {"1", "true"}
        for derivative, path in (
            (False, "nonDerivativeTable/nonDerivativeTransaction"),
            (True, "derivativeTable/derivativeTransaction"),
        ):
            for transaction in root.findall(path):
                row: dict[str, Any] = {**identity, "derivative": derivative}
                for key, field in (
                    ("security_title", "securityTitle/value"),
                    ("transaction_date", "transactionDate/value"),
                    ("code", "transactionCoding/transactionCode"),
                    (
                        "acquired_disposed",
                        "transactionAmounts/transactionAcquiredDisposedCode/value",
                    ),
                ):
                    row[key] = transaction.findtext(field)
                    if not row[key]:
                        raise DataError("Form 4 transaction requires identity and date")
                row["transaction_date"] = ev.day(row["transaction_date"])
                if row["acquired_disposed"] not in {"A", "D"}:
                    raise DataError("invalid Form 4 acquired/disposed code")
                for key, field in (
                    ("shares", "transactionAmounts/transactionShares/value"),
                    ("price", "transactionAmounts/transactionPricePerShare/value"),
                    (
                        "shares_after",
                        "postTransactionAmounts/sharesOwnedFollowingTransaction/value",
                    ),
                ):
                    row[key] = ev.number(transaction.findtext(field), nullable=key != "shares")
                rows.append(row)
    return rows


def resolve_cik(
    data_dir: Path, *, ticker: str | None, cik: str | None, client: SecClient | None = None
) -> str:
    return resolve_company(
        data_dir, ticker=ticker, cik=cik, client=client, mapper=map_submission_arrays
    )


def earnings(df: pl.DataFrame) -> pl.DataFrame:
    items = pl.col("items").str.split(",").list.eval(pl.element().str.strip_chars())
    return df.filter(pl.col("form").is_in(["8-K", "8-K/A"]) & items.list.contains("2.02"))


def pull_edgar(
    *,
    data_dir: Path,
    fetched_at: datetime,
    ticker: str | None = None,
    cik: str | None = None,
    forms: str = "4,8-K",
    since: date = date(2016, 1, 1),
    client: SecClient | None = None,
) -> dict[str, Any]:
    ev.utc_time(fetched_at)
    client = client or SecClient()
    selected = set(forms.split(","))
    if not selected or any(not re.fullmatch(r"[A-Za-z0-9/-]+", f) for f in selected):
        raise DataError("invalid SEC forms")
    selected |= {f + "/A" for f in selected if not f.endswith("/A")}
    identifier = resolve_cik(data_dir, ticker=ticker, cik=cik, client=client)
    root = "https://data.sec.gov/submissions/"
    mapped = map_submission_arrays(client.json(f"{root}CIK{identifier}.json", data_dir=data_dir))
    company = mapped.pop(0)
    if company.get("company_cik") != identifier:
        raise DataError("SEC submissions CIK differs from requested CIK")
    pages = [row for row in mapped if "page" in row]
    rows = [row for row in mapped if "page" not in row]
    for page in pages:
        if page["through"] < since:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.json", page["page"]):
            raise DataError("invalid SEC older page name")
        rows.extend(map_submission_arrays(client.json(root + page["page"], data_dir=data_dir)))
    rejected = Counter(row["rejected"] for row in rows if "rejected" in row)
    filings = [
        {
            "cik": identifier,
            "ticker": str(ticker).upper() if ticker else next(iter(company["company_tickers"]), ""),
            **row,
        }
        for row in rows
        if "rejected" not in row and row["form"] in selected and row["filing_date"] >= since
    ]
    df = (
        pl.DataFrame(filings, schema=ev.FILINGS_SCHEMA)
        .unique(maintain_order=True)
        .sort("accepted_at", "accession")
    )
    if df["accession"].is_duplicated().any():
        raise DataError("conflicting SEC accession")
    insiders: list[dict[str, Any]] = []
    fetched, cached = client.documents_fetched, client.documents_cached
    for row in df.iter_rows(named=True):
        if row["form"] in {"4", "4/A"}:
            raw = client.get(
                archive_document_url(identifier, row["accession"], row["primary_document"]),
                data_dir=data_dir,
            )
            insiders.extend(
                {**{k: row[k] for k in ("cik", "accession", "form", "known_from")}, **r}
                for r in map_form4(raw)
            )
    insider = pl.DataFrame(insiders, schema=ev.INSIDER_SCHEMA)
    provenance = {
        "source": "edgar",
        "fetched_at": fetched_at.isoformat(),
        "cik": identifier,
        "user_agent_declared": True,
    }
    directory = data_dir / "context/edgar" / identifier
    df = ev.retain_partitions(directory / "filings.parquet", df, source="edgar", key="accession")
    insider = ev.retain_partitions(
        directory / "insider.parquet", insider, source="edgar", key="accession"
    )
    ev.store_events(directory / "filings.parquet", df, provenance, schema=ev.FILINGS_SCHEMA)
    ev.store_events(directory / "insider.parquet", insider, provenance, schema=ev.INSIDER_SCHEMA)
    return dict(
        cik=identifier,
        name=company["company_name"],
        filings=df.height,
        earnings_8k=earnings(df).height,
        insider_rows=insider.height,
        documents_fetched=client.documents_fetched - fetched,
        documents_cached=client.documents_cached - cached,
        rejected_rows=dict(rejected),
    )
