"""The Machine learning window: stored ML runs (`alpha ml run`), read from their run folders."""

from __future__ import annotations

from ._base import StrictModel


class MlStoredFold(StrictModel):
    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str


class MlStoredMetrics(StrictModel):
    """Stored numbers after costs; a number that could not be worked out is null with a reason."""

    total_return: float | None
    benchmark_total_return: float | None
    max_drawdown: float | None
    sharpe: float | None
    cagr: float | None
    mean_turnover: float | None
    total_fees: float | None
    total_slippage_cost: float | None
    sharpe_reason: str | None


class MlStoredRun(StrictModel):
    run_id: str
    mtime: float
    assets: list[str]
    model: str
    costs: str
    split_sentence: str | None
    n_oos_periods: int | None
    label: str | None
    metrics: MlStoredMetrics
    folds: list[MlStoredFold]


class MlStoredRunList(StrictModel):
    total: int
    items: list[MlStoredRun]
