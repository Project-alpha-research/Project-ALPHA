"""Offline restored-store imports, historical clocks and failure preservation."""

import hashlib
import io
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_core import DataError
from alpha_data.context import bybit_import
from alpha_data.context.binance_bulk import table_path as binance_path
from alpha_data.context.events import (
    FUNDING_SCHEMA,
    OPEN_INTEREST_SCHEMA,
    as_known_events,
    load_events,
)
from alpha_data.crypto.contracts import (
    CryptoDatasetIdentityV1,
    CryptoQualityReportV1,
    CryptoRawReceiptV1,
    content_digest,
)

START = datetime(2024, 1, 1, tzinfo=UTC)
FETCH = datetime(2026, 10, 1, tzinfo=UTC)


def manifest(root: Path, body: dict[str, Any]) -> str:
    identity = content_digest(body)
    path = root / "crypto-metadata/manifests" / f"{identity}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**body, "manifest_id": identity}))
    return identity


def source(
    root: Path,
    hours: list[int],
    *,
    family: str = "funding",
    values: list[float] | None = None,
    fetched_at: datetime = FETCH,
    symbol: str = "BTCUSDT",
    overrides: dict[str, Any] | None = None,
    with_receipt: bool = True,
) -> tuple[str, Path]:
    dataset = CryptoDatasetIdentityV1.from_dict(
        dict(
            schema_version=1,
            provider="bybit",
            venue="bybit",
            market_type="linear",
            family=family,
            instrument=symbol,
            base_asset="BTC",
            quote_asset="USDT",
            frequency="1h" if family == "open_interest" else "event",
            units="base_coin" if family == "open_interest" else "rate",
            timestamp_convention="period_start" if family == "open_interest" else "settlement",
        )
    )
    raw = b"fixture provider response"
    receipt = CryptoRawReceiptV1.create(
        dataset=dataset,
        request=(),
        fetched_at=fetched_at,
        response_sha256=hashlib.sha256(raw).hexdigest(),
        response_bytes=len(raw),
        provider_schema="fixture",
        parser_version="fixture",
        pagination=(),
        upstream_checksum=None,
    )
    raw_body: dict[str, Any] = dict(
        schema_version=1,
        artifact_kind="raw",
        provider="bybit",
        receipt=receipt.to_dict(),
        receipt_id=receipt.receipt_id,
        artifact_key="raw/fixture.json",
        artifact_sha256=hashlib.sha256(raw).hexdigest(),
        artifact_bytes=len(raw),
    )
    if not with_receipt:
        # The store also admits raw manifests whose receipt was never embedded.
        del raw_body["receipt"]
        raw_body["receipt_id"] = f"receiptless-{symbol}-{family}-{hours}-{values}"
    raw_id = manifest(root, raw_body)
    timestamps = [START + timedelta(hours=h) for h in hours]
    frame = pl.DataFrame(
        dict(
            timestamp=timestamps,
            symbol=[symbol] * len(hours),
            category=["linear"] * len(hours),
            **{
                ("funding_rate" if family == "funding" else "open_interest"): values
                if values is not None
                else [float(i + 1) for i in range(len(hours))]
            },
        )
    )
    payload = io.BytesIO()
    frame.write_parquet(payload)
    raw_bytes = payload.getvalue()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    key = f"normalized/{family}/{dataset.content_sha256}/{digest}.parquet"
    path = root / "crypto-bulk" / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw_bytes)
    quality = CryptoQualityReportV1(
        dataset_sha256=digest,
        method_version="fixture",
        state="qualified",
        failures=(),
        warnings=(),
        observed_start=min(timestamps, default=None),
        observed_end=max(timestamps, default=None),
        row_count=frame.height,
        correction_lineage=(),
    )
    body = dict(
        schema_version=1,
        artifact_kind="normalized",
        provider="bybit",
        dataset=dataset.to_dict(),
        artifact_key=key,
        artifact_sha256=digest,
        artifact_bytes=len(raw_bytes),
        quality=quality.to_dict(),
        input_manifest_ids=[raw_id],
    )
    body.update(overrides or {})
    return manifest(root, body), path


def read(data: Path, family: str = "funding", symbol: str = "BTCUSDT") -> pl.DataFrame:
    schema = FUNDING_SCHEMA if family == "funding" else OPEN_INTEREST_SCHEMA
    return load_events(bybit_import.table_path(data, family, symbol), source="bybit", schema=schema)


@pytest.mark.parametrize(
    "hours,expected,gaps",
    [
        ([0, 8, 16], [8, 8, 8], 0),
        ([0, 4, 8], [4, 4, 4], 0),
        ([0, 1, 2], [1, 1, 1], 0),
        ([0, 8, 12, 13, 16], [8, 8, 4, 1, 1], 2),
        ([0, 2, 4], [2, 2, 2], 0),
        ([0, 8, 10, 12, 20], [8, 8, 2, 2, 8], 0),
        ([0, 1, 2, 4, 5], [1, 1, 1, 1, 1], 1),
    ],
)
def test_funding_cadence_and_clocks(
    tmp_path: Path,
    hours: list[int],
    expected: list[int],
    gaps: int,
) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    identity, _ = source(src, hours)
    report = bybit_import.import_bybit(source_dir=src, data_dir=data)
    frame = read(data)
    assert frame["interval_hours"].to_list() == expected
    assert frame["known_from"].equals(frame["funding_time"])
    row = report["tables"][0]
    assert row["gaps"] == gaps and row["rows_in"] == len(hours)
    assert row["manifests_used"] == [identity]
    assert row["first_timestamp"] == START.isoformat()
    path = bybit_import.table_path(data, "funding", "BTCUSDT")
    meta = json.loads(path.with_suffix(".json").read_text())
    assert meta["source_manifest_ids"] == [identity] and meta["source"] == "bybit"
    assert meta["first_row_interval_rule"] == "next gap only; unknown if not 1, 2, 4 or 8 hours"
    assert meta["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_open_interest_future_poison_and_leaky_clock(tmp_path: Path) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    source(src, [0, 1, 4], family="open_interest")
    report = bybit_import.import_bybit(source_dir=src, data_dir=data)
    df = read(data, "open_interest")
    assert df.columns == ["symbol", "ts", "open_interest", "known_from"]
    assert df["known_from"].to_list() == [ts + timedelta(minutes=65) for ts in df["ts"]]
    assert report["tables"][0]["gaps"] == 2
    cutoff = START + timedelta(minutes=65)
    poisoned = df.with_columns(
        pl.when(pl.col("known_from") > cutoff)
        .then(1e100)
        .otherwise(pl.col("open_interest"))
        .alias("open_interest")
    )
    assert as_known_events(df, as_of=cutoff).equals(as_known_events(poisoned, as_of=cutoff))
    leaky = poisoned.with_columns(pl.col("ts").alias("known_from"))
    with pytest.raises(AssertionError):
        assert as_known_events(df, as_of=cutoff).equals(as_known_events(leaky, as_of=cutoff))
    assert as_known_events(df, as_of=cutoff - timedelta(microseconds=1)).is_empty()


def test_selection_and_skip_reasons(tmp_path: Path) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    source(src, [0, 8])
    overrides: list[dict[str, Any]] = [
        dict(provider="binance"),
        dict(artifact_kind="derived"),
        dict(quality={"state": "warning"}),
        dict(quality={"state": "quarantined"}),
    ]
    for override in overrides:
        source(src, [0, 8], overrides=override)
    # Obtain the normalized dataset rather than relying on directory order.
    normalized = [
        json.loads(p.read_text())
        for p in src.glob("crypto-metadata/manifests/*.json")
        if json.loads(p.read_text()).get("artifact_kind") == "normalized"
    ]
    original = next(
        m for m in normalized if m["provider"] == "bybit" and m["quality"]["state"] == "qualified"
    )
    for field, value in [("venue", "binance"), ("market_type", "inverse"), ("family", "trades")]:
        body = {k: v for k, v in original.items() if k != "manifest_id"}
        body["dataset"] = {**body["dataset"], field: value}
        manifest(src, body)
    report = bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert report["manifests_skipped"] == {
        "artifact_kind": 2,
        "provider": 1,
        "venue": 1,
        "market_type": 1,
        "family": 1,
        "quality:warning": 1,
        "quality:quarantined": 1,
    }
    assert read(data).height == 2


@pytest.mark.parametrize("damage", ["checksum", "size"])
def test_corruption_preserves_both_families(tmp_path: Path, damage: str) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    source(src, [0, 8])
    _, path = source(src, [0, 1], family="open_interest")
    before = path.read_bytes()
    path.write_bytes((b"X" + before[1:]) if damage == "checksum" else before + b"X")
    with pytest.raises(DataError, match=damage):
        bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert not list(data.rglob("*.parquet"))


def test_duplicates_conflicts_and_latest_fetch(tmp_path: Path) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    source(src, [0, 8, 16], values=[1.0, 2.0, 3.0])
    source(src, [0, 8, 16], values=[1.0, 20.0, 3.0], fetched_at=FETCH + timedelta(days=1))
    report = bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert read(data)["funding_rate"].to_list() == [1.0, 20.0, 3.0]
    row = report["tables"][0]
    assert row["duplicates_dropped"] == 2 and len(row["conflicts"]) == 1
    conflict = row["conflicts"][0]
    assert conflict["symbol"] == "BTCUSDT"
    assert conflict["timestamp"] == (START + timedelta(hours=8)).isoformat()
    assert (conflict["previous_value"], conflict["incoming_value"]) == (2.0, 20.0)


def test_conflict_limit_preserves_previous_symbol(tmp_path: Path) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    source(src, list(range(11)), values=[1.0] * 11)
    bybit_import.import_bybit(source_dir=src, data_dir=data)
    path = bybit_import.table_path(data, "funding", "BTCUSDT")
    before = path.read_bytes(), path.with_suffix(".json").read_bytes()
    source(src, list(range(11)), values=[2.0] * 11, fetched_at=FETCH + timedelta(days=1))
    with pytest.raises(DataError, match="conflicts"):
        bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert (path.read_bytes(), path.with_suffix(".json").read_bytes()) == before
    report = json.loads((data / "context/bybit/linear/import-report.json").read_text())
    assert len(report["tables"][0]["conflicts"]) == 11


def test_idempotence_and_atomic_publication_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    source(src, [0, 8])
    source(src, [0, 1], family="open_interest")
    bybit_import.import_bybit(source_dir=src, data_dir=data)
    before = {p: p.read_bytes() for p in data.rglob("*") if p.is_file()}
    bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert all(p.read_bytes() == raw for p, raw in before.items())
    source(src, [16, 24])
    source(src, [2, 3], family="open_interest")
    replace = os.replace
    failed = False

    def fail_once(src_path: str | Path, dst_path: str | Path) -> None:
        nonlocal failed
        if (
            Path(dst_path) == data / "context/bybit/linear/open_interest/BTCUSDT.json"
            and not failed
        ):
            assert read(data).height == 4
            failed = True
            raise OSError("injected rename failure")
        replace(src_path, dst_path)

    monkeypatch.setattr(os, "replace", fail_once)
    with pytest.raises(DataError, match="injected rename failure"):
        bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert failed
    assert all(p.read_bytes() == raw for p, raw in before.items() if p.name != "import-report.json")
    assert not list(data.rglob("*.tmp"))
    assert (
        binance_path(data, "funding", "BTCUSDT")
        == data / "context/binance/um/funding/BTCUSDT.parquet"
    )


def test_unknown_first_interval_never_uses_a_later_gap(tmp_path: Path) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    source(src, [0, 3, 7])
    bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert read(data)["interval_hours"].to_list() == [None, None, 4]


def test_one_failed_symbol_does_not_block_another(tmp_path: Path) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    _, corrupt = source(src, [0, 8])
    source(src, [0, 8], symbol="ETHUSDT")
    corrupt.write_bytes(b"corrupt")
    with pytest.raises(bybit_import.BybitImportError) as caught:
        bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert set(caught.value.report["errors"]) == {"BTCUSDT"}
    assert read(data, symbol="ETHUSDT").height == 2
    assert not bybit_import.table_path(data, "funding", "BTCUSDT").exists()


def test_skipped_only_symbol_has_a_family_report(tmp_path: Path) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    source(src, [0, 8], symbol="ETHUSDT", overrides={"quality": {"state": "warning"}})
    report = bybit_import.import_bybit(source_dir=src, data_dir=data)
    row = report["tables"][0]
    assert row["symbol"] == "ETHUSDT" and row["family"] == "funding"
    assert row["manifests_skipped"] == {"artifact_kind": 1, "quality:warning": 1}
    assert row["status"] == "skipped" and row["rows"] == 0


@pytest.mark.parametrize("mutation", ["nan", "negative", "naive", "disordered", "symbol"])
def test_invalid_normalized_rows_fail_loud(tmp_path: Path, mutation: str) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    identity, path = source(src, [0, 1], family="open_interest")
    frame = pl.read_parquet(path)
    if mutation == "nan":
        frame = frame.with_columns(pl.lit(float("nan")).alias("open_interest"))
    elif mutation == "negative":
        frame = frame.with_columns(pl.lit(-1.0).alias("open_interest"))
    elif mutation == "naive":
        frame = frame.with_columns(pl.col("timestamp").dt.replace_time_zone(None))
    elif mutation == "disordered":
        frame = frame.reverse()
    else:
        frame = frame.with_columns(pl.lit("ETHUSDT").alias("symbol"))
    frame.write_parquet(path)
    manifest_path = src / "crypto-metadata/manifests" / f"{identity}.json"
    body = json.loads(manifest_path.read_text())
    del body["manifest_id"]
    body["artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    body["artifact_bytes"] = path.stat().st_size
    body["quality"]["dataset_sha256"] = body["artifact_sha256"]
    manifest_path.unlink()
    manifest(src, body)
    with pytest.raises(DataError):
        bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert not list(data.rglob("*.parquet"))


def test_manifest_tampering_and_path_escape_fail(tmp_path: Path) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    identity, _ = source(src, [0, 8])
    path = src / "crypto-metadata/manifests" / f"{identity}.json"
    original = json.loads(path.read_text())
    path.write_text(json.dumps({**original, "artifact_key": "../escape.parquet"}))
    with pytest.raises(DataError, match="manifest hash"):
        bybit_import.import_bybit(source_dir=src, data_dir=data)
    path.unlink()
    manifest(
        src,
        {
            k: v
            for k, v in {**original, "artifact_key": "../escape.parquet"}.items()
            if k != "manifest_id"
        },
    )
    with pytest.raises(DataError, match="artifact path"):
        bybit_import.import_bybit(source_dir=src, data_dir=data)


@pytest.mark.parametrize(
    "override",
    [
        {"artifact_key": None},
        {"input_manifest_ids": [[]]},
        {"quality": None},
        {"dataset": None},
    ],
)
def test_malformed_manifest_is_a_typed_error(tmp_path: Path, override: dict[str, Any]) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    source(src, [0, 8], overrides=override)
    with pytest.raises(DataError):
        bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert not list(data.rglob("*.parquet"))


def test_corrupt_first_family_reports_both_as_failed(tmp_path: Path) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    _, corrupt = source(src, [0, 8])
    source(src, [0, 1], family="open_interest")
    corrupt.write_bytes(b"broken")
    with pytest.raises(bybit_import.BybitImportError) as caught:
        bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert [(row["family"], row["status"]) for row in caught.value.report["tables"]] == [
        ("funding", "failed"),
        ("open_interest", "failed"),
    ]


def test_receiptless_raw_input_never_wins_a_conflict(tmp_path: Path) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    dated, _ = source(src, [0, 8, 16], values=[1.0, 2.0, 3.0])
    undated, _ = source(src, [8, 16, 24], values=[20.0, 3.0, 4.0], with_receipt=False)
    report = bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert read(data)["funding_rate"].to_list() == [1.0, 2.0, 3.0, 4.0]
    row = report["tables"][0]
    assert row["manifests_used"] == [undated, dated]
    assert [(c["previous_value"], c["incoming_value"]) for c in row["conflicts"]] == [(20.0, 2.0)]
    path = bybit_import.table_path(data, "funding", "BTCUSDT")
    meta = json.loads(path.with_suffix(".json").read_text())
    assert list(meta["source_fetched_at"][undated].values()) == [None]
    assert meta["fetched_at"] == FETCH.isoformat()


def test_receiptless_inputs_alone_fail_the_symbol(tmp_path: Path) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    source(src, [0, 8], with_receipt=False)
    with pytest.raises(bybit_import.BybitImportError, match="fetched_at"):
        bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert not list(data.rglob("*.parquet"))


def test_retired_manifest_is_skipped(tmp_path: Path) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    source(src, [0, 8])
    retired, _ = source(src, [16, 24], values=[9.0, 9.0])
    record = src / "crypto-metadata/retirements" / f"{retired}.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"manifest_id": retired, "reason": "revoked_units_error"}))
    report = bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert report["manifests_skipped"]["retired"] == 1
    assert read(data)["funding_rate"].to_list() == [1.0, 2.0]


def test_report_lists_only_bybit_context_families(tmp_path: Path) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    identity, _ = source(src, [0, 8])
    original = json.loads((src / "crypto-metadata/manifests" / f"{identity}.json").read_text())
    body = {k: v for k, v in original.items() if k != "manifest_id"}
    body["dataset"] = {**body["dataset"], "family": "mark_bars"}
    manifest(src, body)
    report = bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert {row["family"] for row in report["tables"]} == {"funding"}
    assert report["manifests_skipped"]["family"] == 1


def test_a_value_that_returns_after_a_conflict_is_reported(tmp_path: Path) -> None:
    src, data = tmp_path / "source", tmp_path / "data"
    source(src, [0, 8], values=[1.0, 2.0])
    source(src, [0, 8], values=[1.0, 20.0], fetched_at=FETCH + timedelta(days=1))
    source(src, [0, 8], values=[1.0, 2.0], fetched_at=FETCH + timedelta(days=2))
    report = bybit_import.import_bybit(source_dir=src, data_dir=data)
    assert read(data)["funding_rate"].to_list() == [1.0, 2.0]
    row = report["tables"][0]
    assert [(c["previous_value"], c["incoming_value"]) for c in row["conflicts"]] == [
        (2.0, 20.0),
        (20.0, 2.0),
    ]
    assert row["duplicates_dropped"] == 2
