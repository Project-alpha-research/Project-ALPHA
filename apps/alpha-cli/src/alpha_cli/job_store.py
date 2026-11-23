"""Durable jobs: the seam the ML lab and the job monitor use (`alpha project job-*`).

These commands reach the `jobs` tables here, never through the old control store. The old
`ControlStore` delegates its job methods to this module until it is deleted.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alpha_cli import home_db
from alpha_cli.artifact_contract import verify_manifest_artifacts
from alpha_cli.home_db import canonical_json, required_text, stamp
from alpha_cli.job_rows import (
    JOB_EVENT_TYPES,
    JOB_STATUSES,
    RESERVED_JOB_PREFIXES,
    SCHEMA,
    TABLES,
    TERMINAL_JOB_STATUSES,
    TRANSITIONS,
    JobStatus,
    active_job_cancellation,
    fail_stale_job,
    has_native_claim,
    heavyweight_occupancy,
    insert_job,
    job_event_view,
    job_view,
    live_job,
    require_job,
    require_monotonic,
)
from alpha_cli.run_store import find_run_dir, read_manifest
from alpha_core import DataError


class JobStore:
    """The job seam over one data home's SQLite file."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)

    def _transaction(self, *, write: bool) -> AbstractContextManager[sqlite3.Connection]:
        return home_db.transaction(self._data_dir, SCHEMA, TABLES, write=write)

    def create_job(
        self,
        *,
        kind: str,
        request: Mapping[str, object],
        job_id: str | None = None,
        at: datetime | None = None,
    ) -> dict[str, object]:
        """Create a generic queued job; reserved suite and research kinds are refused."""
        jid = home_db.new_uuid(job_id, "job_id")
        timestamp = stamp(at)
        request_json = canonical_json(home_db.json_object(request, "job request"), "job request")
        clean_kind = required_text(kind, "job kind", max_length=100)
        if clean_kind.startswith(RESERVED_JOB_PREFIXES):
            raise DataError("reserved job kinds require their governed internal executor")
        with self._transaction(write=True) as connection:
            if connection.execute("SELECT 1 FROM jobs WHERE job_id = ?", (jid,)).fetchone():
                raise DataError(f"job {jid!r} already exists")
            return insert_job(
                connection,
                job_id=jid,
                kind=clean_kind,
                project_id=None,
                experiment_id=None,
                request_json=request_json,
                timestamp=timestamp,
            )

    def heavyweight_job_capacity(self) -> dict[str, object]:
        """Return exact shared heavyweight occupancy without a paginated job scan."""
        with self._transaction(write=False) as connection:
            return heavyweight_occupancy(connection)

    def request_job_cancellation(
        self, job_id: str, *, actor: str, reason: str, at: datetime | None = None
    ) -> dict[str, str]:
        """Persist an idempotent cancellation request without signalling an unresolved PID."""
        payload = {
            "actor": required_text(actor, "job cancellation actor", max_length=200),
            "reason": required_text(reason, "job cancellation reason"),
        }
        timestamp = stamp(at)
        with self._transaction(write=True) as connection:
            job = require_job(connection, job_id)
            if str(job["status"]) in TERMINAL_JOB_STATUSES:
                return {"job_id": str(job["job_id"]), "status": "already_terminal"}
            if active_job_cancellation(connection, job_id):
                return {"job_id": str(job["job_id"]), "status": "cancellation_requested"}
            require_monotonic(job["updated_at"], timestamp, "cancellation timestamp")
            sequence = int(job["last_sequence"]) + 1
            connection.execute(
                "INSERT INTO job_events VALUES (?, ?, 'cancel_requested', ?, ?)",
                (job_id, sequence, timestamp, canonical_json(payload, "job cancellation event")),
            )
            connection.execute(
                "UPDATE jobs SET updated_at = ?, last_sequence = ? WHERE job_id = ?",
                (timestamp, sequence, job_id),
            )
        return {"job_id": job_id, "status": "cancellation_requested"}

    def job_cancellation_requested(self, job_id: str) -> bool:
        """Return whether a durable cancellation request exists for a nonterminal job."""
        with self._transaction(write=False) as connection:
            job = require_job(connection, job_id)
            if str(job["status"]) in TERMINAL_JOB_STATUSES:
                return False
            return active_job_cancellation(connection, job_id)

    def _append(
        self, job_id: str, event_type: str, payload: Mapping[str, object], at: datetime | None
    ) -> dict[str, object]:
        """Append one event (or the result) to a live job and advance its durable cursor."""
        is_result = event_type == "result"
        label = "job result" if is_result else "job event payload"
        clean_payload = home_db.json_object(payload, label)
        timestamp = stamp(at)
        with self._transaction(write=True) as connection:
            job = live_job(connection, job_id, "append to")
            require_monotonic(
                job["updated_at"], timestamp, "result timestamp" if is_result else "event timestamp"
            )
            sequence = int(job["last_sequence"]) + 1
            connection.execute(
                "INSERT INTO job_events VALUES (?, ?, ?, ?, ?)",
                (job_id, sequence, event_type, timestamp, canonical_json(clean_payload, label)),
            )
            heartbeat = timestamp if event_type == "heartbeat" else job["heartbeat_at"]
            connection.execute(
                """UPDATE jobs SET updated_at = ?, heartbeat_at = ?, last_sequence = ?
                WHERE job_id = ?""",
                (timestamp, heartbeat, sequence, job_id),
            )
            row = connection.execute(
                "SELECT * FROM job_events WHERE job_id = ? AND sequence = ?", (job_id, sequence)
            ).fetchone()
        if row is None:  # pragma: no cover
            raise DataError(f"control store failed to persist {label.removesuffix(' payload')}")
        return job_event_view(row)

    def append_job_event(
        self,
        job_id: str,
        *,
        event_type: str,
        payload: Mapping[str, object],
        at: datetime | None = None,
    ) -> dict[str, object]:
        """Append a bounded non-status job event and advance the durable cursor."""
        clean_type = required_text(event_type, "job event type", max_length=20)
        if clean_type not in JOB_EVENT_TYPES - {"created", "status", "result", "cancel_requested"}:
            raise DataError(f"unsupported append-only job event type {event_type!r}")
        return self._append(job_id, clean_type, payload, at)

    def append_job_result(
        self, job_id: str, payload: Mapping[str, object], *, at: datetime | None = None
    ) -> dict[str, object]:
        """Append the typed result payload before a job enters its terminal state."""
        return self._append(job_id, "result", payload, at)

    def set_job_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        result_run_id: str | None = None,
        terminal_error: str | None = None,
        at: datetime | None = None,
    ) -> dict[str, object]:
        """Transition a job and append the transition to its event journal atomically."""
        clean_status = required_text(status, "job status", max_length=16)
        if clean_status not in JOB_STATUSES:
            raise DataError(f"unsupported job status {status!r}")
        if result_run_id is not None:
            run_dir = find_run_dir(self._data_dir, result_run_id)
            if run_dir is None:
                raise DataError(f"unknown completed run {result_run_id!r}")
            verify_manifest_artifacts(run_dir, read_manifest(run_dir))
        clean_error = home_db.optional_text(terminal_error, "job terminal error")
        if clean_status == "failed" and clean_error is None:
            raise DataError("failed job requires terminal_error")
        if clean_status != "failed" and clean_error is not None:
            raise DataError("terminal_error is only valid for failed jobs")
        if clean_status != "succeeded" and result_run_id is not None:
            raise DataError("result_run_id is only valid for succeeded jobs")
        timestamp = stamp(at)
        with self._transaction(write=True) as connection:
            job = live_job(connection, job_id, "transition")
            prior_status = str(job["status"])
            if clean_status not in TRANSITIONS[prior_status]:
                raise DataError(f"invalid job transition {prior_status!r} -> {clean_status!r}")
            require_monotonic(job["updated_at"], timestamp, "status timestamp")
            sequence = int(job["last_sequence"]) + 1
            payload = {"from": prior_status, "to": clean_status}
            connection.execute(
                "INSERT INTO job_events VALUES (?, ?, 'status', ?, ?)",
                (job_id, sequence, timestamp, canonical_json(payload, "job status event")),
            )
            connection.execute(
                """UPDATE jobs SET status = ?, updated_at = ?, heartbeat_at = ?,
                result_run_id = ?, terminal_error = ?, last_sequence = ? WHERE job_id = ?""",
                (clean_status, timestamp, timestamp, result_run_id, clean_error, sequence, job_id),
            )
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:  # pragma: no cover
            raise DataError("control store failed to persist job status")
        return job_view(row)

    def get_job(
        self,
        job_id: str,
        *,
        event_limit: int = 200,
        event_offset: int = 0,
        event_tail: bool = False,
    ) -> dict[str, object]:
        """Read one job and a SQL-bounded chronological window of its event journal."""
        event_limit, event_offset = home_db.page(event_limit, event_offset)
        if not isinstance(event_tail, bool):
            raise DataError("control event_tail must be a boolean")
        order = "DESC" if event_tail else "ASC"
        with self._transaction(write=False) as connection:
            job = job_view(require_job(connection, job_id))
            events = connection.execute(
                f"SELECT * FROM job_events WHERE job_id = ? ORDER BY sequence {order} "
                "LIMIT ? OFFSET ?",
                (job["job_id"], event_limit, event_offset),
            ).fetchall()
        if event_tail:
            events.reverse()
        event_total = job["last_sequence"]
        if isinstance(event_total, bool) or not isinstance(event_total, int) or event_total < 0:
            raise DataError("control job has an invalid last_sequence invariant")
        more = event_offset + len(events) < event_total
        return {
            **job,
            "events": [job_event_view(row) for row in events],
            "event_total": event_total,
            "event_limit": event_limit,
            "event_offset": event_offset,
            "event_tail": event_tail,
            "events_has_more": more,
            "events_truncated": more,
        }

    def list_jobs(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, object]]:
        """Return bounded durable job summaries, newest first."""
        limit, offset = home_db.page(limit, offset)
        with self._transaction(write=False) as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY updated_at DESC, job_id LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [job_view(row) for row in rows]

    def reconcile_interrupted_jobs(
        self,
        *,
        reason: str = "process restarted before terminal job status",
        stale_after_seconds: int = 60,
        at: datetime | None = None,
    ) -> list[dict[str, object]]:
        """Fail stale non-research journals; research needs a trustworthy owner-host binding."""
        clean_reason = required_text(reason, "job reconciliation reason")
        if isinstance(stale_after_seconds, bool) or not 30 <= stale_after_seconds <= 86_400:
            raise DataError("job stale_after_seconds must be in 30..86400")
        current = datetime.now(UTC) if at is None else at
        timestamp = stamp(current)
        stale_before = stamp(current - timedelta(seconds=stale_after_seconds))
        reconciled: list[dict[str, object]] = []
        with self._transaction(write=True) as connection:
            rows = connection.execute(
                """SELECT * FROM jobs WHERE status IN ('queued', 'running') AND heartbeat_at <= ?
                ORDER BY created_at""",
                (stale_before,),
            ).fetchall()
            for job in rows:
                # A native claim keeps its capacity until the protected owner records cleanup.
                # A local PID miss cannot prove a remote research owner stopped.
                if has_native_claim(connection, str(job["job_id"])):
                    continue
                if job["kind"] == "research:event-study":
                    continue
                reconciled.append(fail_stale_job(connection, job, timestamp, clean_reason))
        return reconciled
