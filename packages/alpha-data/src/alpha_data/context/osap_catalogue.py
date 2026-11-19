"""The Open Source Asset Pricing signal table (SignalDoc.csv): strict parsing, facts only.

Source: Chen and Zimmermann, "Open Source Cross-Sectional Asset Pricing", openassetpricing.com. The
data set is licensed CC BY 4.0 (Hugging Face dataset card). Only identifiers and bibliographic and
classification facts are read here; the table's free-text columns are never read.
"""

from __future__ import annotations

import csv
import io
from typing import Literal

from pydantic import BaseModel, ConfigDict

from alpha_core import DataError

PROJECT = "Open Source Cross-Sectional Asset Pricing"
HOST = "https://huggingface.co/datasets/OpenSourceAP/CrossSection/resolve"
CITATION = "Chen and Zimmermann, Open Source Cross-Sectional Asset Pricing (openassetpricing.com)"
LICENSE = "CC BY 4.0 (dataset card on Hugging Face, OpenSourceAP/CrossSection)"
# The columns this reader uses. Any other column is ignored; a missing one fails loud.
COLUMNS = (
    "Acronym",
    "Cat.Signal",
    "Authors",
    "Year",
    "Journal",
    "Cat.Data",
    "Cat.Economic",
    "SampleStartYear",
    "SampleEndYear",
    "Acronym2",
    "Sign",
)


class SignalDoc(BaseModel):
    """One row of the signal table, reduced to facts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    acronym: str  # the source's own identifier; also the column name in its return files
    short_name: str
    kind: Literal["Predictor", "Placebo", "Drop"]
    authors: str
    year: int | None
    journal: str | None
    data_category: str
    category: str
    sample_start: int | None
    sample_end: int | None
    sign: Literal[-1, 1] | None


def release_base(release: str, branch: str | None = None) -> str:
    """Folder URL of one release on the host; branches are named per release."""
    return f"{HOST}/{branch or f'Data-Release-{release}'}"


def _whole(row: dict[str, str], column: str, *, required: bool) -> int | None:
    raw = row[column].strip()
    if not raw:
        if required:
            raise DataError(f"SignalDoc {column} is empty for {row['Acronym']!r}")
        return None
    try:
        value = float(raw)
    except ValueError:
        raise DataError(
            f"SignalDoc {column} is not a number for {row['Acronym']!r}: {raw!r}"
        ) from None
    if value != int(value):
        raise DataError(f"SignalDoc {column} is not a whole number for {row['Acronym']!r}")
    return int(value)


def _sign(row: dict[str, str]) -> Literal[-1, 1] | None:
    value = _whole(row, "Sign", required=False)
    if value is None:
        return None
    if value not in (-1, 1):
        raise DataError(f"SignalDoc Sign must be -1 or 1 for {row['Acronym']!r}, got {value}")
    return -1 if value == -1 else 1


def _kind(row: dict[str, str]) -> Literal["Predictor", "Placebo", "Drop"]:
    value = row["Cat.Signal"].strip()
    if value == "Predictor":
        return "Predictor"
    if value == "Placebo":
        return "Placebo"
    if value == "Drop":
        return "Drop"
    raise DataError(f"SignalDoc Cat.Signal {value!r} is not Predictor, Placebo or Drop")


def parse_signal_doc(raw: bytes) -> list[SignalDoc]:
    """Every row of the table; a missing column, a duplicate id or a bad number fails loud."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DataError("SignalDoc.csv is not UTF-8 text") from None
    reader = csv.DictReader(io.StringIO(text))
    missing = [name for name in COLUMNS if name not in (reader.fieldnames or [])]
    if missing:
        raise DataError("SignalDoc.csv lacks column(s): " + ", ".join(missing))
    found: list[SignalDoc] = []
    for row in reader:
        acronym = (row["Acronym"] or "").strip()
        if not acronym:
            raise DataError("SignalDoc.csv has a row without an Acronym")
        if any(d.acronym == acronym for d in found):
            raise DataError(f"SignalDoc.csv has a duplicate Acronym {acronym!r}")
        found.append(
            SignalDoc(
                acronym=acronym,
                short_name=(row["Acronym2"] or "").strip() or acronym,
                kind=_kind(row),
                authors=(row["Authors"] or "").strip(),
                year=_whole(row, "Year", required=False),
                journal=(row["Journal"] or "").strip() or None,
                data_category=(row["Cat.Data"] or "").strip(),
                category=(row["Cat.Economic"] or "").strip(),
                sample_start=_whole(row, "SampleStartYear", required=False),
                sample_end=_whole(row, "SampleEndYear", required=False),
                sign=_sign(row),
            )
        )
    if not found:
        raise DataError("SignalDoc.csv has no rows")
    return found
