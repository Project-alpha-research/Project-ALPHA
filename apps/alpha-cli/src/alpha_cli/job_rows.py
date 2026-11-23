"""The durable job tables (`jobs`, `job_events`): their fresh-home schema and row rules.

An old home keeps its tables as they are. A fresh home gets them without the old foreign keys to
the research-case tables (`projects`, `experiment_specs`), which it does not have. `job_store`
and, until it is deleted, the old `ControlStore` share these row rules.
"""

from __future__ import annotations

import sqlite3
from typing import Final, Literal, cast

from alpha_cli import home_db
from alpha_cli.home_db import canonical_json, decode_json
from alpha_cli.job_capacity import HEAVYWEIGHT_JOB_CAPACITY, HEAVYWEIGHT_JOB_KINDS
from alpha_core import DataError

type JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
JOB_STATUSES: Final = frozenset({"queued", "running", "succeeded", "failed", "cancelled"})
JOB_EVENT_TYPES: Final = frozenset(
    {"created", "status", "heartbeat", "progress", "log", "result", "cancel_requested"}
)
TERMINAL_JOB_STATUSES: Final = frozenset({"succeeded", "failed", "cancelled"})
RESERVED_JOB_PREFIXES: Final = ("suite:", "research:")
TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "queued": frozenset({"running", "failed", "cancelled"}),
    "running": frozenset({"succeeded", "failed", "cancelled"}),
}
TABLES: Final = ("jobs", "job_events")
SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    project_id TEXT,
    experiment_id TEXT,
    request_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    result_run_id TEXT,
    terminal_error TEXT,
    last_sequence INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS job_events (
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (job_id, sequence)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_job_project ON jobs(project_id, created_at);
"""


def job_view(row: sqlite3.Row) -> dict[str, object]:
    result = dict(row)
    result["request"] = decode_json(result.pop("request_json"), "job request")
    return result


def job_event_view(row: sqlite3.Row) -> dict[str, object]:
    result = dict(row)
    result["payload"] = decode_json(result.pop("payload_json"), "job event payload")
    return result


def require_job(connection: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    jid = home_db.canonical_uuid(job_id, "job_id")
    row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (jid,)).fetchone()
    if row is None:
        raise DataError(f"unknown control job {jid!r}")
    return cast(sqlite3.Row, row)


def has_native_claim(connection: sqlite3.Connection, job_id: str) -> bool:
    sql = "SELECT 1 FROM job_events WHERE job_id=? AND event_type='native_claim' LIMIT 1"
    return connection.execute(sql, (job_id,)).fetchone() is not None


def require_monotonic(prior: object, current: str, field: str) -> None:
    if not isinstance(prior, str) or current < prior:
        raise DataError(f"control {field} precedes prior job update")


def active_job_cancellation(connection: sqlite3.Connection, job_id: str) -> bool:
    """Return whether the latest cancellation has not been superseded by a resume."""
    rows = connection.execute(
        """SELECT sequence, event_type, payload_json FROM job_events
        WHERE job_id = ? AND event_type IN ('cancel_requested', 'status')
        ORDER BY sequence""",
        (job_id,),
    ).fetchall()
    last_cancel = last_resume = 0
    for row in rows:
        if row["event_type"] == "cancel_requested":
            last_cancel = int(row["sequence"])
            continue
        payload = decode_json(row["payload_json"], "job status event")
        if isinstance(payload, dict) and payload.get("resume") is True:
            last_resume = int(row["sequence"])
    return last_cancel > last_resume


def insert_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    kind: str,
    project_id: str | None,
    experiment_id: str | None,
    request_json: str,
    timestamp: str,
) -> dict[str, object]:
    """Insert one queued job and its `created` event, inside the shared heavyweight capacity."""
    if kind in HEAVYWEIGHT_JOB_KINDS:
        heavyweight_kinds = sorted(HEAVYWEIGHT_JOB_KINDS)
        placeholders = ",".join("?" for _ in heavyweight_kinds)
        active_rows = connection.execute(
            f"""SELECT job_id, kind FROM jobs
            WHERE status IN ('queued', 'running') AND kind IN ({placeholders})
            ORDER BY created_at LIMIT ?""",
            [*heavyweight_kinds, HEAVYWEIGHT_JOB_CAPACITY],
        ).fetchall()
        if len(active_rows) >= HEAVYWEIGHT_JOB_CAPACITY:
            active = active_rows[0]
            raise DataError(
                f"heavyweight job capacity is occupied by {active['kind']} job {active['job_id']}"
            )
    connection.execute(
        "INSERT INTO jobs VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, NULL, NULL, 1)",
        (job_id, kind, project_id, experiment_id, request_json, timestamp, timestamp, timestamp),
    )
    connection.execute(
        "INSERT INTO job_events VALUES (?, 1, 'created', ?, ?)",
        (job_id, timestamp, canonical_json({"status": "queued"}, "job event")),
    )
    row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:  # pragma: no cover
        raise DataError("control store failed to persist job")
    return job_view(row)


def live_job(connection: sqlite3.Connection, job_id: str, verb: str) -> sqlite3.Row:
    """A job that is neither natively owned nor terminal; refuses anything else."""
    if has_native_claim(connection, job_id):
        raise DataError("native process ownership requires its protected lifecycle operation")
    job = require_job(connection, job_id)
    if job["status"] in TERMINAL_JOB_STATUSES:
        raise DataError(f"cannot {verb} terminal job {job_id!r}")
    return job


def fail_stale_job(
    connection: sqlite3.Connection, job: sqlite3.Row, timestamp: str, reason: str
) -> dict[str, object]:
    """Mark one stale queued or running job failed, with its `status` event."""
    require_monotonic(job["updated_at"], timestamp, "reconciliation timestamp")
    sequence = int(job["last_sequence"]) + 1
    payload = {"from": job["status"], "to": "failed", "reason": reason}
    connection.execute(
        "INSERT INTO job_events VALUES (?, ?, 'status', ?, ?)",
        (job["job_id"], sequence, timestamp, canonical_json(payload, "job reconciliation event")),
    )
    connection.execute(
        """UPDATE jobs SET status = 'failed', updated_at = ?, heartbeat_at = ?,
        terminal_error = ?, last_sequence = ? WHERE job_id = ?""",
        (timestamp, timestamp, reason, sequence, job["job_id"]),
    )
    row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job["job_id"],)).fetchone()
    if row is None:  # pragma: no cover
        raise DataError("control store lost a job during reconciliation")
    return job_view(row)


def heavyweight_occupancy(connection: sqlite3.Connection) -> dict[str, object]:
    """Exact shared heavyweight occupancy without a paginated job scan."""
    heavyweight_kinds = sorted(HEAVYWEIGHT_JOB_KINDS)
    placeholders = ",".join("?" for _ in heavyweight_kinds)
    rows = connection.execute(
        f"""SELECT job_id, kind, status, created_at FROM jobs
        WHERE status IN ('queued', 'running') AND kind IN ({placeholders})
        ORDER BY created_at, job_id""",
        heavyweight_kinds,
    ).fetchall()
    active = [dict(row) for row in rows]
    return {
        "capacity_class": "heavyweight",
        "limit": HEAVYWEIGHT_JOB_CAPACITY,
        "active_count": len(active),
        "busy": len(active) >= HEAVYWEIGHT_JOB_CAPACITY,
        "active_jobs": active,
    }
