"""``/api/recent-runs``: the newest stored runs for the Overview's recent-tests table. Read-only."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from alpha_web import _recent_runs
from alpha_web.api._common import data_dir
from alpha_web.api.models.recent_runs import RecentRunList

router = APIRouter(prefix="/api", tags=["runs"])


@router.get("/recent-runs", response_model=RecentRunList)
def recent_runs(
    limit: Annotated[int, Query(ge=1, le=200)] = 10,
    spark: bool = True,
) -> dict[str, Any]:
    """The newest stored runs with idea, asset, trades, out-of-sample Sharpe and evidence word."""
    return _recent_runs.recent_runs(data_dir=data_dir(), limit=limit, spark=spark)
