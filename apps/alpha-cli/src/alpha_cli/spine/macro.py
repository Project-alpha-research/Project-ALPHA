"""Macro picture for one date window, read from stored context series as known at its end."""

from __future__ import annotations

import importlib
from datetime import date, datetime
from pathlib import Path
from typing import Any

SERIES = ("DGS10", "T10Y2Y", "VIXCLS", "DFF", "UNRATE", "ICSA", "BAMLH0A0HYM2")


def _day(value: object) -> date:
    return datetime.fromisoformat(str(value)).date()


def macro_window(home: Path, episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Each stored series at the start and trough of the worst drawdown, as known at the trough."""
    try:
        views = importlib.import_module("alpha_data.context.views")
    except ImportError as exc:
        return {
            "available": False,
            "reason": "macro data was not installed when this run was made",
            "detail": str(exc),
        }
    if not (home / "context" / "fred").exists():
        return {
            "available": False,
            "reason": "macro data was not installed when this run was made",
            "detail": f"no stored FRED context series at {home / 'context' / 'fred'}",
        }
    if not episodes:
        return {"available": False, "reason": "no drawdown episode to describe"}
    start, trough = _day(episodes[0]["start"]), _day(episodes[0]["trough"])
    rows: list[dict[str, Any]] = []
    for series_id in SERIES:
        try:
            known = views.as_known(views.load_series(series_id, data_dir=home), as_of=trough)
        except Exception as exc:  # one unreadable series must not stop the diagnostic pass
            rows.append(
                {
                    "series_id": series_id,
                    "reason": "macro data could not be read",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        known = known.filter(known["value"].is_not_null()).sort("obs_date")
        at_start = known.filter(known["obs_date"] <= start)["value"]
        at_trough = known.filter(known["obs_date"] <= trough)["value"]
        if at_start.is_empty() or at_trough.is_empty():
            rows.append({"series_id": series_id, "reason": "no observation known by then"})
            continue
        first, last = float(at_start[-1]), float(at_trough[-1])
        rows.append(
            {
                "series_id": series_id,
                "start_value": first,
                "trough_value": last,
                "change": last - first,
            }
        )
    return {
        "available": True,
        "basis": "stored FRED series as known on the trough date; worst full-sample drawdown",
        "start": str(start),
        "trough": str(trough),
        "as_of": str(trough),
        "series": rows,
    }
