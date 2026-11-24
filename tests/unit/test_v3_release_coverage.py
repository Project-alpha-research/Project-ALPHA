"""Focused release coverage for Workstation v3 control and suite contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import control_store as control
from alpha_cli import run_projection
from alpha_cli.control_store import ControlStore
from alpha_cli.main import app
from alpha_core import DataError
from tests.fixtures.control_store_fixtures import mark_project_as_migrated_legacy

NOW = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)


def _experiment(
    tmp_path: Path,
    *,
    universe: list[str] | None = None,
    definition: dict[str, object] | None = None,
    parameter_space: dict[str, object] | None = None,
    stage_config: dict[str, object] | None = None,
    source: str = "git:abc123",
) -> tuple[ControlStore, str, str, str]:
    snapshot_dir = tmp_path / "snapshots" / "frozen"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_manifest = snapshot_dir / "manifest.json"
    if not snapshot_manifest.exists():
        snapshot_manifest.write_text(
            json.dumps({"snapshot_id": "frozen", "symbols": {}}, sort_keys=True),
            encoding="utf-8",
        )
    store = ControlStore(tmp_path)
    project = store.create_project(
        name="Release coverage",
        hypothesis="A causal daily signal persists after costs.",
        falsification_criterion="Reject on failed OOS evidence.",
        at=NOW,
    )
    project_id = str(project["project_id"])
    mark_project_as_migrated_legacy(store, project_id)
    version = store.create_strategy_version(
        project_id,
        strategy_name="ts_momentum",
        source_fingerprint=source,
        definition=definition or {"lookback": 5, "skip": 1, "vol_window": 3},
        parameter_space=parameter_space or {"lookback": [5, 10]},
        at=NOW,
    )
    version_id = str(version["version_id"])
    experiment = store.create_experiment_spec(
        project_id,
        strategy_version_id=version_id,
        snapshot_id="frozen",
        universe=universe or ["SPY", "AAPL"],
        split_policy={"train": 30, "test": 10, "embargo": 2},
        costs={"fee_bps": 0, "slippage_bps": 0},
        seeds={"master": 7},
        stage_config=stage_config or {},
        at=NOW,
    )
    experiment_id = str(experiment["experiment_id"])
    store.seal_holdout(
        project_id,
        experiment_id,
        actor="owner",
        reason="reserve final release-coverage window before research",
        start_date="2025-10-01",
        end_date="2025-12-31",
        at=NOW,
    )
    return store, project_id, version_id, experiment_id


def _publish(
    tmp_path: Path,
    run_id: str,
    *,
    passed: bool = True,
    null_outcome: bool | None = None,
) -> None:
    rdir = tmp_path / "runs" / run_id
    rdir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "run_id": run_id,
        "command": "backtest_run",
        "snapshot_id": "frozen",
        "snapshot_hash": "a" * 64,
        "passed": passed,
    }
    if null_outcome is not None:
        manifest["outcomes"] = [
            {"name": "randomized_price_null", "passed": null_outcome, "detail": {}}
        ]
    (rdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_control_value_store_and_transaction_guards(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="YYYY-MM-DD"):
        control._iso_date("2026-02-30", "date")
    with pytest.raises(DataError, match="canonical"):
        control._iso_date("2026-W14-3", "date")
    nested: object = None
    for _ in range(18):
        nested = [nested]
    with pytest.raises(DataError, match="nesting"):
        control._clean_json(nested, label="nested")
    with pytest.raises(DataError, match="keys"):
        control._clean_json({1: "bad"}, label="mapping")
    with pytest.raises(DataError, match="finite JSON"):
        control._canonical_json({"bad": object()}, "payload")
    with pytest.raises(DataError, match="is not text"):
        control._decode_json(1, "payload")
    with pytest.raises(DataError, match="invalid payload"):
        control._decode_json("{", "payload")
    with pytest.raises(DataError, match="too many values"):
        control._strings(["x"] * 257, "values")
    with pytest.raises(DataError, match="too many values"):
        control._evidence_ids(["00000000-0000-0000-0000-000000000001"] * 257)

    store = ControlStore(tmp_path / "transaction")
    with (
        pytest.raises(DataError, match="transaction failed"),
        store._transaction(write=True) as connection,
    ):
        connection.execute("definitely not SQL")

    target = tmp_path / "target"
    target.mkdir()
    symlink_root = tmp_path / "symlinked" / "control"
    symlink_root.parent.mkdir()
    symlink_root.symlink_to(target, target_is_directory=True)
    with pytest.raises(DataError, match="root must not be a symlink"):
        ControlStore(tmp_path / "symlinked").list_projects()

    database = tmp_path / "directory-db" / "control" / control.DATABASE_NAME
    database.mkdir(parents=True)
    with pytest.raises(DataError, match="database is not a file"):
        ControlStore(tmp_path / "directory-db").list_projects()


def test_control_stage_attempt_job_and_corruption_guards(tmp_path: Path) -> None:
    store, project_id, _version_id, experiment_id = _experiment(tmp_path)
    _publish(tmp_path, "0123456789abcdef")
    with pytest.raises(DataError, match="unsupported development stage"):
        store.link_stage_run(
            project_id,
            experiment_id,
            stage="deployment",
            state="pass",
            run_id="0123456789abcdef",
        )
    with pytest.raises(DataError, match="unsupported development stage"):
        store.append_experiment_stage_state(
            project_id, experiment_id, "deployment", "ready", reason="bad"
        )
    with pytest.raises(DataError, match="unsupported stage state"):
        store.append_experiment_stage_state(
            project_id,
            experiment_id,
            "baseline",
            cast(control.StageState, "green"),
            reason="bad",
        )
    with pytest.raises(DataError, match="candidate freeze"):
        store.append_experiment_stage_state(
            project_id, experiment_id, "candidate", "ready", reason="too early"
        )

    link = store.link_stage_run(
        project_id,
        experiment_id,
        stage="baseline",
        state="queued",
        run_id="0123456789abcdef",
        at=NOW + timedelta(minutes=2),
    )
    with pytest.raises(DataError, match="suite-owned"):
        store.link_stage_run(
            project_id,
            experiment_id,
            stage="baseline",
            state="pass",
            run_id="0123456789abcdef",
        )
    with pytest.raises(DataError, match="unsupported stage state"):
        store.append_stage_state(
            str(link["link_id"]), cast(control.StageState, "green"), reason="bad"
        )
    with pytest.raises(DataError, match="precedes prior event"):
        store.append_stage_state(
            str(link["link_id"]),
            "running",
            reason="backdated",
            at=NOW,
        )

    attempt_id = "00000000-0000-0000-0000-000000000099"
    store.record_attempt(
        project_id,
        experiment_id,
        stage="baseline",
        status="passed",
        config_fingerprint="cfg",
        attempt_id=attempt_id,
    )
    with pytest.raises(DataError, match="already exists"):
        store.record_attempt(
            project_id,
            experiment_id,
            stage="baseline",
            status="passed",
            config_fingerprint="cfg",
            attempt_id=attempt_id,
        )

    job = store.create_job(kind="coverage", request={}, at=NOW + timedelta(minutes=3))
    job_id = str(job["job_id"])
    with pytest.raises(DataError, match="precedes prior job update"):
        store.append_job_event(job_id, event_type="log", payload={}, at=NOW)
    store.set_job_status(
        job_id,
        "failed",
        terminal_error="expected failure",
        at=NOW + timedelta(minutes=4),
    )
    with pytest.raises(DataError, match="terminal job"):
        store.append_job_result(job_id, {}, at=NOW + timedelta(minutes=5))
    with pytest.raises(DataError, match="transition terminal job"):
        store.set_job_status(job_id, "cancelled", at=NOW + timedelta(minutes=5))

    with store._transaction(write=True) as connection:
        connection.execute(
            "DELETE FROM stage_state_events WHERE link_id = ?", (str(link["link_id"]),)
        )
    with pytest.raises(DataError, match="has no events"):
        store.get_project(project_id)


def test_evidence_citation_and_correlation_guards(tmp_path: Path) -> None:
    store, _project_id, _version_id, _experiment_id = _experiment(tmp_path)
    run_id = "0123456789abcdef"
    _publish(tmp_path, run_id)
    rdir = tmp_path / "runs" / run_id
    pl.DataFrame({"symbol": ["AAPL", "MSFT"], "score": [1.0, 2.0]}).write_parquet(
        rdir / "scores.parquet"
    )
    (rdir / "notes.txt").write_text("audit", encoding="utf-8")

    with pytest.raises(DataError, match="do not accept a row selector"):
        store._validate_evidence_citation(
            run_id=run_id,
            artifact="manifest.json",
            field="passed",
            row_selector={"row_index": 0},
        )
    with pytest.raises(DataError, match="manifest.json or Parquet"):
        store._validate_evidence_citation(
            run_id=run_id, artifact="notes.txt", field="x", row_selector={}
        )
    with pytest.raises(DataError, match="does not exist"):
        store._validate_evidence_citation(
            run_id=run_id,
            artifact="scores.parquet",
            field="missing",
            row_selector={"row_index": 0},
        )
    with pytest.raises(DataError, match="outside the artifact"):
        store._validate_evidence_citation(
            run_id=run_id,
            artifact="scores.parquet",
            field="score",
            row_selector={"row_index": 10},
        )
    with pytest.raises(DataError, match="selector field"):
        store._validate_evidence_citation(
            run_id=run_id,
            artifact="scores.parquet",
            field="score",
            row_selector={"missing": "AAPL"},
        )
    with pytest.raises(DataError, match="must be scalar"):
        store._validate_evidence_citation(
            run_id=run_id,
            artifact="scores.parquet",
            field="score",
            row_selector={"symbol": ["AAPL"]},
        )
    with pytest.raises(DataError, match="exactly one row"):
        store._validate_evidence_citation(
            run_id=run_id, artifact="scores.parquet", field="score", row_selector={}
        )

    correlation: dict[str, object] = {
        "assets": ["AAPL", "MSFT"],
        "timeframe": "1d",
        "metric_name": "correlation",
        "metric_value": 0.4,
        "metric_unit": "coefficient",
        "run_id": run_id,
        "artifact": "scores.parquet",
        "row_selector": {
            "sample_count": 2,
            "aligned_oos": True,
            "frequency": "1d",
            "association_not_causation": True,
            "oos_start": "2026-01-01",
            "oos_end": "2026-06-30",
            "snapshot_hash": "a" * 64,
        },
    }
    for update, message in (
        ({"assets": ["AAPL"]}, "at least two assets"),
        ({"artifact": "manifest.json"}, "Parquet report"),
        ({"metric_name": None}, "explicit metric"),
        (
            {
                "row_selector": {
                    **cast(dict[str, object], correlation["row_selector"]),
                    "oos_end": "2025-01-01",
                }
            },
            "ordered aligned OOS",
        ),
        (
            {
                "row_selector": {
                    **cast(dict[str, object], correlation["row_selector"]),
                    "snapshot_hash": "bad",
                }
            },
            "64-hex",
        ),
    ):
        with pytest.raises(DataError, match=message):
            store._validate_correlation_evidence(**{**correlation, **update})  # type: ignore[arg-type]


def test_project_cli_plain_and_error_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    empty_jobs = runner.invoke(app, ["project", "job-list"])
    empty_jobs_json = runner.invoke(app, ["project", "job-list", "--json"])
    assert "no development jobs" in empty_jobs.output
    assert json.loads(empty_jobs_json.output) == []


def test_legacy_rule_fold_projection_is_typed_and_skips_malformed_entries(
    tmp_path: Path,
) -> None:
    manifest: dict[str, object] = {
        "folds": [
            {
                "index": 3,
                "train_start": datetime(2025, 1, 1, tzinfo=UTC).timestamp(),
                "train_end": datetime(2025, 3, 31, tzinfo=UTC).timestamp(),
                "test_start": datetime(2025, 4, 1, tzinfo=UTC).timestamp(),
                "test_end": datetime(2025, 4, 30, tzinfo=UTC).timestamp(),
            },
            "not-an-object",
            {"index": "invalid", "train_start": "missing required boundaries"},
        ]
    }

    assert run_projection._folds(tmp_path, manifest, 10) == [
        {
            "fold": 3,
            "semantics": "fixed_rule_evaluation_no_refit",
            "train_start": datetime(2025, 1, 1, tzinfo=UTC).timestamp(),
            "train_end": datetime(2025, 3, 31, tzinfo=UTC).timestamp(),
            "validation_start": None,
            "validation_end": None,
            "test_start": datetime(2025, 4, 1, tzinfo=UTC).timestamp(),
            "test_end": datetime(2025, 4, 30, tzinfo=UTC).timestamp(),
        }
    ]
