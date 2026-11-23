"""Per-fold out-of-sample results of a model run, read from its stored periods."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from alpha_cli.figures import _sources as src
from alpha_core import DataError
from alpha_validation import sharpe_ratio

PERIODS = "ml_periods.parquet"


def ml_folds(rdir: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per fold: its Sharpe (None when flat) and compounded return."""
    frame = src.frame(rdir, PERIODS, "target_ts")
    if frame is None or frame.is_empty():
        raise DataError(f"this run did not store {PERIODS}; run `alpha ml run` again")
    per_year = manifest.get("periods_per_year")
    if type(per_year) is not int or per_year < 1:
        raise DataError("the run records no periods per year")
    rows: list[dict[str, Any]] = []
    for fold in sorted(set(frame["fold"].to_list())):
        returns = np.array(
            src.floats(frame.filter(frame["fold"] == fold)["net_return"], name="net_return")
        )
        flat = returns.size < 2 or float(np.std(returns, ddof=1)) == 0.0
        rows.append(
            {
                "fold": fold,
                "oos_sharpe": None if flat else sharpe_ratio(returns, periods_per_year=per_year),
                "oos_return": float(np.prod(1.0 + returns) - 1.0),
            }
        )
    return rows
