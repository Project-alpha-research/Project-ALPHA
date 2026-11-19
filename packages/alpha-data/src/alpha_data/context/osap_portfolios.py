"""Published long-short factor returns (Open Source Asset Pricing) as point-in-time context rows.

One stored table per release (vintage): `context/osap/portfolios/<release>.parquet`. A new release
that revises history is a new file beside the old one; nothing is overwritten. The series are
reference rows for the question "is my strategy just a known published factor?". No signal or
statistic is defined on them here.
"""

from __future__ import annotations

import io
import json
import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from alpha_core import DataError
from alpha_data.context.events import TIME, as_known_events, load_events, store_events, utc_time
from alpha_data.context.free_http import Client, check_ascending
from alpha_data.context.osap_catalogue import (
    CITATION,
    LICENSE,
    PROJECT,
    SignalDoc,
    parse_signal_doc,
    release_base,
)

SOURCE = "osap-portfolios"
FOLDER = "context/osap/portfolios"
HOSTS = ("huggingface.co", ".hf.co")
RETURNS_FILE = "Portfolios/Full%20Sets%20OP/PredictorLSretWide.parquet"
PERCENT = 100.0
UNIT_NOTE = (
    "The source states monthly returns in percent (5.0 = 5%). They are stored as decimals "
    "(0.05 = 5%): divided by 100 once, when the file is mapped."
)
KNOWN_RULE = (
    "A month's value is known from the later of two times: 12:00 UTC on the day after the month "
    "ends, and 00:00 UTC on the day after the release date of the vintage that holds the value. "
    "The release date is a required argument of the pull (the source's files carry none); every "
    "row in a vintage uses that vintage's date, because the source revises history with each "
    "annual release and a revised value was not known before it. known_basis says which time won."
)
CAVEAT = (
    "Long-short returns of the source's own portfolios of US stocks, as published in one release. "
    "Releases revise history; name the release you read. Not a claim that any factor makes money."
)
SCHEMA: dict[str, Any] = dict(
    signal=pl.String,
    month=pl.Date,
    long_short_return=pl.Float64,
    published_year=pl.Int32,
    release=pl.String,
    known_from=TIME,
    known_basis=pl.String,
)


def _check_release(release: str) -> str:
    if not re.fullmatch(r"\d{4}\.\d{2}", release):
        raise DataError("invalid release; expected the source's year.month id, e.g. 2026.10")
    return release


def table_path(data_dir: Path, release: str) -> Path:
    return data_dir / FOLDER / f"{_check_release(release)}.parquet"


def percent_to_decimal(value: float) -> float:
    """The one place a percent return becomes a decimal return."""
    return value / PERCENT


def month_end(day: date) -> date:
    """Last calendar day of the month. The source stamps each month with its last trading day."""
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def known_from(month_end: date, released: date) -> tuple[datetime, str]:
    """Later of month-end plus lag and the vintage's release date; and which one won."""
    lag = datetime.combine(month_end + timedelta(days=1), time(12), tzinfo=UTC)
    release = datetime.combine(released + timedelta(days=1), time(0), tzinfo=UTC)
    return (release, "release") if release >= lag else (lag, "month-lag")


def _wide(raw: bytes, predictors: set[str]) -> pl.DataFrame:
    try:
        wide = pl.read_parquet(io.BytesIO(raw))
    except pl.exceptions.PolarsError:
        raise DataError("long-short return file is not valid parquet") from None
    if wide.columns[:1] != ["date"] or wide.schema["date"] != pl.Date:
        raise DataError("long-short return file must start with a date column of type Date")
    unknown = [c for c in wide.columns[1:] if c not in predictors]
    if unknown:
        raise DataError("unknown column(s) in the return file: " + ", ".join(sorted(unknown)[:5]))
    for name in wide.columns[1:]:
        if wide.schema[name] != pl.Float64:
            raise DataError(f"return column {name} must be Float64")
        if not wide[name].drop_nulls().is_finite().all():
            raise DataError(f"return column {name} must be finite (no NaN or infinity)")
    months = wide["date"]
    if months.null_count():
        raise DataError("the date column has a missing month")
    if any((m + timedelta(days=7)).month == m.month for m in months.to_list()):
        raise DataError("every date must be a month end (the last trading day of its month)")
    check_ascending([month_end(m) for m in months.to_list()], "month")
    return wide


def map_returns(raw: bytes, docs: list[SignalDoc], *, release: str, released: date) -> pl.DataFrame:
    """Strictly map the wide percent file to long decimal rows with the two point-in-time layers."""
    _check_release(release)
    predictors = {d.acronym: d for d in docs if d.kind == "Predictor"}
    wide = _wide(raw, set(predictors))
    long = (
        wide.unpivot(index="date", variable_name="signal", value_name="percent")
        .drop_nulls("percent")
        .rename({"date": "month"})
        .with_columns(pl.col("month").map_elements(month_end, return_dtype=pl.Date))
    )
    if long.is_empty():
        raise DataError("the return file holds no returns")
    clock = {m: known_from(m, released) for m in long["month"].unique().to_list()}
    out = long.with_columns(
        long_short_return=pl.col("percent") / PERCENT,
        published_year=pl.col("signal").replace_strict(
            {a: d.year for a, d in predictors.items()}, return_dtype=pl.Int32
        ),
        release=pl.lit(release),
        known_from=pl.col("month").replace_strict(
            {m: t for m, (t, _) in clock.items()}, return_dtype=TIME
        ),
        known_basis=pl.col("month").replace_strict(
            {m: b for m, (_, b) in clock.items()}, return_dtype=pl.String
        ),
    )
    return out.select(list(SCHEMA)).sort(["signal", "month"]).cast(pl.Schema(SCHEMA))


def _summary(release: str, released: str | None, df: pl.DataFrame) -> dict[str, Any]:
    return dict(
        release=release,
        released=released,
        rows=df.height,
        signals=df["signal"].n_unique(),
        months=df["month"].n_unique(),
        first_month=str(df["month"].min()),
        last_month=str(df["month"].max()),
    )


def pull_portfolios(
    *,
    data_dir: Path,
    release: str,
    released: date,
    fetched_at: datetime,
    branch: str | None = None,
    client: Client | None = None,
) -> dict[str, Any]:
    """Fetch the release's signal table and long-short file; store one vintage, never overwrite."""
    utc_time(fetched_at)
    path = table_path(data_dir, release)
    if released > fetched_at.date():
        raise DataError("released date is after today; give the source's release date")
    client = client or Client()
    base = release_base(release, branch)
    urls = {"signal_doc": f"{base}/SignalDoc.csv", "long_short": f"{base}/{RETURNS_FILE}"}
    fetched: dict[str, bytes] = {}
    for key, url in urls.items():
        status, body = client.get_following(url, "Open Source Asset Pricing", HOSTS)
        if status != 200:
            raise DataError(
                f"Open Source Asset Pricing HTTP {status} for {key}; nothing was stored"
            )
        fetched[key] = body
    df = map_returns(
        fetched["long_short"],
        parse_signal_doc(fetched["signal_doc"]),
        release=release,
        released=released,
    )
    summary = {**_summary(release, released.isoformat(), df), "unit": UNIT_NOTE}
    summary["known_from_rule"] = KNOWN_RULE
    if path.exists() or path.with_suffix(".json").exists():
        stored = load_events(path, source=SOURCE, schema=SCHEMA)
        if not stored.equals(df):
            raise DataError(
                f"release {release} is already stored with different values; "
                "a revised file is a new release: pull it under its own release id"
            )
        return {**summary, "stored": "already stored, unchanged"}
    store_events(
        path,
        df,
        {
            "source": SOURCE,
            "fetched_at": fetched_at.isoformat(),
            "release": release,
            "released": released.isoformat(),
            "project": PROJECT,
            "citation": CITATION,
            "license": LICENSE,
            "files": urls,
            "unit": UNIT_NOTE,
            "known_from_rule": KNOWN_RULE,
            "caveat": CAVEAT,
        },
        schema=SCHEMA,
    )
    return {**summary, "stored": str(path)}


def _releases(data_dir: Path) -> list[str]:
    return sorted((p.stem for p in (data_dir / FOLDER).glob("*.parquet")), reverse=True)


def read_known(
    data_dir: Path, *, as_of: datetime, release: str | None = None
) -> tuple[str | None, pl.DataFrame]:
    """Rows with known_from <= as_of from one vintage, and the vintage's name.

    Without `release`, the newest stored vintage that has any row known at `as_of` is used.
    """
    utc_time(as_of)
    if release is not None:
        stored = load_events(table_path(data_dir, release), source=SOURCE, schema=SCHEMA)
        return release, as_known_events(stored, as_of=as_of)
    for name in _releases(data_dir):
        known = as_known_events(
            load_events(table_path(data_dir, name), source=SOURCE, schema=SCHEMA), as_of=as_of
        )
        if known.height:
            return name, known
    return None, pl.DataFrame(schema=SCHEMA)


def describe(data_dir: Path) -> list[dict[str, Any]]:
    """One listing row per stored vintage, read through the hash-checked loader."""
    out = []
    for name in sorted(_releases(data_dir)):
        path = table_path(data_dir, name)
        df = load_events(path, source=SOURCE, schema=SCHEMA)
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        out.append(
            {
                "source": SOURCE,
                "key": name,
                **{
                    k: v
                    for k, v in _summary(name, meta.get("released"), df).items()
                    if k != "release"
                },
                "last_known_from": df.select(pl.col("known_from").max()).item().isoformat(),
                "fetched_at": meta["fetched_at"],
                "caveat": meta["caveat"],
            }
        )
    return out
