"""The crypto research lane holds the reserved period back: crowding, hedged basis, candidate.

A bundle with rows on and after the reserved instant must give the same observations as the same
bundle cut before it. The cut runs inside the parquet scan. The held-back count reads time
columns only. A sealed candidate holdout window is read on purpose and is reported, not cut.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import (
    _runner,
    crypto_data_cmds,
    research_crypto_strategy,
    research_data_audit,
    strategy_candidate_cmds,
)
from alpha_cli.main import app
from alpha_cli.research_crypto_data import (
    compose_crypto_crowding_observations,
    held_back_rows,
    load_crypto_crowding_observations,
)
from alpha_cli.spine import reserve
from alpha_core.reserve import RESERVED_INSTANT, RESERVED_START
from alpha_data.crypto.contracts import CryptoQualityReportV1, CryptoSnapshotV1
from tests.unit import test_crypto_crowding_composition as bundle

EVENTS = 40
START = RESERVED_INSTANT - timedelta(hours=8 * 25)
SENTENCE = "Held back"


def _frames(*, poisoned: bool, cut: bool) -> dict[str, pl.DataFrame]:
    """A crowding bundle that crosses the reserved instant, optionally cut before it."""
    funding_times = [START + timedelta(hours=8 * index) for index in range(EVENTS)]
    hourly = [START - timedelta(hours=25) + timedelta(hours=i) for i in range(25 + 8 * EVENTS)]

    def value(stamp: datetime, base: float) -> float:
        return base * 1000.0 if poisoned and stamp >= RESERVED_INSTANT else base

    def hourly_frame(column: str, base: float, extra: dict[str, str] | None = None) -> pl.DataFrame:
        columns: dict[str, Any] = {
            "timestamp": hourly,
            "category": ["linear"] * len(hourly),
            "symbol": ["BTCUSDT"] * len(hourly),
            column: [value(stamp, base + 0.01 * (i % 7)) for i, stamp in enumerate(hourly)],
        }
        for name, text in (extra or {}).items():
            columns[name] = [text] * len(hourly)
        return pl.DataFrame(columns)

    frames = {
        "funding": pl.DataFrame(
            {
                "timestamp": funding_times,
                "category": ["linear"] * EVENTS,
                "symbol": ["BTCUSDT"] * EVENTS,
                "funding_rate": [value(t, 0.001 + 1e-6 * i) for i, t in enumerate(funding_times)],
            }
        ),
        "open_interest": hourly_frame("open_interest", 1000.0),
        "long_short_ratio": hourly_frame("long_short_ratio", 1.25),
        "premium_bars": hourly_frame("close", 0.001, {"family": "premium"}),
        "mark_bars": hourly_frame("close", 100.0, {"family": "mark"}),
        "index_bars": hourly_frame("close", 100.0, {"family": "index"}),
        "derivative_bars": hourly_frame("close", 100.0, {"family": "trade"}),
        "instrument_catalog": bundle._frames()["instrument_catalog"],
    }
    if cut:
        frames = {
            name: frame.filter(pl.col("timestamp") < RESERVED_INSTANT)
            if "timestamp" in frame.columns
            else frame
            for name, frame in frames.items()
        }
    return frames


def _snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, poisoned: bool, cut: bool
) -> tuple[CryptoSnapshotV1, dict[str, CryptoQualityReportV1]]:
    frames = _frames(poisoned=poisoned, cut=cut)
    monkeypatch.setattr(bundle, "_frames", lambda: frames)
    return bundle._snapshot_fixture(tmp_path)


def _after(frames: dict[str, pl.DataFrame]) -> int:
    return sum(
        frame.filter(pl.col("timestamp") >= RESERVED_INSTANT).height
        for frame in frames.values()
        if "timestamp" in frame.columns
    )


def test_crowding_load_equals_the_cut_bundle_and_counts_what_it_held_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    full, cut = tmp_path / "full", tmp_path / "cut"
    snapshot, reports = _snapshot(full, monkeypatch, poisoned=True, cut=False)
    cut_snapshot, cut_reports = _snapshot(cut, monkeypatch, poisoned=False, cut=True)
    held = load_crypto_crowding_observations(snapshot, reports, bulk_root=full)
    plain = load_crypto_crowding_observations(cut_snapshot, cut_reports, bulk_root=cut)
    assert held and held == plain
    assert all(item.exit_available_at <= RESERVED_INSTANT for item in held)
    assert held_back_rows(snapshot, bulk_root=full) == _after(_frames(poisoned=True, cut=False))
    assert held_back_rows(cut_snapshot, bulk_root=cut) == 0
    uncut = load_crypto_crowding_observations(
        snapshot, reports, bulk_root=full, before_reserved=False
    )
    assert max(item.funding_time for item in uncut) >= RESERVED_INSTANT


def test_crowding_load_reads_no_row_from_the_reserved_instant_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot, reports = _snapshot(tmp_path, monkeypatch, poisoned=True, cut=False)
    seen: list[pl.DataFrame] = []
    compose = compose_crypto_crowding_observations

    def spy(frames: Any, **kwargs: Any) -> Any:
        seen.extend(frames.values())
        return compose(frames, **kwargs)

    monkeypatch.setattr("alpha_cli.research_crypto_data.compose_crypto_crowding_observations", spy)
    load_crypto_crowding_observations(snapshot, reports, bulk_root=tmp_path)
    assert seen
    for frame in seen:
        if "timestamp" in frame.columns:
            assert max(frame["timestamp"].to_list()) < RESERVED_INSTANT


def test_a_bundle_that_ends_before_the_boundary_gives_the_observations_it_gave_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = {
        name: (
            frame.filter(pl.col("timestamp") < RESERVED_INSTANT - timedelta(days=2))
            if "timestamp" in frame.columns
            else frame
        )
        for name, frame in _frames(poisoned=False, cut=False).items()
    }
    monkeypatch.setattr(bundle, "_frames", lambda: frames)
    snapshot, reports = bundle._snapshot_fixture(tmp_path)
    loaded = load_crypto_crowding_observations(snapshot, reports, bulk_root=tmp_path)
    assert loaded == compose_crypto_crowding_observations(frames, correction_lineage=())
    assert held_back_rows(snapshot, bulk_root=tmp_path) == 0


def _spot(tmp_path: Path) -> Path:
    stamps = [RESERVED_INSTANT - timedelta(hours=3) + timedelta(hours=i) for i in range(6)]
    path = tmp_path / "spot.parquet"
    pl.DataFrame(
        {
            "open_time": stamps,
            "close_time": [s + timedelta(hours=1) for s in stamps],
            "close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
        }
    ).write_parquet(path)
    return path


def test_spot_bars_are_kept_when_they_close_by_the_boundary(tmp_path: Path) -> None:
    path = _spot(tmp_path)
    cut = research_crypto_strategy._read_spot(path, before_reserved=True)
    assert cut["close"].to_list() == [100.0, 101.0, 102.0]
    assert cut["close_time"].max() == RESERVED_INSTANT
    assert research_crypto_strategy._read_spot(path, before_reserved=False).height == 6


# ---- the audit and the candidate command ------------------------------------------------------


def test_audit_of_a_crypto_dataset_stops_at_the_boundary_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "crypto" / "snapshots" / ("a" * 64 + ".json")
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}")
    import hashlib

    stamps = [RESERVED_INSTANT + timedelta(hours=8 * i - 80) for i in range(20)]
    observations = [SimpleNamespace(funding_time=s, funding_rate=0.001) for s in stamps]
    monkeypatch.setattr(crypto_data_cmds, "crypto_crowding_observations", lambda _: observations)
    ref = {
        "ref_id": "rd_" + "b" * 64,
        "instrument": "BTC",
        "start_ts": "2023-01-01",
        "end_ts": "2024-06-30",
        "origin": {
            "snapshot_schema": "CryptoSnapshotV1",
            "snapshot_id": "a" * 64,
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        },
    }
    frame = research_data_audit.load_registered_dataset_frame(tmp_path, ref=ref)
    assert 0 < frame.height < len(stamps)
    assert frame["ts"].max() < RESERVED_INSTANT
    monkeypatch.setattr("alpha_cli.research_crypto_data.snapshot_held_back_rows", lambda *a, **k: 7)
    held = research_data_audit._audit_hold(tmp_path, ref)
    assert held.record_fields() == {"reserve": reserve.record(7, "rows")}
    note = held.say()
    assert note == reserve.sentence(7, "rows")
    assert "rows (bars, funding and open interest)" in note and SENTENCE in note


class Candidate:
    """What the candidate command passed on."""

    def __init__(self) -> None:
        self.run: dict[str, Any] = {}
        self.loads: list[bool] = []


@pytest.fixture
def candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Candidate:
    seen = Candidate()
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(_runner, "verified_snapshot_hash", lambda *_: "e" * 64)

    def observations(_: str, *, before_reserved: bool = True) -> tuple[()]:
        seen.loads.append(before_reserved)
        return ()

    def fake_run(_: Path, **kwargs: Any) -> dict[str, Any]:
        seen.run = kwargs
        return {"run_id": "1234567890abcdef", "reserve": kwargs["held"].record_fields() or None}

    monkeypatch.setattr(strategy_candidate_cmds, "crypto_hedged_basis_observations", observations)
    monkeypatch.setattr(strategy_candidate_cmds, "run_hedged_basis_candidate", fake_run)
    return seen


def _candidate(
    *extra: str, rows: int, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, list[datetime | None]]:
    def count(*_a: Any, **kwargs: Any) -> int:
        counted.append(kwargs.get("until"))
        return rows

    counted: list[datetime | None] = []
    monkeypatch.setattr(strategy_candidate_cmds, "snapshot_held_back_rows", count)
    args = ["strategy-candidate", "run", "d" * 64, "--research-contract-id", f"rc_{'f' * 64}"]
    return CliRunner().invoke(app, [*args, *extra]), counted


@pytest.mark.parametrize("extra", [[], ["--as-of", "2025-03-01"]])
def test_candidate_cutoff_defaults_to_the_reserve_cutoff_and_says_so(
    candidate: Candidate, monkeypatch: pytest.MonkeyPatch, extra: list[str]
) -> None:
    result, counted = _candidate(*extra, rows=5, monkeypatch=monkeypatch)
    assert result.exit_code == 0, result.output
    assert candidate.run["as_of"] == reserve.CUTOFF
    assert candidate.run["research_cutoff"] == reserve.CUTOFF_DATE
    held = candidate.run["held"]
    assert held == reserve.Hold(reserve.CUTOFF, reserve.CUTOFF_DATE, 5, "rows")
    assert held.record_fields() == {"reserve": reserve.record(5, "rows")}
    assert SENTENCE in result.output and RESERVED_START in result.output
    assert candidate.loads == [True]
    # Only rows the user's own cut-off would have admitted are counted.
    assert counted == [_runner.parse_as_of(extra[1]) if extra else None]


def test_candidate_with_nothing_held_back_keeps_its_cutoff_and_record(
    candidate: Candidate, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, counted = _candidate("--json", rows=0, monkeypatch=monkeypatch)
    assert result.exit_code == 0, result.output
    assert candidate.run["research_cutoff"] is None
    assert not candidate.run["held"].held_back
    assert json.loads(result.output)["reserve"] is None
    assert SENTENCE not in result.output


def test_candidate_with_an_early_cutoff_is_not_changed(
    candidate: Candidate, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, counted = _candidate("--as-of", "2023-06-30", rows=9, monkeypatch=monkeypatch)
    assert result.exit_code == 0, result.output
    assert candidate.run["research_cutoff"] == "2023-06-30"
    assert candidate.run["as_of"] == datetime(2023, 6, 30, 23, 59, 59, tzinfo=UTC)
    assert not candidate.run["held"].held_back


def test_candidate_holdout_reads_its_sealed_window_and_is_not_cut(
    candidate: Candidate, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = ["--holdout-start", "2025-01-01", "--holdout-end", "2025-01-31"]
    result, counted = _candidate("--analysis", "holdout", *window, rows=5, monkeypatch=monkeypatch)
    assert result.exit_code == 0, result.output
    assert candidate.loads == [False]
    assert candidate.run["as_of"] is None
    assert not candidate.run["held"].held_back


def test_candidate_run_records_the_hold_back_and_its_label_only_when_rows_were_held(
    tmp_path: Path,
) -> None:
    from alpha_cli.strategy_candidate_runtime import run_hedged_basis_candidate
    from tests.unit.test_strategy_candidate_runtime import _observations

    def run(held: reserve.Hold, home: Path) -> dict[str, Any]:
        return run_hedged_basis_candidate(
            home,
            snapshot_id="d" * 64,
            snapshot_hash="e" * 64,
            research_contract_id=f"rc_{'f' * 64}",
            observations=_observations(),
            analysis="baseline",
            research_cutoff=held.research_cutoff,
            as_of=None,
            held=held,
        )

    stamped = run(reserve.Hold(reserve.CUTOFF, reserve.CUTOFF_DATE, 5, "rows"), tmp_path / "a")
    assert stamped["reserve"] == reserve.record(5, "rows")
    assert reserve.HELD_BACK in stamped["labels"]
    plain = run(reserve.Hold(reserve.CUTOFF, None, 0, "rows"), tmp_path / "b")
    assert "reserve" not in plain and reserve.HELD_BACK not in plain.get("labels", [])
    before = run_hedged_basis_candidate(
        tmp_path / "c",
        snapshot_id="d" * 64,
        snapshot_hash="e" * 64,
        research_contract_id=f"rc_{'f' * 64}",
        observations=_observations(),
        analysis="baseline",
        research_cutoff=None,
        as_of=None,
    )
    assert plain["run_id"] == before["run_id"]


def test_candidate_count_reads_only_rows_the_user_cutoff_admits(tmp_path: Path) -> None:
    stamps = [RESERVED_INSTANT + timedelta(days=d) for d in (-1, 0, 10, 40)]
    path = tmp_path / "member.parquet"
    pl.DataFrame({"timestamp": stamps}).write_parquet(path)
    member = SimpleNamespace(artifact_key="member.parquet")
    snapshot = cast(CryptoSnapshotV1, SimpleNamespace(members=(member,)))
    assert held_back_rows(snapshot, bulk_root=tmp_path) == 3
    until = RESERVED_INSTANT + timedelta(days=20)
    assert held_back_rows(snapshot, bulk_root=tmp_path, until=until) == 2
