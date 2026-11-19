"""``/api/market/overview``: stored bars summarised for the Market screen (read-only)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query

from alpha_web._catalog import _run_json
from alpha_web.api._common import data_dir
from alpha_web.api.models import MarketOverview

router = APIRouter(prefix="/api/market", tags=["market"])

#: The CLI reads up to 200 assets from disk, so allow more than the default 60 s.
_TIMEOUT_SECONDS = 120.0


@router.get("/overview", response_model=MarketOverview)
def overview(
    store: Annotated[str, Query(pattern=r"^(1D|[1-9][0-9]?m|[1-9][0-9]?h)$")] = "1D",
    window: Literal["30", "90", "365"] = "90",
    limit: Annotated[int, Query(ge=1, le=30)] = 15,
) -> dict[str, Any]:
    """Relay ``alpha data market-overview``: the assets with the highest median traded value."""
    args = [
        "data",
        "market-overview",
        "--store",
        store,
        "--window",
        window,
        "--limit",
        str(limit),
        "--json",
    ]
    try:
        result: dict[str, Any] = _run_json(
            args, data_dir=data_dir(), timeout_seconds=_TIMEOUT_SECONDS
        )
        return result
    except RuntimeError as exc:  # unknown store or unreadable data: the CLI's own text
        raise HTTPException(status_code=409, detail=str(exc)) from exc
