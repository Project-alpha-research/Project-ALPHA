"""Mirror identity on a frozen panel; missing historical values are disclosed."""

from __future__ import annotations

import hashlib
import io
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from alpha_core import DataError
from alpha_research.panel import cross_sectional_ic

TWIN_RANK_CORRELATION = 0.98
TWIN_RULE = "same-panel-rank-twin-098-1"


def rank_twin(signal: np.ndarray, earlier: np.ndarray) -> dict[str, Any]:
    """Spearman daily ranks; the mean absolute correlation identifies sign mirrors too."""
    ic = cross_sectional_ic(signal, earlier)
    observed = np.array([v for v in ic.values if v is not None])
    if not observed.size:
        return {
            "is_twin": False,
            "mean_correlation": None,
            "mean_absolute_correlation": None,
            "days": 0,
        }
    absolute = float(np.abs(observed).mean())
    return {
        "is_twin": absolute >= TWIN_RANK_CORRELATION,
        "mean_correlation": float(observed.mean()),
        "mean_absolute_correlation": absolute,
        "days": len(observed),
        "rule": TWIN_RULE,
    }


def find_twin(
    signal: np.ndarray,
    history: list[dict[str, Any]],
    panel_hash: str,
    days: list[date],
    symbols: list[str],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    from alpha_cli._rdagent_judge import matrix

    unavailable = 0
    for row in history:
        if row["status"] == "REPEAT" or row["panel_sha256"] != panel_hash:
            continue
        stored = row.get("factor_values", {})
        path = Path(stored["path"]) if stored else None
        # Code that failed or gave unstable answers stored no comparable values.
        if row["status"] in {"FAILED", "UNSTABLE"} or path is None or not path.exists():
            unavailable += 1
            continue
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != stored["sha256"]:
            raise DataError("earlier factor values differ from their recorded hash")
        values = pl.read_parquet(io.BytesIO(raw))
        if row["name"] not in values.columns:
            unavailable += 1
            continue
        result = rank_twin(signal, matrix(values, row["name"], days, symbols))
        if result["is_twin"]:
            return row, {
                "twin": result,
                "twin_check": f"not available for {unavailable} earlier trials",
            }
    return None, {"twin_check": f"not available for {unavailable} earlier trials"}
