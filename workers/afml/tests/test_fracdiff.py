"""Parity and look-ahead checks for wave 1 item 4: fractional differencing and minimum d."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import pytest
from shared_fixtures import synthetic_daily_bars

from alpha_afml_worker.contract import ContractError
from alpha_afml_worker.fracdiff import ffd, ffd_weights, fit_min_d


def closes(bars: pl.DataFrame) -> pd.Series:
    index = pd.DatetimeIndex(bars["ts"].to_numpy()).tz_localize("UTC")
    return pd.Series(bars["close"].to_numpy(), index=index)


def test_hand_weights_for_half_and_one() -> None:
    # w_k = -w_{k-1} (d - k + 1) / k: for d = 0.5, 1, -1/2, -1/8, -1/16, -5/128.
    assert ffd_weights(0.5, 0.039).tolist() == [1.0, -0.5, -0.125, -0.0625, -0.0390625]
    assert ffd_weights(1.0, 1e-5).tolist() == [1.0, -1.0]


def test_d_one_is_the_plain_difference_and_zero_the_series() -> None:
    x = np.log(closes(synthetic_daily_bars()).to_numpy())
    assert np.allclose(ffd(x, 1.0, 1e-5)[1:], np.diff(x), atol=1e-14)
    assert np.allclose(ffd(x, 0.0, 1e-5), x)


@pytest.mark.parametrize("d", [0.2, 0.4, 0.55, 0.8])
def test_libraries_agree_on_ffd_values(d: float) -> None:
    x = np.log(closes(synthetic_daily_bars()).to_numpy())
    values = ffd(x, d, 1e-4)  # raises on any gap above 1e-10
    width = ffd_weights(d, 1e-4).size - 1
    assert np.isnan(values[:width]).all() and np.isfinite(values[width:]).all()


def test_ffd_value_at_t_ignores_every_later_bar() -> None:
    x = np.log(closes(synthetic_daily_bars()).to_numpy())
    base = ffd(x, 0.45, 1e-3)
    for t in (100, 300, 598):
        moved = x.copy()
        moved[t + 1 :] += 0.7
        np.testing.assert_array_equal(ffd(moved, 0.45, 1e-3)[: t + 1], base[: t + 1])


def test_min_d_uses_only_the_training_span() -> None:
    bars = synthetic_daily_bars(n=600)
    close = closes(bars)
    fit_end = close.index[399]
    fitted = fit_min_d(close[close.index <= fit_end])
    poisoned = close.copy()
    poisoned.iloc[400:] = poisoned.iloc[400:] * np.exp(np.linspace(0, 3, 200))  # a later trend
    again = fit_min_d(poisoned[poisoned.index <= fit_end])
    assert (fitted.d, fitted.pvalue, fitted.table) == (again.d, again.pvalue, again.table)
    assert fitted.train_bars == 400
    whole = fit_min_d(poisoned)
    assert whole.table != fitted.table  # the full-sample search would see the later bars


def test_random_walk_needs_a_positive_d() -> None:
    fitted = fit_min_d(closes(synthetic_daily_bars(n=600)))
    assert fitted.d is not None and 0.0 < fitted.d <= 1.0
    assert fitted.corr is not None and fitted.pvalue is not None and fitted.pvalue <= 0.05


def test_bad_input_fails_loud() -> None:
    with pytest.raises(ContractError):
        ffd(np.array([1.0, np.nan, 2.0]), 0.5, 1e-3)
    short = closes(synthetic_daily_bars(n=60)).iloc[:30]
    with pytest.raises(ContractError):
        fit_min_d(short)


def test_command_fits_d_before_fit_end_and_ignores_later_bars(tmp_path: Path) -> None:
    """Review finding: exercise the real fit_end filter, not a slice made by the test."""
    from datetime import datetime

    from alpha_afml_worker.__main__ import run_fracdiff

    bars = synthetic_daily_bars(n=600)
    fit_end = datetime.fromisoformat(str(bars["ts"][399]))
    trend = np.r_[np.ones(400), np.exp(np.linspace(0.0, 3.0, 200))]
    poisoned = bars.with_columns(
        pl.col(c) * pl.Series(trend) for c in ("open", "high", "low", "close")
    )
    outputs = []
    for name, frame in (("clean", bars), ("poisoned", poisoned)):
        frame.write_parquet(tmp_path / f"{name}.parquet")
        summary = run_fracdiff(
            tmp_path / f"{name}.parquet", tmp_path / f"{name}-ffd.parquet", fit_end
        )
        assert summary["train_bars"] == 400 and summary["thres"] == 0.01
        outputs.append((summary, pl.read_parquet(tmp_path / f"{name}-ffd.parquet")))
    assert outputs[0][0]["table"] == outputs[1][0]["table"]
    assert outputs[0][1].head(400).equals(outputs[1][1].head(400))
    assert all(row["d"] == round(row["d"], 10) for row in outputs[0][0]["table"])


def test_a_series_shorter_than_the_window_fails_loud() -> None:
    x = np.log(closes(synthetic_daily_bars(n=60)).to_numpy())[:50]
    with pytest.raises(ContractError, match="window"):
        ffd(x, 0.1, 1e-4)
