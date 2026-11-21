"""The research-case lane holds the reserved period back: diagnostic, data audit, controller.

Each path reads a store that has bars on and after the reserved day. The result must equal the
result on a store that ends the day before, no bar from the reserved day on may be read, and the
"Held back" sentence must appear. When no bar is held back, the ids and records stay as they were.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import polars as pl
import pytest
import typer
from typer.testing import CliRunner

from alpha_cli import _runner, research_data_audit, research_execution
from alpha_cli.main import app
from alpha_cli.research_diagnostic_cmds import diagnostic_app
from alpha_core import Bar
from alpha_core.corporate import ActionType, CorporateAction
from alpha_core.reserve import RESERVED_DAY, RESERVED_START
from alpha_data.pit import PointInTimeReader
from alpha_data.sessions import sessions_between
from alpha_data.snapshot import create_snapshot
from alpha_data.store import ParquetStore

PROJECT = "12345678-1234-4234-8234-123456789abc"
SENTENCE = "Held back"


def _same(left: object, right: object, path: str = "") -> None:
    """Every number equal to 1e-9 relative; every other value exactly equal."""
    if isinstance(left, dict) and isinstance(right, dict):
        assert left.keys() == right.keys(), path
        for key in left:
            _same(left[key], right[key], f"{path}/{key}")
    elif isinstance(left, list) and isinstance(right, list):
        assert len(left) == len(right), path
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            _same(a, b, f"{path}/{index}")
    elif isinstance(left, float) and isinstance(right, float):
        assert left == pytest.approx(right, rel=1e-9, abs=1e-12), path
    else:
        assert left == right, path


def _frame(days: list[date], *, poisoned: bool, seed: int) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.cumprod(1.0 + 0.0004 + rng.normal(0.0, 0.01, len(days)))
    rows = []
    for day, close in zip(days, closes.tolist(), strict=True):
        price = close * 1000.0 if poisoned and day >= RESERVED_DAY else close
        rows.append(
            {
                "ts": datetime.combine(day, datetime.min.time(), UTC),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1000.0,
            }
        )
    return pl.DataFrame(rows)


def _home(root: Path, days: list[date], *, poisoned: bool, symbol: str = "SPY") -> Path:
    """A store and a snapshot named ``frozen``; the poisoned store also has later actions."""
    store = ParquetStore(root / "store")
    store.write_bars(symbol, _frame(days, poisoned=poisoned, seed=7))
    store.write_provenance(symbol, source="alpaca", adapter_version="1", parser_version="1")
    if poisoned:
        store.write_actions(
            symbol,
            [
                CorporateAction(
                    symbol=symbol,
                    action_type=ActionType.SPLIT,
                    ex_date=date(2024, 2, 15),
                    ratio=4.0,
                ),
                CorporateAction(
                    symbol=symbol,
                    action_type=ActionType.DIVIDEND,
                    ex_date=date(2024, 3, 1),
                    pay_date=date(2024, 3, 5),
                    amount=1.0,
                ),
            ],
        )
    create_snapshot(
        store,
        root / "snapshots",
        "frozen",
        [symbol],
        source="alpaca",
        adapter_version="1",
        parser_version="1",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    return root


def _session_days(last: date) -> list[date]:
    return sessions_between("XNYS", date(2019, 1, 2), last)


def _pair(tmp_path: Path, all_days: list[date]) -> tuple[Path, Path]:
    """A store with bars after the boundary, and the same store cut the day before it."""
    cut_days = [day for day in all_days if day < RESERVED_DAY]
    assert len(cut_days) < len(all_days)
    return (
        _home(tmp_path / "poisoned", all_days, poisoned=True),
        _home(tmp_path / "cut", cut_days, poisoned=False),
    )


# ---- C5: weekly classifier ------------------------------------------------------------------


class Latest:
    """The latest bar each ``load_bars`` call returned."""

    def __init__(self) -> None:
        self.stamps: list[datetime] = []


@pytest.fixture
def latest(monkeypatch: pytest.MonkeyPatch) -> Latest:
    seen = Latest()
    load_bars = _runner.load_bars

    def spy(*args: Any, **kwargs: Any) -> tuple[list[Bar], str | None]:
        result = load_bars(*args, **kwargs)
        seen.stamps.append(max(bar.ts for bar in result[0]))
        return result

    monkeypatch.setattr(_runner, "load_bars", spy)
    return seen


def _classify(
    home: Path, monkeypatch: pytest.MonkeyPatch, as_of: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    root = typer.Typer()
    root.add_typer(diagnostic_app, name="diagnostic")
    root.command("other")(lambda: None)
    args = ["diagnostic", "weekly-classifier", "SPY", "--snapshot", "frozen", "--as-of", as_of]
    result = CliRunner().invoke(root, args)
    assert result.exit_code == 0, result.output
    payload: dict[str, Any] = json.loads(result.stdout)
    evidence: dict[str, Any] = json.loads(Path(payload["evidence"]).read_text())
    return payload, evidence


def test_weekly_classifier_reads_no_held_back_bar_and_equals_the_cut_store(
    tmp_path: Path, latest: Latest, monkeypatch: pytest.MonkeyPatch
) -> None:
    poisoned, cut = _pair(tmp_path, _session_days(date(2024, 6, 28)))
    held, held_evidence = _classify(poisoned, monkeypatch, "2024-04-30")
    assert latest.stamps and all(stamp.date() < RESERVED_DAY for stamp in latest.stamps)
    assert held["reserve"]["reserved_start"] == RESERVED_START
    assert held["reserve"]["held_back_bars"] > 0
    assert SENTENCE in held["reserve_sentence"] and RESERVED_START in held["reserve_sentence"]
    assert held_evidence["identity"]["reserve"] == held["reserve"]
    plain, plain_evidence = _classify(cut, monkeypatch, "2024-04-30")
    assert "reserve" not in plain and "reserve_sentence" not in plain
    assert "reserve" not in plain_evidence["identity"]
    _same(held["metrics"], plain["metrics"])
    _same(held_evidence["report"], plain_evidence["report"])
    assert held["sha256"] != plain["sha256"]


def test_weekly_classifier_as_of_before_the_boundary_keeps_its_identity(
    tmp_path: Path, latest: Latest, monkeypatch: pytest.MonkeyPatch
) -> None:
    poisoned, _ = _pair(tmp_path, _session_days(date(2024, 6, 28)))
    payload, evidence = _classify(poisoned, monkeypatch, "2023-06-30")
    assert "reserve" not in payload and "reserve_sentence" not in payload
    identity = evidence["identity"]
    assert set(identity) == {
        "version",
        "execution_fingerprint",
        "research_source_sha256",
        "runtime_versions",
        "python_version",
        "symbol",
        "snapshot",
        "as_of",
        "calendar",
        "cost_bps_per_side",
        "snapshot_hash",
        "source_hash",
        "calendar_hash",
    }
    assert identity["as_of"] == "2023-06-30"
    stable = {
        "identity": {
            key: value
            for key, value in identity.items()
            if key not in {"execution_fingerprint", "research_source_sha256", "runtime_versions"}
            and key != "python_version"
        },
    }
    text = json.dumps(stable, sort_keys=True, allow_nan=False)
    assert hashlib.sha256(text.encode()).hexdigest() == PINNED_WEEKLY


# Pinned on the code before the reserved period was held back here (code and environment hashes
# left out): an as-of before the boundary keeps its evidence.
PINNED_WEEKLY = "033ff8ddd9828226414efcd07a4aef006b10b1e3bd5d34e7405f058646a56ec1"


# ---- C6: data audit -------------------------------------------------------------------------


def _ref(home: Path, *, end_ts: str) -> dict[str, object]:
    manifest = home / "snapshots" / "frozen" / "manifest.json"
    return {
        "ref_id": "rd_" + "a" * 64,
        "instrument": "SPY",
        "dataset_kind": "snapshot",
        "start_ts": "2019-01-02",
        "end_ts": end_ts,
        "origin": {
            "snapshot_id": "frozen",
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        },
    }


class Ends:
    """The ``end_at`` each point-in-time read was given."""

    def __init__(self) -> None:
        self.at: list[datetime] = []


@pytest.fixture
def ends(monkeypatch: pytest.MonkeyPatch) -> Ends:
    seen = Ends()
    original = PointInTimeReader.as_of

    def as_of(self: Any, instrument: str, end_at: datetime) -> pl.DataFrame:
        seen.at.append(end_at)
        return original(self, instrument, end_at)

    monkeypatch.setattr(PointInTimeReader, "as_of", as_of)
    return seen


def test_audit_read_is_capped_at_the_boundary_and_says_so(tmp_path: Path, ends: Ends) -> None:
    poisoned, cut = _pair(tmp_path, _session_days(date(2024, 6, 28)))
    ref = _ref(poisoned, end_ts="2024-04-30")
    frame = research_data_audit.load_registered_dataset_frame(poisoned, ref=ref)
    assert ends.at and all(end.date() < RESERVED_DAY for end in ends.at), ends.at
    assert frame["ts"].max().date() < RESERVED_DAY
    reference = research_data_audit.load_registered_dataset_frame(
        cut, ref=_ref(cut, end_ts="2024-04-30")
    )
    assert frame.height == reference.height
    assert frame["close"].to_list() == pytest.approx(
        reference["close"].to_list(), rel=1e-9, abs=1e-12
    )

    held = research_data_audit.run_data_audit(poisoned, project_id=PROJECT, ref=ref)
    plain = research_data_audit.run_data_audit(
        cut, project_id=PROJECT, ref=_ref(cut, end_ts="2024-04-30")
    )
    notes = held["summary"]["notes"]
    assert any(SENTENCE in note and RESERVED_START in note for note in notes), notes
    assert not any(SENTENCE in note for note in plain["summary"]["notes"])
    assert held["manifest"]["dataset_hash"] == plain["manifest"]["dataset_hash"]
    assert held["manifest"]["reserve"]["reserved_start"] == RESERVED_START
    assert held["manifest"]["reserve"]["held_back_bars"] > 0
    assert held["manifest"]["labels"] == ["reserved-period-held-back"]
    assert "reserve" not in plain["manifest"] and "labels" not in plain["manifest"]
    _same(
        json.loads(
            (poisoned / "runs" / held["manifest"]["run_id"] / "descriptives.json").read_text()
        ),
        json.loads((cut / "runs" / plain["manifest"]["run_id"] / "descriptives.json").read_text()),
    )


def test_audit_with_an_end_before_the_boundary_keeps_its_record(tmp_path: Path, ends: Ends) -> None:
    poisoned, cut = _pair(tmp_path, _session_days(date(2024, 6, 28)))
    ref = _ref(poisoned, end_ts="2023-06-30")
    held = research_data_audit.run_data_audit(poisoned, project_id=PROJECT, ref=ref)
    plain = research_data_audit.run_data_audit(
        cut, project_id=PROJECT, ref=_ref(cut, end_ts="2023-06-30")
    )
    assert ends.at and all(end.date() <= date(2023, 6, 30) for end in ends.at)
    assert not any(SENTENCE in note for note in held["summary"]["notes"])
    assert held["summary"] == plain["summary"]
    assert held["manifest"]["dataset_hash"] == plain["manifest"]["dataset_hash"]
    assert "reserve" not in held["manifest"] and "labels" not in held["manifest"]


# ---- C7: the controller ---------------------------------------------------------------------

SPEC = dict(lookback=20, skip=1, vol_window=10, rebalance_every=5, train_size=300, test_size=60)


def _plan(as_of: str) -> research_execution.BaselineExecutionPlan:
    return research_execution.BaselineExecutionPlan(
        symbol="SPY", snapshot="frozen", as_of=as_of, embargo=2, **SPEC
    )


def _controller(home: Path, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Run the baseline child for real, in process; stop at the validation stage."""
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    calls: list[list[str]] = []

    def child(args: list[str], *, output: Path, **_: Any) -> dict[str, Any]:
        calls.append(args)
        if "validate" in args:
            output.write_text("not run in this test")
            return {"status": "failed", "returncode": 2, "elapsed_seconds": 0.0}
        result = CliRunner().invoke(app, args[3:])
        output.write_text(result.output)
        return {"status": "completed", "returncode": result.exit_code, "elapsed_seconds": 0.0}

    monkeypatch.setattr(research_execution, "run_child", child)
    return calls


def _baseline(receipt: dict[str, Any]) -> dict[str, Any]:
    attempt: dict[str, Any] = receipt["attempts"][0]
    assert attempt["stage"] == "baseline"
    assert attempt["status"] == "completed", attempt
    digest: dict[str, Any] = attempt["digest"]
    return digest


def test_controller_agrees_with_the_cut_child_when_the_plan_is_past_the_boundary(
    tmp_path: Path, latest: Latest, monkeypatch: pytest.MonkeyPatch
) -> None:
    poisoned, cut = _pair(tmp_path, [d for d in _session_days(date(2024, 6, 28)) if d.year >= 2021])
    _controller(poisoned, monkeypatch)
    held = research_execution.execute_plan(_plan("2024-04-30"), data_dir=poisoned)
    assert latest.stamps and all(stamp.date() < RESERVED_DAY for stamp in latest.stamps)
    digest = _baseline(held)
    assert held["reserve"]["reserved_start"] == RESERVED_START
    assert held["reserve"]["held_back_bars"] > 0
    assert SENTENCE in held["reserve_sentence"] and RESERVED_START in held["reserve_sentence"]
    assert digest["research_cutoff"] == "2023-12-31"
    _controller(cut, monkeypatch)
    plain = research_execution.execute_plan(_plan("2024-04-30"), data_dir=cut)
    reference = _baseline(plain)
    assert "reserve" not in plain and "reserve_sentence" not in plain
    for key in ("sessions", "orders_by_status", "fill_events", "closed_trades"):
        _same(digest[key], reference[key])


def test_plan_before_the_boundary_keeps_its_identity_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    poisoned, _ = _pair(tmp_path, [d for d in _session_days(date(2024, 6, 28)) if d.year >= 2021])
    _controller(poisoned, monkeypatch)
    plan = _plan("2023-06-30")
    receipt = research_execution.execute_plan(plan, data_dir=poisoned)
    _baseline(receipt)
    assert "reserve" not in receipt and "reserve_sentence" not in receipt
    saved = json.loads((Path(receipt["receipt"]).parent / "plan.json").read_text())
    assert set(saved) == {
        "plan",
        "snapshot_hash",
        "execution_fingerprint",
        "controller_sha256",
        "digest_sha256",
    }
    assert saved["plan"] == plan.model_dump(mode="json")


def test_past_the_boundary_with_nothing_stored_there_keeps_the_plan_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    days = [d for d in _session_days(date(2023, 12, 29)) if d.year >= 2021]
    home = _home(tmp_path / "short", days, poisoned=False)
    _controller(home, monkeypatch)
    receipt = research_execution.execute_plan(_plan("2024-04-30"), data_dir=home)
    digest = _baseline(receipt)
    assert "reserve" not in receipt
    assert digest["research_cutoff"] == "2024-04-30"


def test_a_case_frozen_on_bars_past_the_boundary_fails_loud_instead_of_a_new_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sealed split of an older case cannot silently change: its frozen data hash fails."""
    from types import SimpleNamespace

    from alpha_cli import research_cmds
    from alpha_cli.control_store import ControlStore
    from alpha_cli.research_d1 import load_registered_research_bars
    from alpha_cli.spine import reserve
    from alpha_core import DataError

    poisoned, _ = _pair(tmp_path, _session_days(date(2024, 6, 28)))
    monkeypatch.setenv("ALPHA_DATA_DIR", str(poisoned))
    ref = {**_ref(poisoned, end_ts="2024-04-30"), "bar_duration_minutes": 1440}
    with monkeypatch.context() as before:  # the read as it was before the cut
        before.setattr(reserve, "CUTOFF", datetime(2099, 1, 1, tzinfo=UTC))
        frozen = load_registered_research_bars(poisoned, ref=ref)
    now = load_registered_research_bars(poisoned, ref=ref)
    assert max(bar.start for bar in frozen.bars).date() >= RESERVED_DAY
    assert max(bar.start for bar in now.bars).date() < RESERVED_DAY
    sha = frozen.dataset.content_sha256
    assert now.dataset.content_sha256 != sha
    store = SimpleNamespace(get_research_dataset=lambda _ref_id: ref)
    payload = {
        "protocol": {"empirical_dataset": {"ref_id": ref["ref_id"], "content_sha256": sha}},
        "hashes": {"data": sha},
    }
    with pytest.raises(DataError, match="no longer reproduce the approval-frozen data hash"):
        research_cmds._empirical_d1_bars(cast(ControlStore, store), payload)
