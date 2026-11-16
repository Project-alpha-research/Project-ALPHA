"""Deterministic operation counts and byte parity for command-local backfill state."""

from __future__ import annotations

import hashlib
import io
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, TypedDict
from unittest.mock import patch

import polars as pl
import pytest

from alpha_cli import crypto_data_cmds as cmds
from alpha_cli._crypto_acquisition import AcquisitionPlan
from alpha_cli._crypto_backfill import Ledger, run_backfill
from alpha_core import DataError
from alpha_data.crypto.contracts import CryptoDatasetIdentityV1, CryptoRawReceiptV1, canonical_bytes
from alpha_data.crypto.storage import Capacity, CryptoBulkStore

NOW = datetime(2026, 11, 1, tzinfo=UTC)
DATASET = CryptoDatasetIdentityV1(
    provider="binance",
    venue="binance",
    market_type="spot",
    family="market_bars",
    instrument="BTCUSDT",
    base_asset="BTC",
    quote_asset="USDT",
    frequency="1d",
    units="provider_native_ohlcv",
    timestamp_convention="interval_start_utc",
)


class _Scope(TypedDict):
    provider: str
    family: str
    category: str
    frequency: str


def _store(root: Path) -> CryptoBulkStore:
    bulk = root / "bulk"
    bulk.mkdir(parents=True, exist_ok=True)
    return CryptoBulkStore(
        bulk_root=bulk,
        manifest_root=root / "manifests",
        expected_volume_uuid="TEST",
        volume_uuid=lambda _: "TEST",
        capacity=lambda _: Capacity(2_000_000, 1_000_000),
        minimum_free_bytes=100,
    )


def _frame(payload: bytes) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "open_time": [datetime(2024, int(payload.decode().split(":")[0]), 1, tzinfo=UTC)],
            "open": [1.0],
            "high": [2.0],
            "low": [1.0],
            "close": [float(payload[-1:])],
            "volume": [3.0],
        }
    )


def _fetched(period: str, revision: int = 1) -> cmds._FetchedAcquisition:
    return cmds._FetchedAcquisition(
        plan=AcquisitionPlan(
            endpoint="archive",
            params={"period": period},
            dataset=DATASET,
            parser=_frame,
            observed_column="open_time",
            key_columns=("open_time",),
        ),
        payload=f"{int(period[-2:])}:{revision}".encode(),
        provider_schema="fake-archive-v1",
        parser_version="fake-v1",
        logical_name="archive.bin",
        upstream_checksum="a" * 64,
    )


def _provider(monkeypatch: pytest.MonkeyPatch, store: CryptoBulkStore) -> None:
    def fetch(*args: Any, **kwargs: Any) -> cmds._FetchedAcquisition:
        return _fetched(kwargs["period"])

    monkeypatch.setattr(cmds, "_bulk_store", lambda: store)
    monkeypatch.setattr(cmds, "_now", lambda: NOW)
    monkeypatch.setattr(cmds, "_fetch_non_bybit", fetch)


def _acquire(period: str = "2024-01") -> dict[str, object]:
    return cmds._backfill_acquire(
        "binance",
        "market_bars",
        "BTCUSDT",
        base="BTC",
        quote="USDT",
        category="spot",
        frequency="1d",
        period=period,
        start=None,
        end=None,
    )


def _seed(store: CryptoBulkStore, count: int) -> None:
    for number in range(count):
        payload = b"seed"
        receipt = CryptoRawReceiptV1.create(
            dataset=DATASET,
            request=(("seed", str(number)),),
            fetched_at=NOW,
            response_sha256=hashlib.sha256(payload).hexdigest(),
            response_bytes=len(payload),
            provider_schema="fake-archive-v1",
            parser_version="fake-v1",
            pagination=(),
            upstream_checksum=None,
        )
        key = f"raw/binance/{receipt.receipt_id}/archive.bin"
        path = store.bulk_root / key
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
        store._publish_manifest(
            {
                "schema_version": 1,
                "artifact_kind": "raw",
                "artifact_key": key,
                "artifact_sha256": receipt.response_sha256,
                "artifact_bytes": len(payload),
                "provider": "binance",
                "receipt_id": receipt.receipt_id,
                "receipt": receipt.to_dict(),
            }
        )


@contextmanager
def _counts(store: CryptoBulkStore) -> Iterator[dict[str, int]]:
    counts = {
        "manifest_opens": 0,
        "manifest_parses": 0,
        "listings": 0,
        "free_space": 0,
        "hashes": 0,
        "artifact_hashes": 0,
    }
    original_open, original_loads, original_scandir = Path.open, json.loads, os.scandir
    original_capacity = store._capacity
    from alpha_data.crypto import storage

    original_hash = storage.sha256_file

    def opened(path: Path, *args: Any, **kwargs: Any) -> Any:
        mode = args[0] if args else kwargs.get("mode", "r")
        if path.parent == store.manifest_root and "r" in mode:
            counts["manifest_opens"] += 1
        return original_open(path, *args, **kwargs)

    def parsed(value: Any, *args: Any, **kwargs: Any) -> Any:
        result = original_loads(value, *args, **kwargs)
        if isinstance(result, dict) and "manifest_id" in result:
            counts["manifest_parses"] += 1
        return result

    def listed(*args: Any, **kwargs: Any) -> Any:
        counts["listings"] += 1
        return original_scandir(*args, **kwargs)

    def capacity(path: Path) -> Capacity:
        counts["free_space"] += 1
        return original_capacity(path)

    def file_hash(path: Path) -> str:
        counts["artifact_hashes"] += 1
        return original_hash(path)

    with (
        patch.object(Path, "open", opened),
        patch.object(json, "loads", parsed),
        patch.object(os, "scandir", listed),
        patch.object(store, "_capacity", capacity),
        patch.object(storage, "sha256_file", file_hash),
        patch.object(hashlib, "sha256", wraps=hashlib.sha256) as hashes,
    ):
        yield counts
        counts["hashes"] = hashes.call_count


def _prime(store: CryptoBulkStore) -> None:
    # Command startup may discover metadata once; each subsequent acquire must be bounded.
    cmds._stable_resource_revision_lineage(
        store,
        dataset=DATASET,
        request=(("period", "unused"),),
        response_sha256="0" * 64,
    )


def test_acquire_operation_counts_do_not_grow_with_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    measured: dict[int, dict[str, int]] = {}
    for size in (100, 1000, 5000):
        store = _store(tmp_path / str(size))
        _seed(store, size)
        _provider(monkeypatch, store)
        _prime(store)
        with _counts(store) as counts:
            result = _acquire()
        assert result["state"] == "qualified"
        measured[size] = counts.copy()
    print("ACQUIRE_COUNTS", json.dumps(measured, sort_keys=True))
    assert measured[100] == measured[1000] == measured[5000]
    assert measured[100]["free_space"] == 3
    assert measured[100]["artifact_hashes"] >= 2


def test_three_step_backfill_counts_and_progress_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    _seed(store, 100)
    _provider(monkeypatch, store)
    _prime(store)
    steps: list[dict[str, int]] = []
    path = tmp_path / "progress.json"
    sizes: list[int] = []

    def acquire(*args: Any, **kwargs: Any) -> dict[str, object]:
        with _counts(store) as counts:
            result = cmds._backfill_acquire(*args, **kwargs)
        steps.append(counts.copy())
        return result

    def logged(message: str) -> None:
        sizes.append(path.stat().st_size)

    with patch.object(Ledger, "_read_raw", wraps=Ledger._read_raw) as reads:
        summary = run_backfill(
            provider="binance",
            family="market_bars",
            symbols=["BTCUSDT"],
            quote="USDT",
            category="spot",
            frequency="1d",
            start=date(2024, 1, 1),
            end=date(2024, 4, 1),
            ledger_path=path,
            acquire=acquire,
            now=NOW,
            pause_seconds=0,
            log=logged,
        )
    print("BACKFILL_COUNTS", steps, "PROGRESS_BYTES", sizes, "PROGRESS_READS", reads.call_count)
    assert summary["done"] == 3
    assert steps[0] == steps[1] == steps[2]
    assert reads.call_count == 1
    assert len(json.loads(path.read_bytes())["windows"]) == 3


def _golden() -> dict[str, bytes]:
    expected: dict[str, bytes] = {}
    for period in ("2024-01", "2024-02", "2024-03"):
        fetched = _fetched(period)
        receipt = CryptoRawReceiptV1.create(
            dataset=DATASET,
            request=(("period", period),),
            fetched_at=NOW,
            response_sha256=hashlib.sha256(fetched.payload).hexdigest(),
            response_bytes=len(fetched.payload),
            provider_schema=fetched.provider_schema,
            parser_version=fetched.parser_version,
            pagination=(),
            upstream_checksum=fetched.upstream_checksum,
        )
        raw_key = f"raw/binance/{receipt.receipt_id}/archive.bin"
        raw_body: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": "raw",
            "artifact_key": raw_key,
            "artifact_sha256": receipt.response_sha256,
            "artifact_bytes": len(fetched.payload),
            "provider": "binance",
            "receipt_id": receipt.receipt_id,
            "receipt": receipt.to_dict(),
        }
        raw_id = hashlib.sha256(canonical_bytes(raw_body)).hexdigest()
        frame = _frame(fetched.payload)
        output = io.BytesIO()
        frame.write_parquet(output, compression="zstd", statistics=True)
        normalized = output.getvalue()
        digest = hashlib.sha256(normalized).hexdigest()
        key = f"normalized/market_bars/{DATASET.content_sha256}/{digest}.parquet"
        from alpha_data.crypto.contracts import CryptoQualityReportV1

        quality = CryptoQualityReportV1(
            dataset_sha256=digest,
            method_version="crypto-quality-v1",
            state="qualified",
            failures=(),
            warnings=(),
            observed_start=frame["open_time"][0],
            observed_end=frame["open_time"][0],
            row_count=1,
            correction_lineage=(),
        )
        body: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": "normalized",
            "artifact_key": key,
            "artifact_sha256": digest,
            "artifact_bytes": len(normalized),
            "provider": "binance",
            "dataset": DATASET.to_dict(),
            "input_manifest_ids": [raw_id],
            "quality": quality.to_dict(),
        }
        for manifest_body in (raw_body, body):
            manifest_id = hashlib.sha256(canonical_bytes(manifest_body)).hexdigest()
            expected[f"manifests/{manifest_id}.json"] = (
                json.dumps(
                    {**manifest_body, "manifest_id": manifest_id},
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                )
                + "\n"
            ).encode()
        expected[f"bulk/{raw_key}"] = fetched.payload
        expected[f"bulk/{key}"] = normalized
    return expected


def _listing(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }


def test_cli_reuses_one_store_and_matches_fresh_acquires_and_golden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before, after = tmp_path / "before", tmp_path / "after"
    _provider(monkeypatch, _store(before))
    monkeypatch.setattr(cmds, "_bulk_store", lambda: _store(before))
    for period in ("2024-01", "2024-02", "2024-03"):
        _acquire(period)
    assert _listing(before) == _golden()
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path / "control"))
    monkeypatch.setattr(cmds, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr("alpha_cli._crypto_backfill.time.sleep", lambda _: None)
    with patch.object(cmds, "_bulk_store", side_effect=lambda: _store(after)) as stores:
        cmds.backfill(
            "binance",
            "market_bars",
            symbols="BTCUSDT",
            quote="USDT",
            start="2024-01-01",
            end="2024-04-01",
            category="spot",
            frequency="1d",
            ledger="scaling",
            dry_run=False,
            max_verify_artifact_bytes=None,
            json_out=True,
        )
    assert _listing(after) == _golden()
    assert stores.call_count == 1


def test_revision_quarantines_after_index_build_and_after_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    _provider(monkeypatch, store)
    _prime(store)
    original = _acquire()
    assert _acquire()["normalized_manifest_id"] == original["normalized_manifest_id"]
    monkeypatch.setattr(cmds, "_fetch_non_bybit", lambda *a, **k: _fetched(k["period"], 2))
    revised = _acquire()
    assert revised["state"] == "quarantined"
    assert isinstance(revised["failures"], list)
    assert "unexplained_provider_revision" in revised["failures"]
    manifest = store.verify_manifest(revised["normalized_manifest_id"])
    quality = manifest["quality"]
    assert isinstance(quality, dict)
    assert quality["correction_lineage"] == [hashlib.sha256(b"1:1").hexdigest()]
    _provider(monkeypatch, _store(tmp_path))
    assert _acquire()["state"] == "quarantined"


def test_selected_lineage_still_rejects_corrupt_raw_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    _provider(monkeypatch, store)
    first = _acquire()
    manifest = store.verify_manifest(first["raw_manifest_id"])
    (store.bulk_root / str(manifest["artifact_key"])).write_bytes(b"bad")
    with pytest.raises(DataError, match="integrity"):
        _acquire()


def test_progress_changed_while_owned_still_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "progress.json"
    ledger = Ledger.open(
        path, provider="binance", family="market_bars", category="spot", frequency="1d"
    )
    with ledger.exclusive():
        ledger.record("first", {"state": "failed"})
        path.write_bytes(path.read_bytes().replace(b"first", b"other"))
        changed = path.read_bytes()
        with pytest.raises(DataError, match="stale|changed"):
            ledger.record("second", {"state": "failed"})
    assert path.read_bytes() == changed


def test_deferred_ledger_cannot_replace_unread_existing_progress(tmp_path: Path) -> None:
    path = tmp_path / "progress.json"
    scope: _Scope = {
        "provider": "binance",
        "family": "market_bars",
        "category": "spot",
        "frequency": "1d",
    }
    Ledger.open(path, **scope).record("first", {"state": "failed"})
    before = path.read_bytes()
    deferred = Ledger.open(path, **scope, defer_read=True)
    with pytest.raises(DataError, match="stale|unread"):
        deferred.record("second", {"state": "failed"})
    assert path.read_bytes() == before


def test_progress_replacement_during_parse_refuses_stale_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "progress.json"
    scope: _Scope = {
        "provider": "binance",
        "family": "market_bars",
        "category": "spot",
        "frequency": "1d",
    }
    Ledger.open(path, **scope).record("first", {"state": "failed"})
    original = json.loads

    def changed(raw: str) -> Any:
        result = original(raw)
        path.write_bytes(path.read_bytes().replace(b"first", b"other"))
        return result

    monkeypatch.setattr(json, "loads", changed)
    with pytest.raises(DataError, match="changed"):
        Ledger.open(path, **scope)


def test_progress_substitution_at_replace_cannot_become_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "progress.json"
    ledger = Ledger.open(
        path, provider="binance", family="market_bars", category="spot", frequency="1d"
    )
    original = os.replace

    def substituted(source: Path, destination: Path) -> None:
        original(source, destination)
        replacement = destination.with_suffix(".other")
        replacement.write_bytes(destination.read_bytes().replace(b"first", b"other"))
        original(replacement, destination)

    with ledger.exclusive():
        monkeypatch.setattr(os, "replace", substituted)
        with pytest.raises(DataError, match="changed"):
            ledger.record("first", {"state": "failed"})


def test_progress_serialization_size_is_the_only_growing_step_io(tmp_path: Path) -> None:
    sizes: dict[int, int] = {}
    scope: _Scope = {
        "provider": "binance",
        "family": "market_bars",
        "category": "spot",
        "frequency": "1d",
    }
    for count in (100, 1000, 5000):
        path = tmp_path / f"progress-{count}.json"
        windows = {
            f"retained-{index:05}": {"state": "failed", "error": "fixture"}
            for index in range(count)
        }
        path.write_text(json.dumps({"schema_version": 1, **scope, "windows": windows}))
        ledger = Ledger.open(path, **scope)
        with ledger.exclusive():
            with (
                patch.object(Ledger, "_read_raw", wraps=Ledger._read_raw) as reads,
                patch.object(os, "replace", wraps=os.replace) as replacements,
            ):
                ledger.record("next", {"state": "failed", "error": "fixture"})
            assert reads.call_count == 0
            assert replacements.call_count == 1
        sizes[count] = path.stat().st_size
        assert json.loads(path.read_bytes())["windows"] == {
            **windows,
            "next": {"state": "failed", "error": "fixture"},
        }
    print("PROGRESS_SIZE_EFFECT", sizes)


def test_cached_store_still_refuses_low_space_before_normalized_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    _provider(monkeypatch, store)
    _prime(store)
    with (
        patch.object(
            store,
            "_capacity",
            side_effect=[
                Capacity(2_000_000, 1_000_000),
                Capacity(2_000_000, 1_000_000),
                Capacity(2_000_000, 300_000),
            ],
        ),
        pytest.raises(DataError, match="reserve"),
    ):
        _acquire()
    manifests = store.inventory()
    assert len(manifests) == 1 and manifests[0]["artifact_kind"] == "raw"


def test_cached_store_observes_another_store_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _store(tmp_path)
    _prime(first)
    _provider(monkeypatch, _store(tmp_path))
    _acquire()
    _provider(monkeypatch, first)
    monkeypatch.setattr(cmds, "_fetch_non_bybit", lambda *a, **k: _fetched(k["period"], 2))
    assert _acquire()["state"] == "quarantined"


def test_retained_range_index_avoids_revisiting_unrelated_progress(tmp_path: Path) -> None:
    from alpha_cli._crypto_backfill import BackfillWindow

    visits: list[str] = []

    class CountedWindows(dict[str, dict[str, str]]):
        def __iter__(self) -> Iterator[str]:
            for key in super().__iter__():
                visits.append(key)
                yield key

    windows = CountedWindows(
        {
            f"COIN{index}USDT|2020-01-01|2020-02-01|None": {"state": "failed"}
            for index in range(5000)
        }
    )
    ledger = Ledger(
        tmp_path / "progress.json",
        {
            "provider": "bybit",
            "family": "funding",
            "category": "linear",
            "frequency": "1h",
            "windows": windows,
        },
        None,
    )
    window = BackfillWindow("2024-01-01", "2024-02-01", None)
    assert ledger.requested_leaves("BTCUSDT", window) == [window]
    visits.clear()
    assert ledger.requested_leaves("ETHUSDT", window) == [window]
    assert not visits
