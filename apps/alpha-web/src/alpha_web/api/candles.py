"""``/api/candles/{symbol}`` — PIT-adjusted OHLCV for the price chart."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from alpha_web import _candles
from alpha_web._catalog import _run_json
from alpha_web.api._common import data_dir
from alpha_web.api.models import ArchiveChartDatasets, Candles, ChartOverlays

router = APIRouter(prefix="/api", tags=["candles"])


@router.get("/candles/{symbol:path}", response_model=Candles)
def candles(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    snapshot: str | None = None,
    manifest_id: str | None = None,
    tail: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    """Point-in-time candles for ``symbol`` (``{symbol:path}`` so ``BTC/USD`` works).

    ``tail`` trims the response to the last N bars of the window. It is a payload trim only:
    the reader still loads the whole window once and caches it on the parquet mtime, so Market
    Watch's ``tail=2`` reads are cheap after the first.
    """
    directory = data_dir()
    try:
        result = _candles.candles(
            symbol,
            data_dir=directory,
            start=start,
            end=end,
            snapshot=snapshot,
            **({"manifest_id": manifest_id} if manifest_id else {}),
        )
        bars = result.get("bars")
        rows = bars if isinstance(bars, list) else []
        if tail is not None:  # copy: the reader's cached dict must keep the full window
            rows = rows[-tail:]
            result = {**result, "bars": rows}
        return result
    except RuntimeError as exc:  # CLI failed (unknown symbol / empty window) — surface as 404
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/overlays/{symbol:path}", response_model=ChartOverlays)
def overlays(
    symbol: str,
    indicator: Annotated[list[str] | None, Query()] = None,
    pattern: Annotated[list[str] | None, Query()] = None,
    end: str | None = None,
    snapshot: str | None = None,
    manifest_id: str | None = None,
) -> dict[str, Any]:
    """Indicator series and pattern annotations computed by ``alpha chart overlays`` over the
    same point-in-time window as ``/api/candles``; the browser draws, it never computes.

    Lives under ``/api/overlays`` because ``/candles/{symbol:path}`` swallows any suffix.
    """
    try:
        return _candles.overlays(
            symbol,
            data_dir=data_dir(),
            indicators=tuple(indicator or ()),
            patterns=tuple(pattern or ()),
            end=end,
            snapshot=snapshot,
            **({"manifest_id": manifest_id} if manifest_id else {}),
        )
    except RuntimeError as exc:  # bad spec / unknown symbol / short window — the CLI's own text
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/chart-datasets", response_model=ArchiveChartDatasets)
def chart_datasets() -> dict[str, Any]:
    try:
        result: dict[str, Any] = _run_json(
            ["data", "chart-datasets", "--json"], data_dir=data_dir(), timeout_seconds=30
        )
        return result
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
