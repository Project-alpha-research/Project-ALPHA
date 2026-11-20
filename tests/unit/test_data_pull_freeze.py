"""Every pull freezes the stored series first (freeze, validate, replace) and reports changes."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from alpha_core import CorporateAction, DataError
from alpha_core.corporate import ActionType
from alpha_data import pull_store
from alpha_data.adapters.base import FetchResult
from alpha_data.pull_store import FreezeRefused, PullReport, pull_into_store
from alpha_data.snapshot import verify_snapshot
from alpha_data.store import ParquetStore

NOW = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)


def _bars(days: list[int], close: float = 10.0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": [datetime(2026, 11, d, tzinfo=UTC) for d in days],
            "open": [close] * len(days),
            "high": [close + 1.0] * len(days),
            "low": [close - 1.0] * len(days),
            "close": [close] * len(days),
            "volume": [100.0] * len(days),
        }
    )


def _split(ratio: float = 2.0) -> CorporateAction:
    return CorporateAction(
        symbol="AAA", action_type=ActionType.SPLIT, ex_date=date(2026, 11, 3), ratio=ratio
    )


def _result(bars: pl.DataFrame, actions: list[CorporateAction] | None = None) -> FetchResult:
    return FetchResult("AAA", bars, actions or [])


def _pull(
    store: ParquetStore, result: FetchResult, *, version: str = "1", at: datetime = NOW
) -> PullReport:
    return pull_into_store(
        store,
        store.root.parent / "snapshots",
        result,
        source="fake",
        adapter_version=version,
        parser_version="1",
        now=at,
    )


def _bytes(store: ParquetStore) -> dict[str, bytes]:
    return {
        str(p.relative_to(store.root)): p.read_bytes()
        for p in sorted(store.root.rglob("*"))
        if p.is_file()
    }


def _snaps(store: ParquetStore) -> list[str]:
    root = store.root.parent / "snapshots"
    return sorted(p.name for p in root.iterdir()) if root.is_dir() else []


def test_the_first_pull_of_a_symbol_takes_no_snapshot(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path / "store")
    report = _pull(store, _result(_bars([2, 3, 4])))
    assert report.snapshot_id is None and _snaps(store) == []
    assert report.bars_added == (3, date(2026, 11, 2), date(2026, 11, 4))


def test_a_second_pull_freezes_the_old_series_and_reports_what_changed(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path / "store")
    _pull(store, _result(_bars([2, 3, 4]), [_split()]))
    before = _bytes(store)
    new = _bars([2, 3, 4, 5]).with_columns(
        pl.when(pl.col("ts").dt.day() >= 3)
        .then(pl.col("close") * 2)
        .otherwise(pl.col("close"))
        .alias("close")
    )
    report = _pull(store, _result(new, [_split(3.0)]))
    assert report.snapshot_id is not None and not report.reused
    snap = tmp_path / "snapshots" / report.snapshot_id
    verify_snapshot(snap)
    frozen = (snap / "bars" / "AAA.parquet").read_bytes()
    assert frozen == before["bars/AAA.parquet"]
    assert report.bars_added == (1, date(2026, 11, 5), date(2026, 11, 5))
    assert report.bars_removed == 0
    assert report.bars_revised == (2, date(2026, 11, 3), ["close"])
    assert report.actions_revised == 1 and report.actions_added == 0
    assert "the provider revised 2 earlier bars" in (report.notice or "")
    assert report.snapshot_id in (report.notice or "")
    as_text = json.dumps(report.as_dict())
    assert "20.0" not in as_text and "10.0" not in as_text  # counts and dates, never prices


def test_an_identical_series_is_frozen_once_and_then_reused(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path / "store")
    _pull(store, _result(_bars([2, 3, 4])))
    first = _pull(store, _result(_bars([2, 3, 4])))
    again = _pull(store, _result(_bars([2, 3, 4])), at=datetime(2026, 11, 21, tzinfo=UTC))
    assert first.snapshot_id is not None and not first.reused
    assert again.snapshot_id == first.snapshot_id and again.reused
    assert _snaps(store) == [first.snapshot_id]


def test_an_identical_repull_leaves_the_stored_files_and_the_fingerprint_unchanged(
    tmp_path: Path,
) -> None:
    from alpha_cli._runner import run_identity_for, source_fingerprint
    from alpha_core import Bar

    store = ParquetStore(tmp_path / "store")
    _pull(store, _result(_bars([2, 3, 4]), [_split()]))
    held = _bytes(store)

    def fingerprint() -> str:
        rows = store.read_bars("AAA").iter_rows(named=True)
        bars = [Bar(symbol="AAA", **row) for row in rows]
        return source_fingerprint(bars, dividends=store.read_actions("AAA"))

    before = fingerprint()
    identity = run_identity_for({"x": 1}, source_fingerprint=before)
    _pull(store, _result(_bars([2, 3, 4]), [_split()]))
    assert _bytes(store) == held
    assert fingerprint() == before
    assert run_identity_for({"x": 1}, source_fingerprint=fingerprint()).run_id == identity.run_id


def test_old_manifests_are_matched_by_their_digests_and_never_rewritten(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path / "store")
    _pull(store, _result(_bars([2, 3, 4])))
    first = _pull(store, _result(_bars([2, 3, 4])))
    assert first.snapshot_id is not None
    manifest = tmp_path / "snapshots" / first.snapshot_id / "manifest.json"
    assert "content_sha256" not in manifest.read_text()  # manifests keep their old shape
    old_bytes = manifest.read_bytes()
    second = _pull(store, _result(_bars([2, 3, 4])), at=datetime(2026, 11, 22, tzinfo=UTC))
    assert second.snapshot_id == first.snapshot_id and second.reused
    assert manifest.read_bytes() == old_bytes
    verify_snapshot(manifest.parent)


def test_data_that_fails_validation_changes_neither_store_nor_snapshots(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path / "store")
    _pull(store, _result(_bars([2, 3, 4])))
    held = _bytes(store)
    bad = _bars([2, 3, 4, 5]).with_columns(
        pl.when(pl.col("ts").dt.day() == 5)
        .then(float("nan"))
        .otherwise(pl.col("close"))
        .alias("close")
    )
    with pytest.raises(DataError, match="not a finite number"):
        _pull(store, _result(bad))
    assert _bytes(store) == held and _snaps(store) == []


def test_a_failed_freeze_stops_the_pull_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ParquetStore(tmp_path / "store")
    _pull(store, _result(_bars([2, 3, 4])))
    held = _bytes(store)

    def broken(*args: object, **kwargs: object) -> dict[str, object]:
        raise DataError("disk full")

    monkeypatch.setattr(pull_store, "create_snapshot", broken)
    with pytest.raises(FreezeRefused, match="disk full"):
        _pull(store, _result(_bars([2, 3, 4, 5])))
    assert _bytes(store) == held


def test_a_series_from_an_older_adapter_is_frozen_under_its_own_versions(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path / "store")
    _pull(store, _result(_bars([2, 3, 4])), version="1")
    held = _bytes(store)
    report = _pull(store, _result(_bars([2, 3, 4, 5])), version="2")
    assert report.snapshot_id is not None and report.older_versions == "fake adapter 1 / parser 1"
    snap = tmp_path / "snapshots" / report.snapshot_id
    verify_snapshot(snap)
    assert json.loads((snap / "manifest.json").read_text())["adapter_version"] == "1"
    assert (snap / "provenance" / "AAA.json").read_bytes() == held["provenance/AAA.json"]
    assert any("fake adapter 1 / parser 1" in line for line in report.lines())
    assert store.read_provenance("AAA") == {
        "source": "fake",
        "adapter_version": "2",
        "parser_version": "1",
    }


@pytest.mark.parametrize("failing", ["write_actions", "write_provenance"])
def test_a_crash_while_replacing_restores_the_old_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    store = ParquetStore(tmp_path / "store")
    _pull(store, _result(_bars([2, 3, 4]), [_split()]))
    held = _bytes(store)

    def crash(*args: object, **kwargs: object) -> Path:
        raise OSError("power cut")

    monkeypatch.setattr(ParquetStore, failing, crash)
    with pytest.raises(OSError, match="power cut"):
        _pull(store, _result(_bars([2, 3, 4, 5], close=99.0), [_split(5.0)]))
    monkeypatch.undo()
    stored = {k: v for k, v in _bytes(store).items()}
    assert stored == held


def test_a_crash_in_the_first_ever_pull_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ParquetStore(tmp_path / "store")

    def crash(*args: object, **kwargs: object) -> Path:
        raise OSError("power cut")

    monkeypatch.setattr(ParquetStore, "write_actions", crash)
    with pytest.raises(OSError, match="power cut"):
        _pull(store, _result(_bars([2, 3, 4])))
    assert _bytes(store) == {}


def test_the_content_hash_is_computed_from_the_three_digests_of_the_manifest(
    tmp_path: Path,
) -> None:
    from alpha_data.snapshot_reuse import content_hash

    store = ParquetStore(tmp_path / "store")
    _pull(store, _result(_bars([2, 3, 4]), [_split()]))
    report = _pull(store, _result(_bars([2, 3, 4]), [_split()]))
    assert report.snapshot_id is not None
    manifest = json.loads(
        (tmp_path / "snapshots" / report.snapshot_id / "manifest.json").read_text()
    )
    entry = manifest["symbols"]["AAA"]
    parts = ("bars_sha256", "actions_sha256", "provenance_sha256")
    joined = "\n".join(f"{name}:{entry[name]}" for name in parts)
    assert content_hash(entry) == hashlib.sha256(joined.encode()).hexdigest()
    assert "content_sha256" not in entry
