"""The one-shot confirmation of a frozen rule test on the reserved period, end to end.

Temporary data homes only: no real store and no real slot. One stored rule test is made once per
module and copied into each test's own home. A bias guard: bars after the frozen span are
poisoned, and no reserved bar is read before the slot is spent (the owner approved this file's
place in tests/bias_guards on 2026-11-22).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_cli import _runner, next_cmds, reserved_slots
from alpha_cli.spine import confirm_run as confirm_module
from alpha_cli.spine import reserve
from alpha_cli.spine.confirm import frozen_test, plan
from alpha_cli.spine.confirm_run import confirm_run
from alpha_cli.spine.deflation import count_snapshot
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.ledger import read_trials
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.run import write_run as real_write_run
from alpha_cli.spine.spec import load_spec
from alpha_cli.spine.trial_reader import spine_snapshot
from alpha_core import Bar, DataError
from alpha_core.reserve import RESERVED_INSTANT
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

pytestmark = pytest.mark.bias_guard

# 2020-01-01 plus 1,600 daily bars ends 2024-05-19: 139 bars are in the reserved period.
LONG, RESERVED = 1600, 139


@dataclass
class Reads:
    """Each bar read: its latest stamp and how many slots were spent at that moment."""

    home: Path
    seen: list[tuple[datetime, int]] = field(default_factory=list)

    def reserved(self) -> list[tuple[datetime, int]]:
        return [item for item in self.seen if item[0] >= RESERVED_INSTANT]


def _test(home: Path, *params: str) -> dict[str, Any]:
    spec = load_spec(
        None, rule="ma_cross", param=list(params or ("fast=5", "slow=20")), asset=["SPY"]
    )
    out: dict[str, Any] = run_idea(spec, home=home, quick=True, no_diagnose=True)["results"][0]
    assert out["error"] is None, out
    return out


@pytest.fixture(scope="module")
def stored(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    """One home with one stored rule test, made once; each test works on its own copy."""
    home = tmp_path_factory.mktemp("stored")
    seed_store(home, symbol="SPY", n=LONG)
    ParquetStore(home / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    return home, _test(home)


@pytest.fixture
def home(stored: tuple[Path, dict[str, Any]], tmp_path: Path) -> Path:
    copy = tmp_path / "home"
    shutil.copytree(stored[0], copy)
    return copy


@pytest.fixture
def run_id(stored: tuple[Path, dict[str, Any]]) -> str:
    return str(stored[1]["run_id"])


@pytest.fixture
def reads(home: Path, monkeypatch: pytest.MonkeyPatch) -> Reads:
    found = Reads(home)
    load_bars = _runner.load_bars

    def spy(*args: Any, **kwargs: Any) -> tuple[list[Bar], str | None]:
        result = load_bars(*args, **kwargs)
        found.seen.append((max(b.ts for b in result[0]), len(reserved_slots.receipts(home))))
        return result

    monkeypatch.setattr(_runner, "load_bars", spy)
    return found


def _poison_after_end(home: Path, extra: int) -> None:
    """Add bars after the frozen span with prices times 1,000 (still valid bars)."""
    store = ParquetStore(home / "store")
    now = store.read_bars("SPY")
    seed_store(home, symbol="SPY", n=LONG + extra)
    longer = store.read_bars("SPY")
    tail = longer.filter(pl.col("ts") > now["ts"].max()).with_columns(
        [pl.col(name) * 1000.0 for name in ("open", "high", "low", "close")]
    )
    store.write_bars("SPY", pl.concat([now, tail]))


def test_plan_reads_no_reserved_bar_and_writes_nothing(
    home: Path, run_id: str, reads: Reads
) -> None:
    before = (home / "ledger" / "trials.jsonl").read_bytes()
    found = plan(home, run_id)
    assert found["slots"] == {"used": 0, "left": 10, "total": 10}
    frozen = found["frozen"]
    assert frozen["reserved_bars"] == RESERVED and frozen["reserved_first"].startswith("2024-01-01")
    assert frozen["run_id"] == run_id and frozen["family_asset"] == "spine:ma_cross|SPY"
    assert "cannot be undone" in " ".join(found["consequences"])
    assert not (home / "control").exists() and not reads.reserved()
    assert (home / "ledger" / "trials.jsonl").read_bytes() == before


def test_one_confirmation_reads_reserved_bars_only_after_its_receipt(
    home: Path, run_id: str, reads: Reads, monkeypatch: pytest.MonkeyPatch
) -> None:
    family_before = count_snapshot(spine_snapshot(home), "ma_cross")
    end = plan(home, run_id)["frozen"]["reserved_end"]
    take_slot = reserved_slots.take_slot

    def poison_then_take(*args: Any, **kwargs: Any) -> dict[str, Any]:
        # Bars stored after the span is frozen and before the read must never be scored.
        _poison_after_end(home, 20)
        return take_slot(*args, **kwargs)

    monkeypatch.setattr(reserved_slots, "take_slot", poison_then_take)
    output = confirm_run(home, run_id)
    # Receipt before read: every read that reached the period ran with the slot already spent,
    # and none reached past the frozen span (the poisoned bars).
    assert reads.reserved() and all(spent == 1 for _, spent in reads.reserved())
    assert max(ts for ts, _ in reads.seen).isoformat() == end
    assert output["slot"] == 1 and output["slots_left"] == 9
    assert output["earlier"]["run_id"] == run_id
    assert output["earlier"]["scored_to"] < "2024-01-01"
    assert output["reserved"]["scored_from"] >= "2024-01-01"
    assert reserve.CONFIRMATION in output["reserved"]["labels"]
    sharpe = output["reserved"]["oos_sharpe"]
    assert isinstance(sharpe, float) and abs(sharpe) < 50  # no poisoned price was scored
    # The ledger: its own kind, never a counted trial; the family count is unchanged.
    row = read_trials(home)[-1]
    assert row["kind"] == "reserved_confirmation" and row["slot"] == 1
    assert "oos_sharpe" not in row and "periods_per_year" not in row
    snapshot = spine_snapshot(home)
    record = next(r for r in snapshot.records if r.run_id == output["confirmation_run_id"])
    assert record.counts_for_deflation is False and record.kind == "reserved_confirmation"
    after = count_snapshot(snapshot, "ma_cross")
    assert (after.prior_trials, after.unknown_rows) == (
        family_before.prior_trials,
        family_before.unknown_rows,
    )
    # One-shot: asking again shows the same stored result and spends nothing.
    seen = len(reads.seen)
    again = confirm_run(home, run_id)
    assert again["reserved"] == output["reserved"] and len(reads.seen) == seen
    assert len(reserved_slots.receipts(home)) == 1
    line = "Reserved period: 1 of 10 confirmation slots used, 9 left. See them: alpha confirm list"
    assert line in next_cmds._text(next_cmds.collect(home))
    # The family label: a tuned variant on the same asset carries it, and cannot be confirmed.
    tuned = _test(home, "fast=6", "slow=20")
    assert reserve.CONFIRMED in tuned["labels"]
    with pytest.raises(SpineError, match="already confirmed"):
        plan(home, tuned["run_id"])


def test_a_recheck_that_does_not_match_spends_nothing(
    home: Path, run_id: str, reads: Reads, monkeypatch: pytest.MonkeyPatch
) -> None:
    def differs(*_: Any, **__: Any) -> dict[str, Any]:
        return {"recheck": {"match": False, "compared_with": run_id, "differences_total": 3}}

    monkeypatch.setattr(confirm_module, "recheck_one", differs)
    with pytest.raises(SpineError, match="No slot was used"):
        confirm_run(home, run_id)
    assert reserved_slots.receipts(home) == [] and not reads.reserved()


def test_a_crash_after_the_receipt_resumes_with_the_same_slot_and_span(
    home: Path, run_id: str, reads: Reads, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(*_: Any, **__: Any) -> dict[str, Any]:
        raise OSError("power cut")

    monkeypatch.setattr(confirm_module, "write_run", crash)
    with pytest.raises(OSError, match="power cut"):
        confirm_run(home, run_id)
    [spent] = reserved_slots.receipts(home)
    assert spent["slot"] == 1 and spent["result"] is None
    end = spent["frozen"]["reserved_end"]
    # Bars stored after the crash are left out of the resumed run: the span stays frozen.
    _poison_after_end(home, 20)
    monkeypatch.setattr(confirm_module, "write_run", real_write_run)
    done = confirm_run(home, run_id)
    assert done["receipt_id"] == spent["receipt_id"] and done["slot"] == 1
    assert len(reserved_slots.receipts(home)) == 1
    assert max(ts for ts, _ in reads.seen).isoformat() == end
    assert abs(done["reserved"]["oos_sharpe"]) < 50


def test_a_test_changed_after_its_slot_was_spent_cannot_resume(
    home: Path, run_id: str, reads: Reads, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(*_: Any, **__: Any) -> dict[str, Any]:
        raise OSError("power cut")

    monkeypatch.setattr(confirm_module, "write_run", crash)
    with pytest.raises(OSError, match="power cut"):
        confirm_run(home, run_id)
    reads.seen.clear()
    monkeypatch.setattr(confirm_module, "write_run", real_write_run)
    # The stored test now reads as another one (its engine seed changed on disk).

    def changed(*args: Any, **kwargs: Any) -> Any:
        found = frozen_test(*args, **kwargs)
        return replace(found, seed=found.seed + 1)

    monkeypatch.setattr(confirm_module, "frozen_test", changed)
    with pytest.raises(DataError, match="changed after its slot was spent"):
        confirm_run(home, run_id)
    assert not reads.reserved()
