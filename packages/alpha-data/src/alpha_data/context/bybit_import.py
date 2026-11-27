"""Offline, verified Bybit context imports without opening the guarded crypto store."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Final

import polars as pl

from alpha_core import DataError
from alpha_core.atomic import publish, write_text
from alpha_data.context.events import (
    FUNDING_SCHEMA,
    OPEN_INTEREST_SCHEMA,
    store_events,
    utc_time,
)
from alpha_data.crypto.contracts import (
    CryptoDatasetIdentityV1,
    CryptoQualityReportV1,
    CryptoRawReceiptV1,
    content_digest,
)

PUBLICATION_DELAY: Final = timedelta(minutes=5)
FUNDING_CADENCES: Final = frozenset({1, 2, 4, 8})
FIRST_ROW_RULE: Final = "next gap only; unknown if not 1, 2, 4 or 8 hours"
MISSED_HOURLY_RULE: Final = "a 2-hour gap after a 1-hour interval is one missed settlement"
FAMILIES: Final = frozenset({"funding", "open_interest"})


class BybitImportError(DataError):
    """One or more symbols failed; the complete report remains available to the CLI."""

    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__("; ".join(f"{s}: {error}" for s, error in report["errors"].items()))


def table_path(data_dir: Path, kind: str, symbol: str) -> Path:
    if kind not in {"funding", "open_interest"}:
        raise DataError("Bybit kind must be funding or open_interest")
    if not re.fullmatch(r"[A-Z0-9_-]{1,128}", symbol):
        raise DataError("invalid Bybit symbol")
    return data_dir / "context/bybit/linear" / kind / f"{symbol}.parquet"


def _confined(root: Path, key: object) -> Path:
    if not isinstance(key, str) or not key:
        raise DataError("invalid Bybit artifact path")
    relative = Path(key)
    if relative.is_absolute() or ".." in relative.parts or "\\" in key:
        raise DataError("invalid Bybit artifact path")
    path = root / relative
    if any(p.is_symlink() for p in [root, path, *path.parents]):
        raise DataError("Bybit source symlinks are not allowed")
    return path


def _manifest(root: Path, identity: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise DataError("invalid Bybit manifest id")
    try:
        value = json.loads(_confined(root, f"{identity}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DataError(f"unreadable Bybit manifest {identity}: {exc}") from exc
    if not isinstance(value, dict):
        raise DataError("invalid Bybit manifest object")
    body = {k: v for k, v in value.items() if k != "manifest_id"}
    if value.get("manifest_id") != identity or content_digest(body) != identity:
        raise DataError(f"Bybit manifest hash mismatch: {identity}")
    return value


def _skip(manifest: dict[str, Any], dataset: dict[str, Any]) -> str | None:
    if manifest.get("artifact_kind") != "normalized":
        return "artifact_kind"
    for key, expected in [("provider", "bybit"), ("venue", "bybit"), ("market_type", "linear")]:
        value = manifest.get(key) if key == "provider" else dataset.get(key)
        if value != expected or (key == "provider" and dataset.get(key) != expected):
            return key
    if dataset.get("family") not in FAMILIES:
        return "family"
    quality = manifest.get("quality", {})
    if not isinstance(quality, dict):
        raise DataError("invalid Bybit quality object")
    state = quality.get("state")
    return f"quality:{state}" if state != "qualified" else None


def _discover(
    root: Path,
) -> tuple[dict[str, list[dict[str, Any]]], Counter[str], dict[tuple[str, str], Counter[str]]]:
    if not root.is_dir():
        raise DataError(f"Bybit manifests not found: {root}")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped: Counter[str] = Counter()
    per_table: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for path in sorted(root.glob("*.json")):
        item = _manifest(root, path.stem)
        receipt = item.get("receipt", {})
        if not isinstance(receipt, dict):
            raise DataError("invalid Bybit receipt object")
        dataset = item.get("dataset", receipt.get("dataset", {}))
        if not isinstance(dataset, dict):
            raise DataError("invalid Bybit dataset object")
        reason = _skip(item, dataset)
        if reason is None and (root.parent / "retirements" / path.name).exists():
            reason = "retired"
        if reason:
            skipped[reason] += 1
            if dataset.get("family") in FAMILIES:
                per_table[(dataset.get("instrument", ""), dataset["family"])][reason] += 1
        else:
            symbol = CryptoDatasetIdentityV1.from_dict(dataset).instrument
            table_path(Path("."), dataset["family"], symbol)
            groups[symbol].append(item)
    return groups, skipped, per_table


def _fetch_times(root: Path, item: dict[str, Any]) -> dict[str, str | None]:
    """Raw fetch times order conflicts only; a raw manifest without a receipt has none."""
    ids = item.get("input_manifest_ids")
    if (
        not isinstance(ids, list)
        or not ids
        or any(not isinstance(identity, str) for identity in ids)
        or len(set(ids)) != len(ids)
    ):
        raise DataError("Bybit normalized manifest requires raw input_manifest_ids")
    times: dict[str, str | None] = {}
    for identity in ids:
        raw = _manifest(root, identity)
        if raw.get("artifact_kind") != "raw" or raw.get("provider") != "bybit":
            raise DataError("Bybit normalized input is not a Bybit raw manifest")
        if raw.get("receipt") is None:
            times[identity] = None
            continue
        receipt = CryptoRawReceiptV1.from_dict(raw.get("receipt"))
        if (
            receipt.dataset.to_dict() != item["dataset"]
            or raw.get("artifact_sha256") != receipt.response_sha256
            or raw.get("artifact_bytes") != receipt.response_bytes
        ):
            raise DataError("Bybit raw receipt differs from normalized identity")
        times[identity] = utc_time(receipt.fetched_at).isoformat()
    return times


def _frame(source_dir: Path, item: dict[str, Any]) -> pl.DataFrame:
    path = _confined(source_dir / "crypto-bulk", item.get("artifact_key"))
    raw = path.read_bytes()
    if type(item.get("artifact_bytes")) is not int or len(raw) != item["artifact_bytes"]:
        raise DataError(f"Bybit artifact size mismatch: {item['manifest_id']}")
    if hashlib.sha256(raw).hexdigest() != item.get("artifact_sha256"):
        raise DataError(f"Bybit artifact checksum mismatch: {item['manifest_id']}")
    quality = CryptoQualityReportV1.from_dict(item["quality"])
    if quality.dataset_sha256 != item["artifact_sha256"]:
        raise DataError("Bybit quality hash differs from artifact")
    try:
        frame = pl.read_parquet(io.BytesIO(raw))
    except pl.exceptions.PolarsError as exc:
        raise DataError("invalid Bybit normalized Parquet") from exc
    dataset = item["dataset"]
    column = "funding_rate" if dataset["family"] == "funding" else "open_interest"
    if not {"timestamp", "symbol", column} <= set(frame.columns) or frame.is_empty():
        raise DataError("invalid Bybit normalized columns or empty table")
    dtype = frame.schema["timestamp"]
    if not isinstance(dtype, pl.Datetime) or dtype.time_zone != "UTC":
        raise DataError("Bybit timestamps must be aware UTC")
    if frame.select("timestamp", "symbol", column).null_count().row(0) != (0, 0, 0):
        raise DataError("Bybit rows cannot contain nulls")
    if not frame["timestamp"].is_sorted() or frame["symbol"].unique().to_list() != [
        dataset["instrument"]
    ]:
        raise DataError("Bybit rows disordered or symbol differs from manifest")
    if not frame[column].dtype.is_numeric() or not frame[column].is_finite().all():
        raise DataError("Bybit values must be finite numbers")
    if "category" in frame.columns and frame["category"].unique().to_list() != ["linear"]:
        raise DataError("Bybit row category differs from manifest")
    if dataset["family"] == "open_interest":
        if dataset["frequency"] != "1h" or (frame[column] < 0).any():
            raise DataError("Bybit open interest must be hourly and non-negative")
        if "unit_rule" in frame.columns and frame["unit_rule"].unique().to_list() != ["base_coin"]:
            raise DataError("Bybit linear open interest must use base_coin units")
        if any(ts.minute or ts.second or ts.microsecond for ts in frame["timestamp"]):
            raise DataError("Bybit open interest timestamp must start an hour")
    if quality.row_count != frame.height:
        raise DataError("Bybit quality row count differs from artifact")
    return frame


def _latest(times: dict[str, str | None]) -> str:
    """Latest known fetch time; unknown sorts before every known time (lowest priority)."""
    return max((t for t in times.values() if t is not None), default="")


def _merge(
    source_dir: Path,
    items: list[dict[str, Any]],
    row: dict[str, Any],
) -> tuple[list[tuple[datetime, float]], dict[str, dict[str, str | None]]]:
    fetched = {
        m["manifest_id"]: _fetch_times(source_dir / "crypto-metadata/manifests", m) for m in items
    }
    ordered = sorted(items, key=lambda m: (_latest(fetched[m["manifest_id"]]), m["manifest_id"]))
    values: dict[datetime, float] = {}
    winners: dict[datetime, str] = {}
    column = "funding_rate" if row["family"] == "funding" else "open_interest"
    for item in ordered:
        if item["dataset"] != items[0]["dataset"]:
            raise DataError("Bybit manifests mix dataset identities")
        frame = _frame(source_dir, item)
        row["rows_in"] += frame.height
        row["manifests_used"].append(item["manifest_id"])
        for ts, value in frame.select("timestamp", column).iter_rows():
            if ts in values and values[ts] == value:
                row["duplicates_dropped"] += 1
            elif ts in values:
                row["conflicts"].append(
                    dict(
                        symbol=row["symbol"],
                        timestamp=ts.isoformat(),
                        previous_value=values[ts],
                        incoming_value=value,
                        previous_manifest_id=winners[ts],
                        incoming_manifest_id=item["manifest_id"],
                    )
                )
            values[ts], winners[ts] = float(value), item["manifest_id"]
    return sorted(values.items()), fetched


def _events(values: list[tuple[datetime, float]], row: dict[str, Any]) -> pl.DataFrame:
    funding = row["family"] == "funding"
    rows = []
    interval: int | None = None
    for i, (ts, value) in enumerate(values):
        if funding:
            gap = (
                (ts - values[i - 1][0]).total_seconds() / 3600
                if i
                else (values[1][0] - ts).total_seconds() / 3600
                if len(values) > 1
                else None
            )
            # A 2-hour gap inside an hourly series is one missed settlement, not a new cadence.
            if gap in FUNDING_CADENCES and not (gap == 2 and interval == 1):
                interval = int(gap)
            elif i:
                row["gaps"] += max(1, int(gap / interval) - 1) if interval and gap else 1
            rows.append(
                dict(
                    symbol=row["symbol"],
                    funding_time=ts,
                    funding_rate=value,
                    interval_hours=interval,
                    known_from=ts,
                )
            )
        else:
            if i:
                row["gaps"] += int((ts - values[i - 1][0]).total_seconds() / 3600) - 1
            rows.append(
                dict(
                    symbol=row["symbol"],
                    ts=ts,
                    open_interest=value,
                    known_from=ts + timedelta(hours=1) + PUBLICATION_DELAY,
                )
            )
    row.update(
        rows=len(rows),
        first_timestamp=values[0][0].isoformat(),
        last_timestamp=values[-1][0].isoformat(),
    )
    return pl.DataFrame(rows, schema=FUNDING_SCHEMA if funding else OPEN_INTEREST_SCHEMA)


def _publish_symbol(
    data_dir: Path, tables: list[tuple[dict[str, Any], pl.DataFrame, dict[str, Any]]]
) -> None:
    root = data_dir / "context/bybit/linear"
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".bybit-", dir=root) as temporary:
        pending = []
        for row, frame, meta in tables:
            target = table_path(data_dir, row["family"], row["symbol"])
            staged = table_path(Path(temporary), row["family"], row["symbol"])
            store_events(staged, frame, meta, schema=dict(frame.schema))
            for src, dst in [
                (staged, target),
                (staged.with_suffix(".json"), target.with_suffix(".json")),
            ]:
                dst.parent.mkdir(parents=True, exist_ok=True)
                pending.append((src, dst, dst.read_bytes() if dst.exists() else None))
        replaced: list[tuple[Path, bytes | None]] = []
        try:
            for src, dst, previous in pending:
                os.replace(src, dst)
                replaced.append((dst, previous))
        except OSError:
            for dst, previous in reversed(replaced):
                if previous is None:
                    dst.unlink()
                else:
                    publish(dst, partial(Path.write_bytes, data=previous))
            raise


def _report_row(symbol: str, family: str, skipped: Counter[str]) -> dict[str, Any]:
    return dict(
        symbol=symbol,
        family=family,
        rows_in=0,
        rows=0,
        duplicates_dropped=0,
        conflicts=[],
        gaps=0,
        first_timestamp=None,
        last_timestamp=None,
        manifests_used=[],
        manifests_skipped=dict(skipped),
        status="skipped",
    )


def import_bybit(*, source_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Import each symbol as a unit; report failures and continue independent symbols."""
    groups, skipped, per_table = _discover(source_dir / "crypto-metadata/manifests")
    report: dict[str, Any] = dict(
        source="bybit", tables=[], manifests_skipped=dict(skipped), errors={}
    )
    for symbol, items in sorted(groups.items()):
        tables = []
        symbol_rows = [
            _report_row(symbol, family, per_table[(symbol, family)])
            for family in sorted({m["dataset"]["family"] for m in items})
        ]
        report["tables"].extend(symbol_rows)
        try:
            for row in symbol_rows:
                family = row["family"]
                selected = [m for m in items if m["dataset"]["family"] == family]
                values, fetched = _merge(source_dir, selected, row)
                latest = max(_latest(times) for times in fetched.values())
                if not latest:
                    raise DataError(f"no raw receipt fetched_at for {family}")
                frame = _events(values, row)
                meta = dict(
                    source="bybit",
                    symbol=symbol,
                    kind=family,
                    market="linear",
                    source_manifest_ids=sorted(fetched),
                    source_fetched_at=fetched,
                    fetched_at=latest,
                    dataset=selected[0]["dataset"],
                    first_row_interval_rule=FIRST_ROW_RULE,
                    missed_hourly_settlement_rule=MISSED_HOURLY_RULE,
                    publication_delay_seconds=int(PUBLICATION_DELAY.total_seconds()),
                    funding_clock="settlement",
                    open_interest_clock="interval start + 1 hour + publication delay",
                    conflict_order=(
                        "latest linked raw fetched_at (unknown lowest), then manifest_id"
                    ),
                )
                tables.append((row, frame, meta))
            if sum(len(row["conflicts"]) for row in symbol_rows) > 10:
                raise DataError("more than 10 conflicts for symbol")
            _publish_symbol(data_dir, tables)
        except (DataError, OSError) as exc:
            report["errors"][symbol] = str(exc)
            for row in symbol_rows:
                row["status"] = "failed"
        else:
            for row in symbol_rows:
                row["status"] = "published"
    reported = {(row["symbol"], row["family"]) for row in report["tables"]}
    for (symbol, family), reasons in sorted(per_table.items()):
        if symbol and family and (symbol, family) not in reported:
            report["tables"].append(_report_row(symbol, family, reasons))
    report["tables"].sort(key=lambda row: (row["symbol"], row["family"]))
    write_text(
        data_dir / "context/bybit/linear/import-report.json",
        json.dumps(report, sort_keys=True, allow_nan=False, indent=2) + "\n",
    )
    if report["errors"]:
        raise BybitImportError(report)
    return report
