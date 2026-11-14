"""Macro reference data, separate from bars and backtest inputs."""

from alpha_data.context.fred import (
    DEFAULT_SERIES,
    FredAdapter,
    as_known,
    first_release,
    latest,
    load_series,
    pull_series,
    store_series,
)

__all__ = [
    "DEFAULT_SERIES",
    "FredAdapter",
    "as_known",
    "first_release",
    "latest",
    "load_series",
    "pull_series",
    "store_series",
]
