"""CFTC Commitments of Traders (legacy, futures only) as point-in-time context rows."""

from __future__ import annotations

import json
import re
import urllib.parse
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from alpha_core import DataError
from alpha_data.context.events import TIME, load_events, store_events, utc_time
from alpha_data.context.free_http import Client, check_ascending, merge_without_revision
from alpha_data.context.us_holidays import is_us_federal_holiday

SOURCE = "cftc-cot"
DATASET = "6dca-aqww"
PAGE = 1000
NEW_YORK = ZoneInfo("America/New_York")
KNOWN_RULE = (
    "Positions are as of Tuesday. Rule time: the following Friday 15:30 US Eastern; if a US "
    "federal "
    "holiday falls Monday to Friday of that week, 15:30 US Eastern on the next weekday after that "
    "Friday that is not a holiday. The API row also carries a system stamp (:created_at) that "
    "matches live releases to the second. known_from is the later of the rule time and that stamp "
    "(known_basis 'stamp'), except when the stamp is more than 120 days after the rule time, "
    "which marks a bulk reload: then the rule time is used (known_basis 'rule'). Reports as of "
    "before 2022-09-01 carry only the bulk-reload stamp, so they use the rule time alone "
    "(known_basis 'rule-only-era')."
)
_BULK_LAG = timedelta(days=120)
RULE_ONLY_BEFORE = date(2022, 9, 1)
SCHEMA: dict[str, Any] = dict(
    market_code=pl.String,
    market_name=pl.String,
    report_date=pl.Date,
    open_interest=pl.Int64,
    noncomm_long=pl.Int64,
    noncomm_short=pl.Int64,
    noncomm_spread=pl.Int64,
    comm_long=pl.Int64,
    comm_short=pl.Int64,
    nonrept_long=pl.Int64,
    nonrept_short=pl.Int64,
    known_from=TIME,
    known_basis=pl.String,
)
# Provider field names (including its own spelling of "postions") stay here and nowhere else.
_COUNTS = {
    "open_interest": "open_interest_all",
    "noncomm_long": "noncomm_positions_long_all",
    "noncomm_short": "noncomm_positions_short_all",
    "noncomm_spread": "noncomm_postions_spread_all",
    "comm_long": "comm_positions_long_all",
    "comm_short": "comm_positions_short_all",
    "nonrept_long": "nonrept_positions_long_all",
    "nonrept_short": "nonrept_positions_short_all",
}
_CODE, _NAME, _DATE, _STAMP = (
    "cftc_contract_market_code",
    "market_and_exchange_names",
    "report_date_as_yyyy_mm_dd",
    ":created_at",
)


def table_path(data_dir: Path, market_code: str) -> Path:
    if not re.fullmatch(r"[0-9A-Z]{6}", market_code):
        raise DataError("invalid CFTC market code; expected six letters or digits, e.g. 13874A")
    return data_dir / "context/cftc/cot" / f"{market_code}.parquet"


def known_from(report_date: date) -> datetime:
    """Conservative publication time of the report for a Tuesday (or earlier-weekday) as-of date."""
    if report_date.weekday() > 3:
        raise DataError(f"CFTC report_date {report_date} is not a Monday to Thursday")
    friday = report_date + timedelta(days=4 - report_date.weekday())
    release = friday
    week = [friday - timedelta(days=n) for n in range(5)]
    if any(is_us_federal_holiday(day) for day in week):
        release += timedelta(days=1)
        while release.weekday() > 4 or is_us_federal_holiday(release):
            release += timedelta(days=1)
    local = datetime.combine(release, time(15, 30), tzinfo=NEW_YORK)
    return local.astimezone(UTC)


def _stamp(record: dict[str, Any]) -> datetime:
    raw = record.get(_STAMP)
    if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:]{8}(\.\d+)?Z", raw):
        raise DataError(f"CFTC {_STAMP} must be a UTC time like 2024-01-12T20:30:47.123Z: {raw!r}")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise DataError(f"CFTC {_STAMP} is not a real time: {raw!r}") from None


def resolve_known(rule: datetime, stamp: datetime, period: date) -> tuple[datetime, str]:
    """The later of rule time and system stamp; a stamp far after the rule is a bulk reload."""
    if period < RULE_ONLY_BEFORE:
        return rule, "rule-only-era"  # stamps before 2022-09 are one bulk-load time, not releases
    if rule < stamp <= rule + _BULK_LAG:
        return stamp, "stamp"
    return rule, "rule"


def _count(record: dict[str, Any], field: str) -> int:
    raw = record.get(field)
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]{1,15}", raw.strip()):
        raise DataError(f"CFTC {field} must be a non-negative whole number, got {raw!r}")
    return int(raw)


def _report_date(record: dict[str, Any]) -> date:
    raw = record.get(_DATE)
    if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T00:00:00\.000", raw):
        raise DataError(f"CFTC {_DATE} must look like 2024-01-02T00:00:00.000, got {raw!r}")
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        raise DataError(f"CFTC {_DATE} is not a real date: {raw!r}") from None


def map_rows(records: list[Any], market_code: str) -> pl.DataFrame:
    """Strictly map provider records for one market; any surprise is a typed error."""
    rows = []
    for record in records:
        if not isinstance(record, dict):
            raise DataError("CFTC record must be an object")
        code, name = record.get(_CODE), record.get(_NAME)
        if not isinstance(code, str) or code.strip() != market_code:
            raise DataError(f"CFTC {_CODE} {code!r} differs from requested {market_code}")
        if not isinstance(name, str) or not name.strip():
            raise DataError(f"CFTC {_NAME} must be text")
        period = _report_date(record)
        known, basis = resolve_known(known_from(period), _stamp(record), period)
        rows.append(
            dict(
                market_code=market_code,
                market_name=name.strip(),
                report_date=period,
                **{column: _count(record, field) for column, field in _COUNTS.items()},
                known_from=known,
                known_basis=basis,
            )
        )
    check_ascending([row["report_date"] for row in rows], "report_date")
    return pl.DataFrame(rows, schema=SCHEMA)


def _fetch(client: Client, market_code: str, since: date) -> list[Any]:
    records: list[Any] = []
    while True:
        query = {
            "$select": ",".join([_CODE, _NAME, _DATE, _STAMP, *_COUNTS.values()]),
            "$where": f"{_CODE}='{market_code}' AND {_DATE}>='{since}T00:00:00.000'",
            "$order": f"{_DATE} ASC",
            "$limit": str(PAGE),
            "$offset": str(len(records)),
        }
        url = f"https://publicreporting.cftc.gov/resource/{DATASET}.json?" + urllib.parse.urlencode(
            query
        )
        status, raw = client.get(url, "CFTC")
        if status != 200:
            raise DataError(f"CFTC HTTP {status}; nothing was stored")
        try:
            page = json.loads(raw)
        except ValueError:
            raise DataError("CFTC response is not JSON") from None
        if not isinstance(page, list):
            raise DataError("CFTC response must be a list of records")
        records.extend(page)
        if len(page) < PAGE:
            return records


def pull_cot(
    *,
    data_dir: Path,
    markets: list[str],
    since: date,
    fetched_at: datetime,
    client: Client | None = None,
) -> dict[str, Any]:
    """Fetch every market first, then store; one bad market stores nothing."""
    utc_time(fetched_at)
    client = client or Client()
    fetched = []
    for code in dict.fromkeys(markets):
        path = table_path(data_dir, code)
        df = map_rows(_fetch(client, code, since), code)
        if df.is_empty():
            raise DataError(f"CFTC returned no rows for {code} since {since}")
        fetched.append((code, path, df))
    results = []
    for code, path, df in fetched:
        merged = merge_without_revision(
            path, df, source=SOURCE, schema=SCHEMA, key="report_date", label=f"CFTC {code}"
        )
        store_events(
            path,
            merged,
            {
                "source": SOURCE,
                "fetched_at": fetched_at.isoformat(),
                "market_code": code,
                "dataset": f"publicreporting.cftc.gov {DATASET} (legacy, futures only)",
                "known_from_rule": KNOWN_RULE,
                "caveat": "Weekly positioning, as of Tuesday; see known_basis.",
            },
            schema=SCHEMA,
        )
        results.append(_summary(code, merged))
    return {"markets": results, "known_from_rule": KNOWN_RULE}


def _summary(code: str, df: pl.DataFrame) -> dict[str, Any]:
    return dict(
        market_code=code,
        rows=df.height,
        first_period=str(df["report_date"].min()),
        last_period=str(df["report_date"].max()),
    )


def describe(data_dir: Path) -> list[dict[str, Any]]:
    """One listing row per stored market, read through the hash-checked loader."""
    out = []
    for path in sorted((data_dir / "context/cftc/cot").glob("*.parquet")):
        df = load_events(path, source=SOURCE, schema=SCHEMA)
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        out.append(
            {
                "source": SOURCE,
                "key": path.stem,
                **{k: v for k, v in _summary(path.stem, df).items() if k != "market_code"},
                "last_known_from": df.select(pl.col("known_from").max()).item().isoformat(),
                "fetched_at": meta["fetched_at"],
                "caveat": meta["caveat"],
            }
        )
    return out
