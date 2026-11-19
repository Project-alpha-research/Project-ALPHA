"""Import a published signal catalogue as facts-only library records (tier "imported").

The records hold identifiers, bibliographic and classification facts and nothing else. The source's
description text is never read: `idea` is a neutral label and `mechanism_claimed` says the paper
must be read. Source: Open Source Cross-Sectional Asset Pricing (CC BY 4.0); see the folder README.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from alpha_cli.spine import library
from alpha_cli.spine.errors import SpineError
from alpha_core import DataError
from alpha_data.context import osap_catalogue
from alpha_data.context.osap_catalogue import SignalDoc

SOURCES = ("osap",)
NO_TITLE = "not recorded in the source table"
NO_VENUE = "not stated in the source table"
NO_MECHANISM = "not stated here; see the paper"
BROWSER_URL = "https://openassetpricing.com/SignalDoc-Browser.html"
_DATA_NEEDED = {
    "Accounting": "company accounts (fundamentals)",
    "Price": "stock prices and returns",
    "Trading": "trading volume and liquidity",
    "Options": "options data",
    "Analyst": "analyst forecasts",
    "13F": "institutional holdings (13F filings)",
    "Event": "corporate event data",
    "Other": "other data (see the source)",
}


class Report(BaseModel):
    model_config = ConfigDict(frozen=True)

    written: int
    not_predictors: int
    removed: int
    folder: Path


def record_id(acronym: str) -> str:
    return "osap-" + re.sub(r"[^a-z0-9]+", "-", acronym.lower()).strip("-")


def _can_test(doc: SignalDoc) -> str:
    if doc.data_category == "Accounting":
        return "no - company accounts (fundamentals) are not held."
    return "unknown - the data needed is listed; it was not checked against what is held."


def make_record(doc: SignalDoc, release: str) -> library.Record:
    return library.Record(
        id=record_id(doc.acronym),
        name=doc.acronym,
        tier="imported",
        year_published=doc.year,
        market="us-equities",
        idea=f"Published signal: {doc.acronym} ({doc.category})",
        mechanism_claimed=NO_MECHANISM,
        data_needed=[
            _DATA_NEEDED.get(doc.data_category, f"{doc.data_category} data (see the source)")
        ],
        direction="long-short",
        holding_clock="months",
        decay_evidence="none recorded",
        can_test_today=_can_test(doc),
        notes=f"Facts imported from the {osap_catalogue.PROJECT} signal table, release {release}.",
        source=library.Source(
            authors=doc.authors,
            year=doc.year,
            title=NO_TITLE,
            venue=doc.journal or NO_VENUE,
            url=BROWSER_URL,
        ),
        imported=library.ImportedFacts(
            project=osap_catalogue.PROJECT,
            release=release,
            source_id=doc.acronym,
            acronym=doc.short_name,
            category=doc.category,
            data_category=doc.data_category,
            predicted_sign=doc.sign,
            sample_start=doc.sample_start,
            sample_end=doc.sample_end,
        ),
    )


def _s(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _value(value: object) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_s(str(v)) for v in value) + "]"
    return _s(value) if isinstance(value, str) else str(value)


def to_toml(record: library.Record) -> str:
    """Plain TOML in the field order of the hand-written records; null facts are left out."""
    data = record.model_dump(exclude_none=True)
    sections = {key: data.pop(key) for key in ("source", "imported")}
    lines = [f"{key} = {_value(value)}" for key, value in data.items()]
    for name, table in sections.items():
        lines += ["", f"[{name}]"] + [f"{k} = {_value(v)}" for k, v in table.items()]
    return "\n".join(lines) + "\n"


def import_osap(raw: bytes, *, release: str, dest: Path) -> Report:
    """Write one record per predictor to `dest/osap/`; remove records the release no longer has."""
    if not re.fullmatch(r"\d{4}\.\d{2}", release):
        raise SpineError(
            "LIBRARY_RELEASE",
            f"{release!r} is not a release id.",
            "Use the source's id, e.g. 2026.10.",
        )
    try:
        docs = osap_catalogue.parse_signal_doc(raw)
    except DataError as exc:
        raise SpineError(
            "LIBRARY_CATALOGUE_INVALID",
            f"The signal table cannot be read: {exc}",
            "Fetch SignalDoc.csv again from the release; nothing was written.",
        ) from exc
    predictors = [d for d in docs if d.kind == "Predictor"]
    records = {record_id(d.acronym): make_record(d, release) for d in predictors}
    if len(records) != len(predictors):
        raise SpineError(
            "LIBRARY_CATALOGUE_INVALID",
            "Two signals give the same record id.",
            "Nothing was written. Report it; the id rule needs a change.",
        )
    folder = dest / "osap"
    folder.mkdir(parents=True, exist_ok=True)
    for key, record in records.items():
        (folder / f"{key}.toml").write_text(to_toml(record), encoding="utf-8")
    stale = [p for p in folder.glob("osap-*.toml") if p.stem not in records]
    for path in stale:
        path.unlink()
    return Report(
        written=len(records),
        not_predictors=len(docs) - len(predictors),
        removed=len(stale),
        folder=folder,
    )


def load_imported(path: Path) -> library.Record:
    """Read one imported record; it must carry the imported tier."""
    record = library.load_record(path)
    if record.tier != "imported":
        raise SpineError(
            "LIBRARY_RECORD_INVALID",
            f"The library record {path.name} has tier {record.tier!r}, not 'imported'.",
            "Imported records live in research/library/imported/.",
        )
    return record
