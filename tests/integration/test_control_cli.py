"""CLI projections for the durable job commands (``alpha project job-*``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli.control_store import ControlStore, parse_timestamp
from alpha_cli.main import app

runner = CliRunner()


def test_job_cli_projections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    project = ControlStore(tmp_path).create_project(
        name="CLI operations",
        hypothesis="A testable hypothesis.",
        falsification_criterion="Reject on failed OOS.",
        at=parse_timestamp("2026-07-19T07:00:00Z"),
    )
    project_id = str(project["project_id"])

    created_job = runner.invoke(
        app,
        [
            "project",
            "job-create",
            "validation_suite",
            "--project-id",
            project_id,
            "--request-json",
            '{"family":"bootstrap"}',
            "--json",
        ],
    )
    assert created_job.exit_code == 0, created_job.output
    job_id = json.loads(created_job.output)["job_id"]
    running = runner.invoke(app, ["project", "job-status", job_id, "running", "--json"])
    event = runner.invoke(
        app,
        [
            "project",
            "job-event",
            job_id,
            "progress",
            "--payload-json",
            '{"completed":1,"total":3}',
            "--json",
        ],
    )
    failed = runner.invoke(
        app,
        [
            "project",
            "job-status",
            job_id,
            "failed",
            "--terminal-error",
            "worker stopped",
            "--json",
        ],
    )
    shown = runner.invoke(app, ["project", "job-show", job_id, "--json"])
    paged = runner.invoke(
        app,
        [
            "project",
            "job-show",
            job_id,
            "--event-limit",
            "2",
            "--event-offset",
            "1",
            "--json",
        ],
    )
    tailed = runner.invoke(
        app,
        ["project", "job-show", job_id, "--event-limit", "2", "--event-tail", "--json"],
    )
    listed = runner.invoke(app, ["project", "job-list", "--json"])
    assert all(
        result.exit_code == 0 for result in (running, event, failed, shown, paged, tailed, listed)
    )
    assert json.loads(shown.output)["last_sequence"] == 4
    assert [row["sequence"] for row in json.loads(paged.output)["events"]] == [2, 3]
    tail = json.loads(tailed.output)
    assert [row["sequence"] for row in tail["events"]] == [3, 4]
    assert tail["event_total"] == 4
    assert tail["events_has_more"] is True

    interrupted = runner.invoke(app, ["project", "job-create", "kronos_eval", "--json"])
    interrupted_id = json.loads(interrupted.output)["job_id"]
    cancellation = runner.invoke(
        app,
        [
            "project",
            "job-cancel",
            interrupted_id,
            "--actor",
            "owner",
            "--reason",
            "stop queued work",
            "--json",
        ],
    )
    reconciled = runner.invoke(app, ["project", "job-reconcile", "--json"])
    assert interrupted.exit_code == 0, interrupted.output
    assert cancellation.exit_code == 0, cancellation.output
    assert json.loads(cancellation.output)["status"] == "cancellation_requested"
    assert reconciled.exit_code == 0, reconciled.output
    assert json.loads(reconciled.output) == []  # fresh queued work is never auto-failed

    plain_jobs = runner.invoke(app, ["project", "job-list"])
    assert plain_jobs.exit_code == 0


def test_empty_plain_job_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    jobs = runner.invoke(app, ["project", "job-list"])
    assert jobs.output.strip() == "no development jobs"
