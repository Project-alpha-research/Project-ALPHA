"""``alpha project job-*`` — generic durable job commands (ML lab, job monitor)."""

from __future__ import annotations

from typing import cast

import typer

from alpha_cli._cli_json import emit as _emit
from alpha_cli._cli_json import json_object_option as _object
from alpha_cli.control_store import ControlStore
from alpha_cli.job_rows import JobStatus
from alpha_cli.job_store import JobStore
from alpha_core import DataError
from alpha_core.config import AlphaSettings

jobs_app = typer.Typer(help="Durable job commands.")


def _store() -> ControlStore:
    return ControlStore(AlphaSettings().data_dir)


def _jobs() -> JobStore:
    """The generic job commands (used by the ML lab and the job monitor) skip the old store."""
    return JobStore(AlphaSettings().data_dir)


@jobs_app.command("job-create")
def job_create(
    kind: str,
    request_json: str = typer.Option("{}"),
    project_id: str | None = typer.Option(None),
    experiment_id: str | None = typer.Option(None),
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
) -> None:
    """Create a durable queued development job."""
    try:
        request = _object(request_json, "--request-json")
        if project_id is None and experiment_id is None:
            row = _jobs().create_job(kind=kind, request=request)
        else:  # A job bound to a research-case project stays on the old store.
            row = _store().create_job(
                kind=kind, request=request, project_id=project_id, experiment_id=experiment_id
            )
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(row, json_out=json_out, fallback=f"queued job {row['job_id']}")


@jobs_app.command("job-status")
def job_status(
    job_id: str,
    status: str,
    result_run_id: str | None = typer.Option(None),
    terminal_error: str | None = typer.Option(None),
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
) -> None:
    """Advance a generic durable job lifecycle."""
    try:
        store = _jobs()
        if status in {"succeeded", "failed", "cancelled"}:
            job = store.get_job(job_id, event_limit=1)
            if job["kind"] == "research:event-study":
                raise DataError(
                    "research job terminal status is owned by its executor; "
                    "generic job-status cannot release research capacity"
                )
        row = store.set_job_status(
            job_id,
            cast(JobStatus, status),
            result_run_id=result_run_id,
            terminal_error=terminal_error,
        )
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(row, json_out=json_out, fallback=f"job {job_id} {row['status']}")


@jobs_app.command("job-capacity")
def job_capacity(
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
) -> None:
    """Show exact occupancy of the shared Qlib/Kronos heavyweight class."""
    row = _jobs().heavyweight_job_capacity()
    _emit(
        row,
        json_out=json_out,
        fallback=f"heavyweight jobs {row['active_count']}/{row['limit']}",
    )


@jobs_app.command("job-event")
def job_event(
    job_id: str,
    event_type: str,
    payload_json: str = typer.Option("{}"),
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
) -> None:
    """Append a heartbeat, progress, or log event to a live job."""
    try:
        row = _jobs().append_job_event(
            job_id,
            event_type=event_type,
            payload=_object(payload_json, "--payload-json"),
        )
        if event_type == "heartbeat":
            row = {
                **row,
                "cancel_requested": _jobs().job_cancellation_requested(job_id),
            }
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(row, json_out=json_out, fallback=f"job {job_id} event {row['sequence']}")


@jobs_app.command("job-show")
def job_show(
    job_id: str,
    event_limit: int = typer.Option(200, min=1, max=500),
    event_offset: int = typer.Option(0, min=0),
    event_tail: bool = typer.Option(
        False,
        "--event-tail",
        help="page backward from the newest events while returning rows chronologically",
    ),
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
) -> None:
    """Show a durable job and a bounded window of its append-only event journal."""
    try:
        row = _jobs().get_job(
            job_id,
            event_limit=event_limit,
            event_offset=event_offset,
            event_tail=event_tail,
        )
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(row, json_out=json_out, fallback=f"job {job_id} {row['status']}")


@jobs_app.command("job-cancel")
def job_cancel(
    job_id: str,
    actor: str = typer.Option(...),
    reason: str = typer.Option(...),
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
) -> None:
    """Persist an idempotent cancellation request for the owning durable worker to observe."""
    try:
        row = _jobs().request_job_cancellation(job_id, actor=actor, reason=reason)
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(row, json_out=json_out, fallback=f"job {job_id} {row['status']}")


@jobs_app.command("job-cancel-requested")
def job_cancel_requested(
    job_id: str,
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
) -> None:
    """Project whether the owning worker must honour an audited cancellation request."""
    try:
        requested = _jobs().job_cancellation_requested(job_id)
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc
    row = {"job_id": job_id, "cancel_requested": requested}
    _emit(
        row,
        json_out=json_out,
        fallback=f"job {job_id} cancel requested: {str(requested).lower()}",
    )


@jobs_app.command("job-list")
def job_list(
    limit: int = typer.Option(100, min=1, max=500),
    offset: int = typer.Option(0, min=0),
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
) -> None:
    """List durable development jobs."""
    try:
        rows = _jobs().list_jobs(limit=limit, offset=offset)
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if json_out:
        _emit(rows, json_out=True, fallback="")
        return
    if not rows:
        typer.echo("no development jobs")
        return
    for row in rows:
        typer.echo(f"{row['job_id']} {row['status']} {row['kind']}")


@jobs_app.command("job-reconcile")
def job_reconcile(
    reason: str = typer.Option("process restarted before terminal job status"),
    stale_after_seconds: int = typer.Option(60, min=30, max=86_400),
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
) -> None:
    """Mark only stale-heartbeat queued/running journals failed after confirmed interruption."""
    try:
        rows = _jobs().reconcile_interrupted_jobs(
            reason=reason,
            stale_after_seconds=stale_after_seconds,
        )
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(rows, json_out=json_out, fallback=f"reconciled {len(rows)} interrupted jobs")


__all__ = ["jobs_app"]
