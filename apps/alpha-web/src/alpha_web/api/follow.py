"""``/api/follow/today`` and ``/{id}``: what the owner follows on paper (read-only relay).

Both routes run ``alpha follow today|show --json`` as a subprocess and relay the answer. The web
backend never opens the ``forward/`` folder itself. No route starts, updates or stops a follow:
those stay owner-only CLI commands.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path

from alpha_web._catalog import _run_json
from alpha_web.api._common import data_dir
from alpha_web.api.models import FollowShow, FollowToday

router = APIRouter(prefix="/api/follow", tags=["follow"])

_TIMEOUT_SECONDS = 30.0
_FOLLOW_ID = r"^[0-9a-f]{4,12}$"


def _relay(args: list[str]) -> dict[str, Any]:
    try:
        result: dict[str, Any] = _run_json(
            args, data_dir=data_dir(), timeout_seconds=_TIMEOUT_SECONDS
        )
        return result
    except RuntimeError as exc:  # the CLI's own words, or a timeout
        status = 504 if "timed out" in str(exc) else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/today", response_model=FollowToday)
def today() -> dict[str, Any]:
    """Relay ``alpha follow today --json``: one row per active follow, in groups."""
    return _relay(["follow", "today", "--json"])


@router.get("/{follow_id}", response_model=FollowShow)
def show(follow_id: Annotated[str, Path(pattern=_FOLLOW_ID)]) -> dict[str, Any]:
    """Relay ``alpha follow show <id> --json``; the id is checked as 4 to 12 hex first."""
    return _relay(["follow", "show", follow_id, "--json"])
