"""Unit-level future poison: rows known after a decision instant never change that bar."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from alpha_data.context import derived
from alpha_data.context.attach import AttachResult, Binding, attach_context
from alpha_data.sessions import bar_known_at
from alpha_data.timeframe import DAILY
from tests.unit._context_attach_support import (
    CODE,
    CUTOFF,
    bars,
    cot_rows,
    daily,
    finra_rows,
    store_cot,
    store_finra,
)

POISON_COUNT = 9_000_000_000_000_000_000  # an Int64 count that dwarfs any real position
POISON_FLOAT = 1e100
BINDINGS = {
    "pos": Binding("cot_nc_net_oi", CODE),
    "sv": Binding("sv_ratio_5d", "SPY"),
}
PERIODS = [date(2023, 5, 2) + timedelta(weeks=n) for n in range(10)]
DAYS = daily(date(2023, 5, 1), 70)


def _cot(poison_after: datetime | None) -> pl.DataFrame:
    frame = cot_rows([dict(report_date=p, nl=100 + 10 * n) for n, p in enumerate(PERIODS)])
    if poison_after is None:
        return frame
    return frame.with_columns(
        pl.when(pl.col("known_from") > poison_after)
        .then(pl.lit(POISON_COUNT))
        .otherwise(pl.col("noncomm_long"))
        .alias("noncomm_long")
    )


def _finra(poison_after: datetime | None) -> pl.DataFrame:
    frame = finra_rows("SPY", [(d, 0.2 + 0.01 * n) for n, d in enumerate(DAYS)])
    if poison_after is None:
        return frame
    return frame.with_columns(
        pl.when(pl.col("known_from") > poison_after)
        .then(pl.lit(POISON_FLOAT))
        .otherwise(pl.col("short_volume"))
        .alias("short_volume")
    )


def _run(data_dir: Path) -> AttachResult:
    return attach_context(
        bars(DAYS),
        timeframe=DAILY,
        calendar=None,
        bindings=BINDINGS,
        data_dir=data_dir,
        cutoff=CUTOFF,
    )


def _store(data_dir: Path, poison_after: datetime | None) -> None:
    store_cot(data_dir, _cot(poison_after))
    store_finra(data_dir, _finra(poison_after), "SPY")


@pytest.mark.parametrize("k", [12, 25, 40, 55])
def test_poisoning_rows_known_after_bar_k_leaves_bars_up_to_k_unchanged(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory, k: int
) -> None:
    clean_dir, poisoned_dir = tmp_path, tmp_path_factory.mktemp("poisoned")
    _store(clean_dir, None)
    d_k = bar_known_at(bars(DAYS)["ts"][k], timeframe=DAILY, calendar=None)
    _store(poisoned_dir, d_k)
    clean, poisoned = _run(clean_dir).frame, _run(poisoned_dir).frame
    assert clean.head(k + 1).equals(poisoned.head(k + 1))
    assert not clean.equals(poisoned)  # the poison is visible later, so the test can fail


def _leaky(rows: pl.DataFrame, frame: pl.DataFrame) -> pl.DataFrame:
    """A deliberately leaky join: by report period, ignoring when the row became known."""
    series = derived.derive_cot(rows, "cot_nc_net_oi").sort("period")
    left = frame.with_columns(pl.col("ts").dt.date().alias("bar_day")).sort("bar_day")
    return left.join_asof(series, left_on="bar_day", right_on="period", strategy="backward")


def test_a_deliberately_leaky_join_does_change_so_the_poison_test_can_fail() -> None:
    k = 22  # Tuesday 2023-05-23: that report is released on Friday, three days later
    d_k = bar_known_at(bars(DAYS)["ts"][k], timeframe=DAILY, calendar=None)
    clean = _leaky(_cot(None), bars(DAYS)).head(k + 1)
    poisoned = _leaky(_cot(d_k), bars(DAYS)).head(k + 1)
    assert not clean.equals(poisoned)


def test_poisoned_known_late_row_is_invisible_before_its_release(tmp_path: Path) -> None:
    store_cot(tmp_path, _cot(datetime(2023, 5, 1, tzinfo=UTC)))  # every row poisoned
    early = attach_context(
        bars(DAYS[:4]),
        timeframe=DAILY,
        calendar=None,
        bindings={"pos": Binding("cot_nc_net_oi", CODE)},
        data_dir=tmp_path,
        cutoff=CUTOFF,
    )
    assert early.frame["ctx_pos"].to_list() == [None] * 4  # first release: Friday 2023-05-05
