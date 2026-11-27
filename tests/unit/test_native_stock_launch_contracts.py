"""Closed stock launch profile and pre-spawn consumption on a pinned tree.

The real upstream RD-Agent checkout is not required: a small synthetic ``rdagent`` tree is
measured and the module's source pin is set to that tree's digest for the duration of a test.
Everything else (measurement, admission checks, the retained owner and the durable journal) is
the production code path against a disposable synthetic store.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from alpha_cli._native_fixture_store import _events
from alpha_cli._native_loop_admission import WORKER, _digest
from alpha_cli._native_stock_launch import (
    SCOPE,
    StockFixtureLaunch,
    consume_before_spawn,
)
from alpha_cli.control_store import ControlStore
from alpha_cli.native_stock_fixture import StockFixtureRequest, stock_fixture_manifest
from alpha_cli.native_supervisor import _open_lock, _Owner, synthetic_workspace
from alpha_core import DataError
from tests.unit.test_research_control_store import _approved_native_d1, _native_d1_job, _project

JOB = "5b0d43f4-6a43-4d1f-9a1e-3f0c2b7e9d11"
APP = Path(__file__).resolve().parents[2] / "apps/alpha-cli/src/alpha_cli"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class StockTree:
    source: Path
    runtime: Path
    pin: str


def _stock_tree(base: Path) -> StockTree:
    base = base.resolve()
    source = base / "source"
    (source / "rdagent" / "core").mkdir(parents=True)
    (source / "rdagent" / "__init__.py").write_text("# synthetic upstream package\n")
    (source / "rdagent" / "core" / "loop.py").write_text("class LoopBase: ...\n")
    runtime = base / "runtime"
    (runtime / "venv" / "bin").mkdir(parents=True)
    (runtime / "dependencies.lock.txt").write_text("synthetic==1.0\n")
    (runtime / "venv" / "bin" / "python").write_bytes(b"synthetic interpreter bytes")
    (runtime / "venv" / "pyvenv.cfg").write_text("home = /synthetic\n")
    files = {
        str(path.relative_to(source)): _sha(path)
        for path in sorted((source / "rdagent").rglob("*"))
        if path.is_file()
    }
    return StockTree(source, runtime, _digest(files))


@contextmanager
def _pinned(tree: StockTree) -> Iterator[None]:
    with patch("alpha_cli._native_stock_launch.SOURCE_SHA256", tree.pin):
        yield


@pytest.fixture
def tree(tmp_path: Path) -> Iterator[StockTree]:
    built = _stock_tree(tmp_path)
    with _pinned(built):
        yield built


def _admission(launch: StockFixtureLaunch, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema": "SyntheticNativeAdmissionV1",
        "job_id": "job",
        "reservation_id": "reservation",
        "owner_id": "owner",
        "spec_sha256": "a" * 64,
        "manifest_sha256": launch.fingerprint,
        "mode": launch.mode,
        "loop_steps": 5,
        "cpu_milliseconds": 1000,
    }
    value.update(overrides)
    return value


# --- profile measurement -------------------------------------------------------------------


def test_pinned_tree_measures_a_stable_mode_bound_profile(tree: StockTree) -> None:
    launch = StockFixtureLaunch(tree.source, "resume", stock_runtime=tree.runtime)
    assert len(launch.fingerprint) == 64
    assert launch.measure() == launch.fingerprint
    again = StockFixtureLaunch(tree.source, "resume", stock_runtime=tree.runtime)
    assert again.fingerprint == launch.fingerprint
    cancel = StockFixtureLaunch(tree.source, "cancel", stock_runtime=tree.runtime)
    assert cancel.fingerprint != launch.fingerprint

    # Bytecode caches are not part of the measured upstream source.
    cache = tree.source / "rdagent" / "__pycache__"
    cache.mkdir()
    (cache / "loop.cpython-312.pyc").write_bytes(b"\x00cache")
    assert launch.measure() == launch.fingerprint


def test_implementation_fingerprints_measure_runtime_selector_and_evaluator(
    tree: StockTree,
) -> None:
    launch = StockFixtureLaunch(tree.source, "resume", stock_runtime=tree.runtime)
    hashes = launch.implementation_fingerprints()
    assert set(hashes) == {"code", "dependency_lock", "environment", "evaluator", "data"}
    assert hashes["data"] is None
    assert hashes["dependency_lock"] == _sha(tree.runtime / "dependencies.lock.txt")
    assert hashes["evaluator"] == _sha(APP / "native_stock_fixture.py")
    assert hashes["environment"] == _digest(
        {
            "python": _sha(tree.runtime / "venv/bin/python"),
            "pyvenv": _sha(tree.runtime / "venv/pyvenv.cfg"),
            "selector": str(tree.runtime),
        }
    )

    (tree.runtime / "dependencies.lock.txt").write_text("synthetic==2.0\n")
    changed = launch.implementation_fingerprints()
    assert changed["dependency_lock"] != hashes["dependency_lock"]
    assert changed["code"] == hashes["code"]
    # The runtime is part of the measured profile, so the launch no longer matches itself.
    assert launch.measure() != launch.fingerprint


def test_source_drift_and_nested_symlinks_break_the_pin(tree: StockTree) -> None:
    launch = StockFixtureLaunch(tree.source, "resume", stock_runtime=tree.runtime)
    loop = tree.source / "rdagent" / "core" / "loop.py"
    loop.write_text("class LoopBase: changed = True\n")
    with pytest.raises(DataError, match="exact pinned upstream source"):
        launch.measure()
    with pytest.raises(DataError, match="exact pinned upstream source"):
        StockFixtureLaunch(tree.source, "resume", stock_runtime=tree.runtime)
    loop.write_text("class LoopBase: ...\n")
    assert launch.measure() == launch.fingerprint

    (tree.source / "rdagent" / "core" / "alias.py").symlink_to(loop)
    with pytest.raises(DataError, match="symlink is unsupported"):
        launch.measure()


@pytest.mark.parametrize("mode", ["SUPPORTED", "wait", "failure", ""])
def test_closed_profile_refuses_non_stock_modes(tree: StockTree, mode: str) -> None:
    with pytest.raises(DataError, match="closed synthetic-only profile"):
        StockFixtureLaunch(tree.source, mode, stock_runtime=tree.runtime)


def test_closed_profile_refuses_studies_and_authorities(tree: StockTree) -> None:
    sentinel = cast(Any, object())
    with pytest.raises(DataError, match="closed synthetic-only profile"):
        StockFixtureLaunch(tree.source, "resume", sentinel, stock_runtime=tree.runtime)
    with pytest.raises(DataError, match="closed synthetic-only profile"):
        StockFixtureLaunch(tree.source, "resume", authority=sentinel, stock_runtime=tree.runtime)


def test_source_and_runtime_must_be_canonical_directories(tree: StockTree) -> None:
    linked = tree.source.parent / "linked-source"
    linked.symlink_to(tree.source, target_is_directory=True)
    indirect = tree.source / ".." / tree.source.name
    a_file = tree.runtime / "dependencies.lock.txt"
    for source, runtime in (
        (linked, tree.runtime),
        (indirect, tree.runtime),
        (tree.source, a_file),
        (tree.source, tree.runtime.parent / "missing-runtime"),
    ):
        with pytest.raises(DataError, match="canonical source/runtime directories"):
            StockFixtureLaunch(source, "resume", stock_runtime=runtime)


# --- admission -> request/command ------------------------------------------------------------


def test_request_is_rebuilt_only_from_matching_durable_admission(tree: StockTree) -> None:
    launch = StockFixtureLaunch(tree.source, "exhaust", stock_runtime=tree.runtime)
    request = launch.request(_admission(launch))
    assert request == StockFixtureRequest(
        "job",
        "reservation",
        "owner",
        "a" * 64,
        stock_fixture_manifest(),
        5,
        2,
        2,
        1000,
        "exhaust",
    )


@pytest.mark.parametrize(
    "override",
    [
        {"manifest_sha256": "f" * 64},
        {"mode": "resume"},
    ],
)
def test_request_refuses_admission_for_another_profile(
    tree: StockTree, override: dict[str, object]
) -> None:
    launch = StockFixtureLaunch(tree.source, "exhaust", stock_runtime=tree.runtime)
    with pytest.raises(DataError, match="differs from durable admission"):
        launch.request(_admission(launch, **override))
    with pytest.raises(DataError, match="differs from durable admission"):
        launch.request(None)


@pytest.mark.parametrize(
    "override",
    [
        {"schema": "SyntheticNativeAdmissionV2"},
        {"cpu_milliseconds": True},
        {"cpu_milliseconds": 1000.0},
        {"job_id": 7},
        {"owner_id": None},
        {"unexpected": "field"},
    ],
)
def test_request_refuses_malformed_admission_fields(
    tree: StockTree, override: dict[str, object]
) -> None:
    launch = StockFixtureLaunch(tree.source, "resume", stock_runtime=tree.runtime)
    with pytest.raises(DataError, match="admission fields are invalid"):
        launch.request(_admission(launch, **override))


def test_request_refuses_a_profile_that_changed_after_construction(tree: StockTree) -> None:
    launch = StockFixtureLaunch(tree.source, "resume", stock_runtime=tree.runtime)
    (tree.runtime / "venv" / "pyvenv.cfg").write_text("home = /elsewhere\n")
    with pytest.raises(DataError, match="differs from durable admission"):
        launch.request(_admission(launch))


def test_command_is_the_fixed_isolated_entry_with_the_bound_payload(tree: StockTree) -> None:
    launch = StockFixtureLaunch(tree.source, "tamper", stock_runtime=tree.runtime)
    admission = _admission(launch)
    argv = launch.command(admission)
    assert argv[:4] == [
        str(tree.runtime / "venv/bin/python"),
        "-I",
        "-B",
        str(WORKER / "stock_fixture_entry.py"),
    ]
    assert argv[4:6] == [str(tree.source), "supervised"]
    assert json.loads(argv[6]) == launch.request(admission).payload()
    assert len(argv) == 7
    with pytest.raises(DataError, match="differs from durable admission"):
        launch.command(_admission(launch, mode="resume"))


# --- durable pre-spawn consumption ----------------------------------------------------------


@contextmanager
def _claimed(tree: StockTree) -> Iterator[tuple[Path, ControlStore, StockFixtureLaunch, _Owner]]:
    launch = StockFixtureLaunch(tree.source, "resume", stock_runtime=tree.runtime)
    with ExitStack() as stack:
        root = stack.enter_context(synthetic_workspace())
        store = ControlStore(root)
        _project(store)
        contract, _ = _approved_native_d1(
            store, loop_steps=5, implementation_fingerprints=launch.implementation_fingerprints()
        )
        _native_d1_job(store, contract, job_id=JOB, manifest_sha256=launch.fingerprint)
        lock = stack.enter_context(_open_lock(root, JOB))
        owner = _Owner(root, JOB, "native_loop", 40, lock, native=launch)
        store.claim_native_fixture(JOB, owner)
        yield root, store, launch, owner


def _journal(store: ControlStore) -> dict[str, dict[str, object]]:
    with store._transaction(write=False) as connection:
        return _events(connection, JOB)


def test_consumption_requires_the_exact_retained_owner_type() -> None:
    with pytest.raises(DataError, match="exact retained owner/launch"):
        consume_before_spawn(object())


def test_consumption_journals_one_bounded_invocation_before_spawn(tree: StockTree) -> None:
    with _claimed(tree) as (_root, store, launch, owner):
        assert set(_journal(store)) == {"native_claim"}
        consume_before_spawn(owner)
        events = _journal(store)
        assert set(events) == {"native_claim", "native_invocation"}
        invocation = events["native_invocation"]
        claim = events["native_claim"]
        assert invocation["scope"] == SCOPE
        assert invocation["profile_sha256"] == launch.fingerprint == claim["stock_profile_sha256"]
        assert (invocation["loop_steps"], invocation["model_calls"], invocation["tool_calls"]) == (
            5,
            2,
            2,
        )
        for key in ("job_id", "reservation_id", "owner_id", "spec_sha256"):
            assert invocation[key] == claim[key]
        assert owner.process is None
        assert owner.spawn_attempted is False

        with pytest.raises(DataError, match="already consumed; reconnect only"):
            consume_before_spawn(owner)
        assert set(_journal(store)) == {"native_claim", "native_invocation"}


def test_consumption_refuses_after_an_attempt_or_profile_change(tree: StockTree) -> None:
    with _claimed(tree) as (_root, store, _launch, owner):
        owner.spawn_attempted = True
        with pytest.raises(DataError, match="already attempted or profile changed"):
            consume_before_spawn(owner)
        owner.spawn_attempted = False
        (tree.runtime / "dependencies.lock.txt").write_text("synthetic==3.0\n")
        with pytest.raises(DataError, match="already attempted or profile changed"):
            consume_before_spawn(owner)
        assert set(_journal(store)) == {"native_claim"}


def test_cancelled_or_stopped_owner_cannot_consume(tree: StockTree) -> None:
    with _claimed(tree) as (_root, store, _launch, owner):
        owner.request_stop("owner_error")
        with pytest.raises(DataError, match="stopped owner cannot consume"):
            consume_before_spawn(owner)
    with _claimed(tree) as (_root, store, _launch, owner):
        store.request_job_cancellation(JOB, actor="synthetic", reason="cancel before spawn")
        with pytest.raises(DataError, match="stopped owner cannot consume"):
            consume_before_spawn(owner)
        assert set(_journal(store)) == {"native_claim"}


# --- journal contract for stock lifecycle rows -----------------------------------------------


def _rows(store: ControlStore) -> list[dict[str, object]]:
    with store._transaction(write=False) as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM job_events WHERE job_id=? ORDER BY sequence", (JOB,)
            )
        ]


def _rewrite(row: dict[str, object], **payload: object) -> dict[str, object]:
    body = json.loads(str(row["payload_json"])) | payload
    return row | {"payload_json": json.dumps(body, sort_keys=True)}


def _lifecycle(
    row: dict[str, object], kind: str, sequence: int, **extra: object
) -> dict[str, object]:
    claim = json.loads(str(row["payload_json"]))
    body = {k: claim[k] for k in ("schema", "job_id", "reservation_id", "spec_sha256", "owner_id")}
    return row | {
        "event_type": kind,
        "sequence": sequence,
        "payload_json": json.dumps(body | extra, sort_keys=True),
    }


def test_journal_rejects_rewritten_stock_lifecycle_rows(tree: StockTree) -> None:
    from tests.unit._native_stock_test_support import event_rows

    with _claimed(tree) as (_root, store, _launch, owner):
        consume_before_spawn(owner)
        rows = [r for r in _rows(store) if str(r["event_type"]).startswith("native_")]
        claim, invocation = rows
        start = int(cast(int, invocation["sequence"])) + 1
        cases: list[tuple[list[dict[str, object]], str]] = [
            (
                [_rewrite(claim, stock_profile_sha256="0" * 64), invocation],
                "stock claim differs from canonical invocation",
            ),
            ([claim, _rewrite(invocation, scope="other")], "consumption binding/order"),
            ([claim, _rewrite(invocation, loop_steps=4)], "consumption binding/order"),
            (
                [claim, _lifecycle(claim, "native_started", start - 1, leader_pid=1)],
                "requires prior durable invocation consumption",
            ),
        ]
        with store._transaction(write=False) as source:
            assert set(_events(source, JOB)) == {"native_claim", "native_invocation"}
            for changed, message in cases:
                with (
                    event_rows(source, changed, JOB) as connection,
                    pytest.raises(DataError, match=message),
                ):
                    _events(connection, JOB)
