"""``/api/desk/*``: the Workstation frame's reads (recent tests, status dot). Read-only."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from alpha_web import _desk
from alpha_web.api._common import data_dir
from alpha_web.api.models.desk import DeskRunList, DeskStatus

router = APIRouter(prefix="/api/desk", tags=["desk"])


@router.get("/runs", response_model=DeskRunList)
def desk_runs(
    limit: Annotated[int, Query(ge=1, le=200)] = 10,
    spark: bool = True,
) -> dict[str, Any]:
    """The newest stored runs with idea, asset, trades, out-of-sample Sharpe and evidence word."""
    return _desk.recent_runs(data_dir=data_dir(), limit=limit, spark=spark)


@router.get("/status", response_model=DeskStatus)
def desk_status() -> dict[str, Any]:
    """The reserved-period start and the last nightly run, relayed from `alpha nightly status`."""
    return _desk.desk_status(data_dir=data_dir())
