"""Daily screening projections over exact qualified provider-native crypto manifests.

Unlike the scalar-availability artifacts in alpha_data.crypto.features, these panels
apply the dataset's timestamp convention to every row at each daily decision cutoff.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from alpha_cli.spine import reserve
from alpha_core import DataError
from alpha_core.config import AlphaSettings
from alpha_data.crypto.contracts import (
    FAMILY_AUTHORITIES,
    CryptoDatasetIdentityV1,
    CryptoQualityReportV1,
    canonical_bytes,
)
from alpha_data.crypto.quality import QUALITY_METHOD_VERSION
from alpha_data.crypto.storage import CryptoBulkStore

FUNDING_FREQUENCY = "funding_interval"
FAMILIES = {
    "derivative_bars": ("1d", "quote_price", "interval_start_utc", "close"),
    "funding": (FUNDING_FREQUENCY, "dimensionless_rate", "provider_event_utc", "funding_rate"),
    "open_interest": (
        "1h",
        "base_coin_if_linear_quote_coin_if_inverse",
        "provider_event_utc",
        "open_interest",
    ),
}


def bulk_store(data_dir: Path) -> CryptoBulkStore:
    settings = AlphaSettings()
    if not settings.bulk_volume_uuid:
        raise DataError("crypto bulk volume UUID must be configured")
    return CryptoBulkStore(
        bulk_root=settings.bulk_data_dir,
        manifest_root=data_dir / "crypto" / "manifests",
        expected_volume_uuid=settings.bulk_volume_uuid,
    )


def _time(value: object) -> datetime:
    try:
        timestamp = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
    except ValueError as exc:
        raise DataError("crypto screening timestamp is invalid") from exc
    if (
        not isinstance(timestamp, datetime)
        or timestamp.tzinfo is None
        or timestamp.utcoffset() is None
    ):
        raise DataError("crypto screening timestamp must be timezone-aware")
    return timestamp.astimezone(UTC)


def validate_identity(manifest: Mapping[str, Any], *, previous: Mapping[str, Any] | None) -> None:
    parsed = CryptoDatasetIdentityV1.from_dict(manifest["dataset"])
    dataset = parsed.to_dict()
    if dataset != manifest["dataset"]:
        raise DataError("crypto screening dataset identity must be canonical")
    family = parsed.family
    frequency, units, convention, _column = FAMILIES[family]
    if (
        dataset.get("provider") != FAMILY_AUTHORITIES[family]
        or dataset.get("venue") != "bybit"
        or dataset.get("frequency") != frequency
        or dataset.get("units") != units
        or dataset.get("timestamp_convention") != convention
        or not dataset.get("base_asset")
        or not dataset.get("quote_asset")
    ):
        raise DataError(f"crypto screening dataset identity mismatch: {manifest['manifest_id']}")
    if previous is not None and canonical_bytes(previous["dataset"]) != canonical_bytes(dataset):
        raise DataError(
            f"crypto identity mismatch between {previous['manifest_id']} "
            f"and {manifest['manifest_id']}"
        )
    quality = CryptoQualityReportV1.from_dict(manifest["quality"])
    if (
        quality.state != "qualified"
        or quality.dataset_sha256 != manifest["artifact_sha256"]
        or quality.method_version != QUALITY_METHOD_VERSION
    ):
        raise DataError("crypto screening requires artifact-bound qualified quality")
    if quality.correction_lineage:
        raise DataError("crypto corrections lack row-level availability; screening refused")


def merge_rows(
    values: dict[datetime, float],
    frame: pl.DataFrame,
    dataset: Mapping[str, Any],
    *,
    as_of: datetime,
    row_signatures: dict[datetime, bytes] | None = None,
    before: datetime | None = None,
) -> None:
    family = dataset["family"]
    column = FAMILIES[family][3]
    required = {"timestamp", "symbol", "category", column}
    if not required.issubset(frame.columns):
        raise DataError(f"crypto {family} is missing screening columns")
    seen = set()
    for row in frame.iter_rows(named=True):
        if row["symbol"] != dataset["instrument"] or row["category"] != dataset["market_type"]:
            raise DataError("crypto screening row identity differs from manifest")
        timestamp = _time(row["timestamp"])
        if timestamp in seen:
            raise DataError("crypto screening duplicate timestamps within manifest")
        seen.add(timestamp)
        if before is not None and timestamp >= before:
            continue  # a row stamped in the held-back period is never read
        available = timestamp + timedelta(days=1) if family == "derivative_bars" else timestamp
        if available > as_of:
            continue
        if row_signatures is not None:
            signature = canonical_bytes(
                {
                    key: value.isoformat() if isinstance(value, datetime) else value
                    for key, value in row.items()
                }
            )
            if available in row_signatures and row_signatures[available] != signature:
                raise DataError(f"crypto {family} complete-row overlap disagrees")
            row_signatures[available] = signature
        value = row[column]
        if type(value) not in {int, float} or not np.isfinite(value):
            raise DataError(f"crypto {family} screening values must be finite")
        if family != "funding" and value <= 0:
            raise DataError(f"crypto {family} screening values must be positive")
        if available in values and values[available] != value:
            raise DataError(f"crypto {family} overlap disagrees at {available.isoformat()}")
        values[available] = float(value)


def capped_cutoff(options: Mapping[str, Any]) -> datetime:
    """The user's cut-off (midnight UTC), never later than the start of the held-back period."""
    user = datetime.combine(date.fromisoformat(options["as_of"]), time.min, tzinfo=UTC)
    return min(user, reserve.RESERVED_INSTANT)


def read_before_reserved(path: Path) -> tuple[int, pl.DataFrame]:
    """The artifact's full row count, and only its rows stamped before the reserved instant.

    The filter runs inside the parquet scan, so no held-back row reaches Python. A timestamp
    column that is not a datetime is left to the row check in ``merge_rows``.
    """
    try:
        lazy = pl.scan_parquet(path)
        height = int(lazy.select(pl.len()).collect().item())
        dtype = lazy.collect_schema().get("timestamp")
        if isinstance(dtype, pl.Datetime):
            stamp = pl.col("timestamp")
            if dtype.time_zone is None:
                stamp = stamp.dt.replace_time_zone("UTC")
            lazy = lazy.filter(stamp < reserve.RESERVED_INSTANT)
        return height, lazy.collect()
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise DataError("crypto screening artifact is unreadable") from exc


def held_back_rows(data_dir: Path, spec: Mapping[str, Any]) -> int:
    """Count frozen rows stamped on or after the reserved day that the user's cut-off admits.

    Only the timestamp column is read. Rows of one instrument and family that repeat across
    overlapping manifests count once.
    """
    store = bulk_store(data_dir)
    user = datetime.combine(date.fromisoformat(spec["options"]["as_of"]), time.min, tzinfo=UTC)
    stamps: dict[tuple[str, str], set[datetime]] = {}
    for frozen in spec["crypto_inputs"]:
        manifest = store.verify_manifest(frozen["manifest_id"])
        dataset = frozen["dataset"]
        family = dataset["family"]
        path = store.bulk_root / str(manifest["artifact_key"])
        try:
            column = pl.read_parquet(path, columns=["timestamp"])["timestamp"]
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise DataError("crypto screening artifact is unreadable") from exc
        bucket = stamps.setdefault((dataset["instrument"], family), set())
        for value in column.to_list():
            stamp = _time(value)
            known = stamp + timedelta(days=1) if family == "derivative_bars" else stamp
            if stamp >= reserve.RESERVED_INSTANT and known <= user:
                bucket.add(stamp)
    return sum(len(bucket) for bucket in stamps.values())


def cut_rows(data_dir: Path, frozen: Sequence[Mapping[str, Any]]) -> list[list[Any]]:
    """Every frozen row stamped before the reserved day, once, sorted: what the screen may read."""
    store = bulk_store(data_dir)
    rows: set[tuple[str, str, str, float]] = set()
    for item in frozen:
        dataset = item["dataset"]
        column = FAMILIES[dataset["family"]][3]
        path = store.bulk_root / str(store.verify_manifest(item["manifest_id"])["artifact_key"])
        frame = read_before_reserved(path)[1]
        if not {"timestamp", column}.issubset(frame.columns):
            raise DataError(f"crypto {dataset['family']} is missing screening columns")
        for stamp, value in frame.select("timestamp", column).iter_rows():
            when = _time(stamp)
            if when < reserve.RESERVED_INSTANT:
                rows.add((dataset["instrument"], dataset["family"], when.isoformat(), value))
    return [list(row) for row in sorted(rows)]


def freeze_crypto_inputs(data_dir: Path, options: Mapping[str, Any]) -> list[dict[str, Any]]:
    store = bulk_store(data_dir)
    cutoff = datetime.combine(date.fromisoformat(options["as_of"]), time.min, tzinfo=UTC)
    needed = {"derivative_bars"}
    if "funding_z_30d" in options["signals"]:
        needed.add("funding")
    if "oi_chg_7d" in options["signals"]:
        needed.add("open_interest")
    selected: list[dict[str, Any]] = []
    previous: dict[tuple[str, str], dict[str, Any]] = {}
    for manifest in store.metadata_inventory():
        dataset = manifest.get("dataset")
        quality = manifest.get("quality")
        if (
            manifest.get("artifact_kind") != "normalized"
            or not isinstance(dataset, dict)
            or not isinstance(quality, dict)
            or quality.get("state") != "qualified"
        ):
            continue
        family = dataset.get("family")
        if (
            family not in needed
            or dataset.get("instrument") not in options["symbols"]
            or dataset.get("market_type") != options["category"]
            or dataset.get("provider") != "bybit"
            or dataset.get("frequency") != FAMILIES[family][0]
        ):
            continue
        # Discovery metadata is not evidence. Verify selected bytes and raw lineage
        # before consulting availability or admitting the input to a frozen spec.
        manifest = store.verify_manifest(manifest["manifest_id"])
        input_ids = manifest.get("input_manifest_ids")
        if not isinstance(input_ids, list) or not input_ids:
            raise DataError("crypto screen manifest has no raw input lineage")
        fetched = []
        for raw_id in input_ids:
            raw = store.verify_manifest(raw_id)
            receipt = raw.get("receipt")
            if not isinstance(receipt, dict):
                raise DataError("crypto screen raw input lacks fetched_at receipt")
            fetched.append(_time(receipt.get("fetched_at")))
        if max(fetched) > cutoff:
            continue
        key = (dataset["instrument"], family)
        validate_identity(manifest, previous=previous.get(key))
        previous[key] = manifest
        selected.append(
            {
                "manifest_id": manifest["manifest_id"],
                "dataset": dataset,
                "artifact_sha256": manifest["artifact_sha256"],
            }
        )
    for symbol in options["symbols"]:
        for family in needed:
            if (symbol, family) not in previous:
                raise DataError(f"no qualified pre-cutoff {family} manifests for {symbol}")
    by_symbol: dict[str, tuple[str, str, str, str]] = {}
    for item in selected:
        dataset = item["dataset"]
        native = (
            dataset["venue"],
            dataset["market_type"],
            dataset["base_asset"],
            dataset["quote_asset"],
        )
        symbol = dataset["instrument"]
        if symbol in by_symbol and by_symbol[symbol] != native:
            raise DataError("crypto families disagree on the exact instrument identity")
        by_symbol[symbol] = native
    if len({item[-1] for item in by_symbol.values()}) != 1:
        raise DataError("crypto screening cannot combine different quote currencies")
    return sorted(selected, key=lambda item: item["manifest_id"])


def daily_signals(
    days: Sequence[datetime],
    names: Sequence[str],
    closes: np.ndarray,
    observations: Mapping[str, Mapping[str, Mapping[datetime, float]]],
    signals: Sequence[str],
) -> dict[str, np.ndarray]:
    from alpha_cli._hypothesis_scan import price_signals

    result = price_signals(closes, ["mom_30d"]) if "mom_30d" in signals else {}
    for signal in signals:
        if signal == "mom_30d":
            continue
        values = np.full(closes.shape, np.nan)
        for column, name in enumerate(names):
            family = "funding" if signal == "funding_z_30d" else "open_interest"
            events = observations[name][family]
            if family == "open_interest":
                for row, day in enumerate(days):
                    earlier = day - timedelta(days=7)
                    if day in events and earlier in events:
                        values[row, column] = events[day] / events[earlier] - 1
            else:
                grouped: dict[datetime, list[float]] = {}
                for timestamp, value in events.items():
                    end = datetime.combine(timestamp.date(), time.min, tzinfo=UTC)
                    if timestamp > end:
                        end += timedelta(days=1)
                    grouped.setdefault(end, []).append(value)
                daily: list[float] = []
                for row, day in enumerate(days):
                    items = grouped.get(day, [])
                    daily.append(float(np.mean(items)) if items else float("nan"))
                    if row >= 29:
                        window = np.asarray(daily[-30:])
                        if np.isfinite(window).all():
                            std = float(np.std(window, ddof=1))
                            if std > 0:
                                values[row, column] = (window[-1] - float(np.mean(window))) / std
        values[~np.isfinite(closes)] = np.nan
        result[signal] = values
    return {name: result[name] for name in signals}


def crypto_panel(
    data_dir: Path, spec: Mapping[str, Any]
) -> tuple[list[date], np.ndarray, dict[str, np.ndarray]]:
    options = spec["options"]
    store = bulk_store(data_dir)
    cutoff = capped_cutoff(options)
    names = options["symbols"]
    observations: dict[str, dict[str, dict[datetime, float]]] = {name: {} for name in names}
    signatures: dict[tuple[str, str], dict[datetime, bytes]] = {}
    for frozen in spec["crypto_inputs"]:
        manifest = store.verify_manifest(frozen["manifest_id"])
        if (
            manifest["dataset"] != frozen["dataset"]
            or manifest["artifact_sha256"] != frozen["artifact_sha256"]
        ):
            raise DataError("crypto frozen input identity changed")
        validate_identity(manifest, previous=None)
        dataset = frozen["dataset"]
        values = observations[dataset["instrument"]].setdefault(dataset["family"], {})
        height, frame = read_before_reserved(store.bulk_root / str(manifest["artifact_key"]))
        quality = CryptoQualityReportV1.from_dict(manifest["quality"])
        if quality.row_count != height:
            raise DataError("crypto screening quality row_count differs from artifact")
        merge_rows(
            values,
            frame,
            dataset,
            as_of=cutoff,
            row_signatures=signatures.setdefault((dataset["instrument"], dataset["family"]), {}),
            before=reserve.RESERVED_INSTANT,
        )
    observed = sorted(
        {day for families in observations.values() for day in families["derivative_bars"]}
    )
    if not observed or any(day.time() != time.min for day in observed):
        raise DataError("crypto daily bars must close at midnight UTC")
    days = [observed[0] + timedelta(days=i) for i in range((observed[-1] - observed[0]).days + 1)]
    closes = np.full((len(days), len(names)), np.nan)
    for column, name in enumerate(names):
        values = observations[name]["derivative_bars"]
        for row, day in enumerate(days):
            if day in values:
                closes[row, column] = values[day]
        present = np.flatnonzero(np.isfinite(closes[:, column]))
        if len(present) and len(present) != present[-1] - present[0] + 1:
            raise DataError(f"crypto {name} has interior daily gaps")
    return (
        [day.date() for day in days],
        closes,
        daily_signals(days, names, closes, observations, options["signals"]),
    )
