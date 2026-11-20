"""Attacks on freeze-before-replace: crashes, a failed restore, two pulls at once, forged or
tampered snapshots, identity of an earlier window, and the honesty of the change report."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from alpha_core import CorporateAction, DataError
from alpha_core.corporate import ActionType
from alpha_data import pipeline
from alpha_data.adapters.base import FetchResult
from alpha_data.pipeline import RestoreFailed, rollback_interrupted_promotion
from alpha_data.pull_store import PullReport, pull_into_store
from alpha_data.snapshot import verify_snapshot
from alpha_data.store import ParquetStore

NOW = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)


def _bars(days: list[int], close: float = 10.0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": [datetime(2026, 10, d, tzinfo=UTC) for d in days],
            "open": [close] * len(days),
            "high": [close + 1.0] * len(days),
            "low": [close - 1.0] * len(days),
            "close": [close] * len(days),
            "volume": [100.0] * len(days),
        }
    )


def _split(ratio: float, day: int = 3) -> CorporateAction:
    return CorporateAction(
        symbol="AAA", action_type=ActionType.SPLIT, ex_date=date(2026, 10, day), ratio=ratio
    )


def _pull(
    store: ParquetStore,
    bars: pl.DataFrame,
    actions: list[CorporateAction] | None = None,
    at: datetime = NOW,
) -> PullReport:
    return pull_into_store(
        store,
        store.root.parent / "snapshots",
        FetchResult("AAA", bars, actions or []),
        source="fake",
        adapter_version="1",
        parser_version="1",
        now=at,
    )


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def _series(store: ParquetStore) -> dict[str, bytes]:
    return {
        k: v
        for k, v in _files(store.root).items()
        if k.split("/")[0] in {"bars", "actions", "provenance"}
    }


_KILL = """
import os, sys
from datetime import UTC, datetime
import polars as pl
from alpha_data.adapters.base import FetchResult
from alpha_data.pull_store import pull_into_store
from alpha_data.store import ParquetStore
root, method = sys.argv[1], sys.argv[2]
setattr(ParquetStore, method, lambda *a, **k: os._exit(9))
bars = pl.read_parquet(sys.argv[3])
pull_into_store(ParquetStore(root), ParquetStore(root).root.parent / "snapshots",
    FetchResult("AAA", bars, []), source="fake", adapter_version="1", parser_version="1",
    now=datetime(2026, 11, 21, tzinfo=UTC))
"""


@pytest.mark.parametrize("killed_at", ["write_actions", "write_provenance"])
def test_a_kill_inside_the_replace_is_loud_and_the_repair_restores_the_old_bytes(
    tmp_path: Path, killed_at: str
) -> None:
    store = ParquetStore(tmp_path / "store")
    _pull(store, _bars([2, 3, 4]), [_split(2.0)])
    _pull(store, _bars([2, 3, 4]), [_split(2.0)])  # take a frozen copy of the old series
    held = _series(store)
    new = tmp_path / "new.parquet"
    _bars([2, 3, 4, 5], close=99.0).write_parquet(new)
    child = subprocess.run(
        [sys.executable, "-c", _KILL, str(store.root), killed_at, str(new)], check=False
    )
    assert child.returncode == 9
    with pytest.raises(DataError, match="rollback-promotion AAA --acknowledge"):
        store.read_bars("AAA")  # never a silent mix of new bars and old actions
    with pytest.raises(DataError, match="interrupted promotion"):
        _pull(store, _bars([2, 3, 4, 5]))
    rollback_interrupted_promotion(store, symbol="AAA", acknowledge=True)
    assert _series(store) == held


def test_a_failed_restore_keeps_reads_refusing_and_names_the_snapshot_and_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ParquetStore(tmp_path / "store")
    _pull(store, _bars([2, 3, 4]), [_split(2.0)])
    held = _series(store)

    def full(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(ParquetStore, "write_actions", full)
    monkeypatch.setattr(pipeline, "_copy_atomic", full)
    with pytest.raises(RestoreFailed) as info:
        _pull(store, _bars([2, 3, 4, 5], close=99.0))
    monkeypatch.undo()
    message = str(info.value)
    assert (
        "snapshot pull-" in message and "alpha data rollback-promotion AAA --acknowledge" in message
    )
    with pytest.raises(DataError, match="interrupted promotion"):
        store.read_bars("AAA")
    rollback_interrupted_promotion(store, symbol="AAA", acknowledge=True)
    assert _series(store) == held


def test_two_pulls_at_once_never_interleave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ParquetStore(tmp_path / "store")
    _pull(store, _bars([2, 3, 4]))
    original = ParquetStore.write_bars
    spans: list[tuple[str, float, float]] = []

    def slow(self: ParquetStore, symbol: str, df: pl.DataFrame) -> Path:
        start = time.monotonic()
        time.sleep(0.3)
        path = original(self, symbol, df)
        spans.append((str(df["close"][0]), start, time.monotonic()))
        return path

    monkeypatch.setattr(ParquetStore, "write_bars", slow)
    first = threading.Thread(target=_pull, args=(store, _bars([2, 3, 4, 5], close=20.0)))
    first.start()
    time.sleep(0.1)
    _pull(
        ParquetStore(store.root),
        _bars([2, 3, 4, 5, 6], close=30.0),
        at=datetime(2026, 11, 21, tzinfo=UTC),
    )
    first.join()
    assert [s[0] for s in spans] == ["20.0", "30.0"] and spans[1][1] >= spans[0][2]
    assert store.read_bars("AAA")["close"].to_list() == [30.0] * 5


def test_a_reused_pull_leaves_every_snapshot_byte_identical(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path / "store")
    _pull(store, _bars([2, 3, 4]), [_split(2.0)])
    _pull(store, _bars([2, 3, 4]), [_split(2.0)])
    before = _files(tmp_path / "snapshots")
    again = _pull(store, _bars([2, 3, 4]), [_split(2.0)], at=datetime(2026, 11, 22, tzinfo=UTC))
    assert again.reused and _files(tmp_path / "snapshots") == before


def test_a_tampered_snapshot_is_never_reused(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path / "store")
    _pull(store, _bars([2, 3, 4]))
    first = _pull(store, _bars([2, 3, 4]))
    assert first.snapshot_id is not None
    bars = tmp_path / "snapshots" / first.snapshot_id / "bars" / "AAA.parquet"
    _bars([2, 3, 4], close=50.0).write_parquet(bars)
    with pytest.raises(DataError):
        verify_snapshot(bars.parent.parent)
    again = _pull(store, _bars([2, 3, 4]), at=datetime(2026, 11, 22, tzinfo=UTC))
    assert again.snapshot_id != first.snapshot_id and not again.reused
    verify_snapshot(tmp_path / "snapshots" / str(again.snapshot_id))


def test_a_forged_manifest_cannot_make_a_different_series_look_frozen(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path / "store")
    _pull(store, _bars([2, 3, 4]))
    older = _pull(store, _bars([2, 3, 4, 5], close=20.0))  # freezes the close-10 series
    assert older.snapshot_id is not None
    manifest = tmp_path / "snapshots" / older.snapshot_id / "manifest.json"
    forged = json.loads(manifest.read_text())
    import hashlib

    for kind in ("bars", "provenance"):
        path = store.series_paths("AAA")[0 if kind == "bars" else 2]
        forged["symbols"]["AAA"][f"{kind}_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(forged, indent=2, sort_keys=True))
    held = store.series_paths("AAA")[0].read_bytes()
    report = _pull(store, _bars([2, 3, 4, 5, 6], close=30.0), at=datetime(2026, 11, 22, tzinfo=UTC))
    assert report.snapshot_id != older.snapshot_id and not report.reused
    frozen = tmp_path / "snapshots" / str(report.snapshot_id) / "bars" / "AAA.parquet"
    assert frozen.read_bytes() == held


def test_an_appending_pull_keeps_the_fingerprint_of_an_earlier_window(tmp_path: Path) -> None:
    from alpha_cli._runner import load_bars, run_identity_for, source_fingerprint

    store = ParquetStore(tmp_path / "store")
    _pull(store, _bars(list(range(1, 11))))

    def fingerprint(as_of: datetime | None) -> str:
        bars, _ = load_bars("AAA", data_dir=tmp_path, as_of=as_of)
        return source_fingerprint(bars)

    cut = datetime(2026, 10, 10, tzinfo=UTC)
    early, whole = fingerprint(cut), fingerprint(None)
    key = run_identity_for({"x": 1}, source_fingerprint=early).run_id
    _pull(store, _bars(list(range(1, 14))))
    assert fingerprint(cut) == early
    assert run_identity_for({"x": 1}, source_fingerprint=fingerprint(cut)).run_id == key
    assert fingerprint(None) != whole


def test_the_report_counts_a_revised_volume_two_removed_and_three_added(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path / "store")
    _pull(store, _bars([1, 2, 3, 4, 5]), [_split(2.0), _split(3.0, day=4)])
    new = _bars([1, 2, 3, 6, 7, 8]).with_columns(
        pl.when(pl.col("ts").dt.day() == 2).then(777.0).otherwise(pl.col("volume")).alias("volume")
    )
    report = _pull(store, new, [_split(2.0), _split(5.0, day=4), _split(4.0, day=7)])
    assert report.bars_added == (3, date(2026, 10, 6), date(2026, 10, 8))
    assert report.bars_removed == 2
    assert report.bars_revised == (1, date(2026, 10, 2), ["volume"])
    assert (report.actions_added, report.actions_removed, report.actions_revised) == (1, 0, 1)
    assert report.notice is not None and str(report.snapshot_id) in report.notice
    shown = json.dumps(report.as_dict()) + "\n".join(report.lines())
    assert "777" not in shown and "10.0" not in shown and "11.0" not in shown


def test_a_legacy_series_without_provenance_is_frozen_as_unrecorded(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path / "store")
    store.write_bars("AAA", _bars([2, 3, 4]))
    held = store.series_paths("AAA")[0].read_bytes()
    report = _pull(store, _bars([2, 3, 4, 5]))
    snap = tmp_path / "snapshots" / str(report.snapshot_id)
    verify_snapshot(snap)
    assert json.loads((snap / "manifest.json").read_text())["source"] == "unrecorded"
    assert (snap / "bars" / "AAA.parquet").read_bytes() == held
