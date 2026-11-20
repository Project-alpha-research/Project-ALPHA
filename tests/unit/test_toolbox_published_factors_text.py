"""Published-factor reading: the words of each branch, the search's exclusions and edge cases."""

from dataclasses import replace
from datetime import date
from pathlib import Path

from alpha_cli.toolbox.reference import read_reference_for_period
from alpha_cli.toolbox.runner import run
from tests.unit.published_factors_support import (
    US_STOCK,
    factor_returns,
    planted_home,
    write_factor_file,
)
from tests.unit.test_spine_tools import RUN

TOOL = "context.published_factors"
COSTS = "paper portfolios before trading costs"
NOT_STOCKS = "for a bond or commodity fund these stock factors mean little"


def test_the_read_never_returns_a_month_ending_after_the_last_day(tmp_path: Path) -> None:
    write_factor_file(tmp_path, factor_returns())
    got = read_reference_for_period(
        tmp_path, first_day=date(2012, 1, 2), last_day=date(2022, 6, 15)
    )
    assert max(got.rows["month"].to_list()) == date(2022, 5, 31)
    whole = read_reference_for_period(
        tmp_path, first_day=date(2012, 1, 2), last_day=date(2022, 6, 30)
    )
    assert max(whole.rows["month"].to_list()) == date(2022, 6, 30)


def test_the_read_states_the_costs_and_no_etf_caution_for_a_stock(tmp_path: Path) -> None:
    planted_home(tmp_path, weights={"Mom12m": 0.5})
    doc = run(tmp_path, TOOL, RUN)
    assert doc["result"]["branch"] == "read"
    assert COSTS in doc["reading"]
    assert NOT_STOCKS not in doc["reading"]
    assert "a month" in doc["reading"] and "a year" in doc["reading"]


def test_an_etf_carries_the_not_stocks_caution(tmp_path: Path) -> None:
    planted_home(tmp_path, weights={"Mom12m": 0.5}, identity=replace(US_STOCK, asset_class="etf"))
    doc = run(tmp_path, TOOL, RUN)
    assert doc["result"]["branch"] == "read"
    assert NOT_STOCKS in doc["reading"]


def test_collinear_branch_says_one_at_a_time_and_no_joint_share(tmp_path: Path) -> None:
    series = factor_returns()
    series["BM"] = dict(series["Size"])
    planted_home(tmp_path, weights={"Mom12m": 0.5}, series=series)
    doc = run(tmp_path, TOOL, RUN)
    assert doc["result"]["branch"] == "collinear-singles"
    text = doc["reading"]
    assert "one factor at a time; these exposures overlap and must not be added up" in text
    assert "month-to-month variation" not in text
    assert doc["values"]["explained_share"] is None
    assert COSTS in text


def test_signals_lacking_months_are_excluded_and_counted(tmp_path: Path) -> None:
    series = factor_returns()
    short = {"Other00", "Other01"}
    file_series = {
        name: (dict(list(rows.items())[24:]) if name in short else rows)
        for name, rows in series.items()
    }
    planted_home(tmp_path, weights={"Mom12m": 0.5}, series=series, file_series=file_series)
    search = run(tmp_path, TOOL, RUN)["result"]["search"]
    assert search["compared"] == len(series) - len(short)
    assert search["excluded"] == len(short)
    assert f"search across all {len(series) - len(short)}" in search["label"]
    assert f"{len(short)} left out" in search["sentence"]


def test_a_perfect_correlation_is_labelled_not_a_crash(tmp_path: Path) -> None:
    series = factor_returns()
    planted_home(tmp_path, weights={"Other03": 1.0}, noise=0.0, series=series)
    search = run(tmp_path, TOOL, RUN)["result"]["search"]
    assert search["top"][0]["signal"] == "Other03"
    assert search["top"][0]["edge"] == "perfect_correlation"
    assert "perfect correlation" in search["sentence"]
