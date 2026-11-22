"""``/api/market/overview``: stored bars summarised for the Market screen (read-only)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query

from alpha_web._catalog import _run_json
from alpha_web.api._common import data_dir
from alpha_web.api.models import MarketOverview

_CACHE_SIZE = 8
_cache: dict[tuple[object, ...], dict[str, Any]] = {}


def _fingerprint(root: Path) -> tuple[tuple[str, int, int], ...]:
    """Name, change time and size of every stored bar, action, pull-record and promotion file.

    The overview reads prices adjusted by the stored corporate actions, so a changed action or
    pull-record file must change the key just as a changed bar file does. A promotion marker
    (a series being replaced) appears and disappears, so a cached answer never hides or keeps it.
    """
    files = sorted(
        path
        for folder in ("bars", "actions", "provenance", "promotions")
        for path in root.glob(f"store*/{folder}/**/*")
        if path.is_file()
    )
    return tuple(
        (str(path.relative_to(root)), info.st_mtime_ns, info.st_size)
        for path in files
        for info in (path.stat(),)
    )


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
    root = data_dir()
    key = (str(root), store, window, limit, _fingerprint(root))
    if key in _cache:
        return _cache[key]
    try:
        result: dict[str, Any] = _run_json(args, data_dir=root, timeout_seconds=_TIMEOUT_SECONDS)
        if len(_cache) >= _CACHE_SIZE:
            _cache.pop(next(iter(_cache)))
        _cache[key] = result
        return result
    except RuntimeError as exc:  # unknown store or unreadable data: the CLI's own text
        raise HTTPException(status_code=409, detail=str(exc)) from exc
