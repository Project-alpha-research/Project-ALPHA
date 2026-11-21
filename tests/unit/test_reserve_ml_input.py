"""`alpha ml export-input` holds the reserved period back from the Qlib input bundle."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import _runner
from alpha_cli.control_store import ControlStore
from alpha_cli.main import app
from alpha_cli.ml_contract import MIN_SYMBOLS, sha256_file
from alpha_cli.ml_input import _aligned_panel, export_project_input
from alpha_core import Bar
from alpha_core.reserve import RESERVED_DAY, RESERVED_INSTANT, RESERVED_START
from alpha_data.snapshot import create_snapshot
from alpha_data.store import ParquetStore
from tests.fixtures.control_store_fixtures import mark_project_as_migrated_legacy

START = date(2020, 1, 1)
CUT_N = (RESERVED_DAY - START).days  # sessions stamped before the reserved day
EXTRA = 60  # sessions on or after the reserved day in the poisoned store
HELD_PER_SYMBOL = EXTRA
SENTENCE = f"Held back {HELD_PER_SYMBOL * MIN_SYMBOLS} bars from {RESERVED_START} on"
# Pinned on the code before this change, for a store with no bar on or after the boundary.
PINNED_SPEC_SHA256 = "1d2396a61d692cfbb45c1cf451daa492024f648091017474f8226b334c14fb9c"

runner = CliRunner()
World = tuple[Path, str, str]  # data dir, project id, experiment id


class Spy:
    """The latest bar each stored-bar read returned."""

    def __init__(self) -> None:
        self.latest: list[datetime] = []


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    seen = Spy()
    load_bars = _runner.load_bars

    def bars(*args: Any, **kwargs: Any) -> tuple[list[Bar], str | None]:
        result = load_bars(*args, **kwargs)
        seen.latest.append(max(bar.ts for bar in result[0]))
        return result

    monkeypatch.setattr(_runner, "load_bars", bars)
    return seen


def _world(root: Path, sessions_total: int, *, poison_from: int | None) -> World:
    symbols = [f"S{index:02d}" for index in range(MIN_SYMBOLS)]
    stamps = [
        datetime.combine(START + timedelta(days=i), datetime.min.time(), tzinfo=UTC)
        for i in range(sessions_total)
    ]
    store = ParquetStore(root / "store")
    for symbol_index, symbol in enumerate(symbols):
        prices = [
            10_000.0 + symbol_index + i
            if poison_from is not None and i >= poison_from
            else 100.0 + symbol_index + i * 0.01
            for i in range(sessions_total)
        ]
        store.write_bars(
            symbol,
            pl.DataFrame(
                {
                    "ts": stamps,
                    "open": prices,
                    "high": [p + 1.0 for p in prices],
                    "low": [p - 1.0 for p in prices],
                    "close": [p + 0.25 for p in prices],
                    "volume": [1_000_000.0 + symbol_index] * sessions_total,
                }
            ),
        )
    create_snapshot(
        store,
        root / "snapshots",
        "ml-frozen",
        symbols,
        source="fixture",
        adapter_version="1",
        parser_version="1",
        created_at=datetime(2026, 7, 19, tzinfo=UTC),
    )
    control = ControlStore(root)
    project = control.create_project(
        name="Reserve starter",
        hypothesis="Relative winners persist one session.",
        falsification_criterion="Reject if locked OOS excess return is non-positive.",
        at=datetime(2026, 7, 19, tzinfo=UTC),
    )
    project_id = str(project["project_id"])
    mark_project_as_migrated_legacy(control, project_id)
    version = control.create_strategy_version(
        project_id,
        strategy_name="qlib_alpha158_lgbm",
        source_fingerprint="git:test",
        definition={"decision": "close_t", "fill": "open_t_plus_1"},
        parameter_space={},
    )
    experiment = control.create_experiment_spec(
        project_id,
        strategy_version_id=str(version["version_id"]),
        snapshot_id="ml-frozen",
        universe=symbols,
        split_policy={"train": 504, "test": 63, "purge": 5, "embargo": 5},
        costs={"fee_bps": 1.0, "slippage_bps": 2.0},
        seeds={"master": 7},
        stage_config={"ml": {"validation_sessions": 120}},
    )
    return root, project_id, str(experiment["experiment_id"])


@pytest.fixture(scope="module")
def poisoned(tmp_path_factory: pytest.TempPathFactory) -> World:
    return _world(tmp_path_factory.mktemp("poisoned"), CUT_N + EXTRA, poison_from=CUT_N)


@pytest.fixture(scope="module")
def cut(tmp_path_factory: pytest.TempPathFactory) -> World:
    return _world(tmp_path_factory.mktemp("cut"), CUT_N, poison_from=None)


def _export(world: World, name: str, as_of: str | None = None) -> tuple[dict[str, object], Path]:
    data_dir, project_id, experiment_id = world
    out = data_dir / "bundles" / name
    summary = export_project_input(
        data_dir=data_dir,
        project_id=project_id,
        experiment_id=experiment_id,
        output_dir=out,
        as_of=as_of,
    )
    return summary, out


def _spec_without_snapshot(bundle: Path) -> dict[str, Any]:
    spec: dict[str, Any] = json.loads((bundle / "spec.json").read_text(encoding="utf-8"))
    del spec["snapshot_hash"]
    return spec


def test_a_poisoned_store_gives_the_bundle_of_a_store_cut_at_the_boundary(
    poisoned: World, cut: World, spy: Spy
) -> None:
    held_summary, held_bundle = _export(poisoned, "held")
    plain_summary, plain_bundle = _export(cut, "plain")
    assert (held_bundle / "panel.parquet").read_bytes() == (
        plain_bundle / "panel.parquet"
    ).read_bytes()
    assert _spec_without_snapshot(held_bundle) == _spec_without_snapshot(plain_bundle)
    assert held_summary["panel_sha256"] == plain_summary["panel_sha256"]
    assert held_summary["sessions"] == plain_summary["sessions"] == CUT_N
    panel = pl.read_parquet(held_bundle / "panel.parquet")
    assert panel["session_ts"].max() < RESERVED_INSTANT


def test_no_bar_on_or_after_the_boundary_is_read(poisoned: World, spy: Spy) -> None:
    _export(poisoned, "spied")
    assert len(spy.latest) == MIN_SYMBOLS
    assert max(spy.latest) < RESERVED_INSTANT


def test_the_held_back_record_is_in_the_summary_and_the_bundle(poisoned: World) -> None:
    summary, bundle = _export(poisoned, "recorded")
    assert summary["reserve"] == {
        "reserved_start": RESERVED_START,
        "held_back_bars": HELD_PER_SYMBOL * MIN_SYMBOLS,
    }
    assert summary["research_cutoff"] == "2023-12-31"
    assert summary["labels"] == ["reserved-period-held-back"]
    assert SENTENCE in str(summary["reserve_sentence"])
    record = json.loads((bundle / "reserve.json").read_text(encoding="utf-8"))
    assert record["reserve"] == summary["reserve"]
    assert record["research_cutoff"] == "2023-12-31"
    assert record["labels"] == ["reserved-period-held-back"]


def test_the_command_prints_the_held_back_sentence(
    poisoned: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir, project_id, experiment_id = poisoned
    monkeypatch.setenv("ALPHA_DATA_DIR", str(data_dir))
    result = runner.invoke(
        app, ["ml", "export-input", project_id, experiment_id, str(data_dir / "bundles" / "cli")]
    )
    assert result.exit_code == 0, result.output
    assert SENTENCE in result.output
    as_json = runner.invoke(
        app,
        [
            "ml",
            "export-input",
            project_id,
            experiment_id,
            str(data_dir / "bundles" / "cli2"),
            "--json",
        ],
    )
    assert as_json.exit_code == 0, as_json.output
    assert json.loads(as_json.output)["reserve"]["held_back_bars"] == HELD_PER_SYMBOL * MIN_SYMBOLS


def test_a_store_with_no_held_back_bar_gives_the_same_bundle_as_before(
    cut: World, spy: Spy
) -> None:
    summary, bundle = _export(cut, "unchanged")
    assert sorted(path.name for path in bundle.iterdir()) == ["panel.parquet", "spec.json"]
    assert set(summary) == {
        "status",
        "input_bundle_id",
        "project_id",
        "experiment_id",
        "snapshot_id",
        "snapshot_hash",
        "symbols",
        "sessions",
        "rows",
        "folds",
        "panel_sha256",
        "spec_sha256",
        "worker_contract_validated",
    }
    assert summary["spec_sha256"] == PINNED_SPEC_SHA256
    # The panel is the one the old unbounded read builds.
    data_dir = cut[0]
    reference, _ = _aligned_panel(
        data_dir=data_dir,
        snapshot_id="ml-frozen",
        universe=[f"S{index:02d}" for index in range(MIN_SYMBOLS)],
    )
    reference_path = data_dir / "reference.parquet"
    reference.write_parquet(reference_path)
    assert sha256_file(bundle / "panel.parquet") == sha256_file(reference_path)


def test_an_earlier_user_cutoff_still_works_and_holds_nothing(poisoned: World, cut: World) -> None:
    summary, bundle = _export(poisoned, "earlier", as_of="2023-06-30")
    assert "reserve" not in summary
    assert not (bundle / "reserve.json").exists()
    assert summary["sessions"] == (date(2023, 6, 30) - START).days + 1


def test_a_later_user_cutoff_is_capped_and_said(poisoned: World) -> None:
    summary, bundle = _export(poisoned, "later", as_of="2024-02-01")
    held = (date(2024, 2, 1) - RESERVED_DAY).days + 1
    assert summary["reserve"] == {
        "reserved_start": RESERVED_START,
        "held_back_bars": held * MIN_SYMBOLS,
    }
    assert summary["sessions"] == CUT_N
    assert "Held back" in str(summary["reserve_sentence"])
    assert (bundle / "reserve.json").is_file()
