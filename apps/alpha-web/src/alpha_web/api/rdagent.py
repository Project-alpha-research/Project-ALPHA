"""Read-only RD-Agent receipts. Uses the same local read boundary as /api/runs."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException

from alpha_web import _rdagent_runs
from alpha_web.api._common import data_dir
from alpha_web.api.rdagent_models import RdAgentDetail, RdAgentRunList

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
            status_code=404, detail="The recorded RD-Agent run was not found."
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
