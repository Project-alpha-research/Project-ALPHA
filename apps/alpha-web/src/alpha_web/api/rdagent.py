"""Read-only RD-Agent receipts. Uses the same local read boundary as /api/runs."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from alpha_web import _rdagent_runs
from alpha_web.api._common import data_dir
from alpha_web.api.rdagent_models import (
    JourneyMissing,
    RdAgentDetail,
    RdAgentRunList,
    StoredJourney,
)

router = APIRouter(prefix="/api/rdagent", tags=["rdagent"])


def _paths() -> tuple[Path, Path]:
    parent = data_dir().resolve().parent
    root = Path(os.environ.get("ALPHA_RDAGENT_RUNS_DIR", str(parent / "runs")))
    ledger = (
        root / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    )  # the CLI default sits in runs/
    return root, ledger


def _read[Result](action: Callable[[], Result]) -> Result:
    try:
        return action()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="The requested RD-Agent record was not found."
        ) from exc
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="The RD-Agent records could not be read safely. Check the recorded files.",
        ) from exc


@router.get("/runs", response_model=RdAgentRunList)
def list_runs() -> RdAgentRunList:
    """List direct-child factor-loop receipts, newest first; no execution or mutation."""
    root, ledger = _paths()
    return _read(lambda: _rdagent_runs.list_runs(root, ledger))


@router.get("/runs/{run_id}", response_model=RdAgentDetail)
def run_detail(run_id: str) -> RdAgentDetail:
    """Select an identity from the run list, never a request-supplied path."""
    root, ledger = _paths()
    return _read(lambda: _rdagent_runs.read_run(root, ledger, run_id))


@router.get(
    "/runs/{run_id}/journeys/{idea_id}",
    response_model=StoredJourney | JourneyMissing,
    response_model_exclude_unset=True,
)
def idea_journey(run_id: str, idea_id: str) -> StoredJourney | JourneyMissing:
    """Read the published steps, or the local command to build a missing journey."""
    root, ledger = _paths()
    return _read(lambda: _rdagent_runs.read_journey(root, ledger, run_id, idea_id))


@router.get(
    "/runs/{run_id}/journeys/{idea_id}/figures/{filename}",
    response_model=bytes,
    response_class=Response,
    responses={200: {"content": {"image/png": {"schema": {"type": "string", "format": "binary"}}}}},
)
def journey_figure(run_id: str, idea_id: str, filename: str) -> Response:
    """Read one published PNG belonging to this idea."""
    root, _ = _paths()
    data = _read(lambda: _rdagent_runs.read_journey_figure(root, run_id, idea_id, filename))
    return Response(data, media_type="image/png")
