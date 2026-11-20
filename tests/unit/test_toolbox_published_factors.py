"""Published-factor reading: month alignment, the descriptive reference read, known answers."""

import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.ledger import read_trials
from alpha_cli.toolbox.reference import LABEL, SENTENCE, read_reference_for_period
from alpha_cli.toolbox.run_months import compound_complete_months
from alpha_cli.toolbox.runner import run
from alpha_data.adapters.base import DatasetIdentity
from alpha_validation.correlation_interval import correlation_interval
from alpha_validation.proportion import benjamini_hochberg
from tests.unit.published_factors_support import (
    CRYPTO,
    FIXED,
    LAST,
    factor_returns,
    month_end,
    month_ends,
    planted_home,
    trading_days,
    write_factor_file,
)
from tests.unit.test_spine_tools import RUN

TOOL = "context.published_factors"
REFERENCE_TEST = "tests/unit/test_toolbox_published_factors.py::test_known_answer_planted_factor"
FORBIDDEN = re.compile(
    r"\b(pass|fail|passed|failed|supported|rejected|profit|should|buy|sell)\b", re.I
)


def _stamp(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _factor(doc: dict[str, Any], name: str) -> dict[str, Any]:
    return next(row for row in doc["result"]["factors"] if row["signal"] == name)


# ---------------------------------------------------------------- month alignment


def test_complete_months_only_and_exact_compounding() -> None:
    days = trading_days(date(2020, 1, 15), date(2020, 4, 20))  # starts mid January
    every = trading_days(date(2019, 12, 1), date(2020, 5, 29))
    returns = [0.01 if d.month == 2 else 0.001 for d in days[:-1]]
    got = compound_complete_months([_stamp(d) for d in days], returns, every)
    # January starts mid-month and April stops mid-month: only February and March are complete.
    assert got.months == (date(2020, 2, 29), date(2020, 3, 31))
    assert got.incomplete == (date(2020, 1, 31), date(2020, 4, 30))
    feb = sum(d.month == 2 for d in days[:-1])
    mar = sum(d.month == 3 for d in days[:-1])
    assert got.returns == pytest.approx((1.01**feb - 1, 1.001**mar - 1), rel=1e-12)


def test_last_trading_day_return_needs_a_following_bar() -> None:
    every = trading_days(date(2020, 1, 1), date(2020, 3, 31))
    days = [d for d in every if d <= date(2020, 2, 28)]  # ends on February's last trading day
    got = compound_complete_months([_stamp(d) for d in days], [0.001] * (len(days) - 1), every)
    assert got.months == (date(2020, 1, 31),)
    assert date(2020, 2, 29) in got.incomplete


def test_a_gap_inside_a_month_makes_it_incomplete() -> None:
    every = trading_days(date(2020, 1, 1), date(2020, 4, 30))
    days = [d for d in every if not date(2020, 2, 10) <= d <= date(2020, 2, 14)]
    got = compound_complete_months([_stamp(d) for d in days], [0.001] * (len(days) - 1), every)
    assert got.months == (date(2020, 1, 31), date(2020, 3, 31))
    assert got.incomplete == (date(2020, 2, 29), date(2020, 4, 30))


# ---------------------------------------------------------------- the descriptive reference read


def test_reference_read_limits(tmp_path: Path) -> None:
    series = factor_returns()
    poisoned = {
        name: {m: v * 1000.0 if m >= date(2023, 12, 31) else v for m, v in rows.items()}
        for name, rows in series.items()
    }
    write_factor_file(tmp_path, poisoned)
    got = read_reference_for_period(tmp_path, first_day=date(2012, 1, 2), last_day=LAST)
    months = set(got.rows["month"].to_list())
    assert got.vintage == "2026.10"
    # (b) nothing at or after the held-back boundary, December 2023 is still before it.
    assert max(months) == date(2023, 12, 31)
    # (c) nothing after the run's own data end: June 2022 is the last month of this run.
    early = read_reference_for_period(
        tmp_path, first_day=date(2012, 1, 2), last_day=date(2022, 6, 15)
    )
    assert max(early.rows["month"].to_list()) == date(2022, 6, 30)
    assert min(early.rows["month"].to_list()) == date(2012, 1, 31)


def test_newest_vintage_is_taken_and_named(tmp_path: Path) -> None:
    series = factor_returns()
    write_factor_file(tmp_path, series, release="2025.10", released=date(2025, 10, 20))
    write_factor_file(tmp_path, series, release="2026.10")
    got = read_reference_for_period(tmp_path, first_day=date(2012, 1, 2), last_day=LAST)
    assert got.vintage == "2026.10"


def test_missing_factor_file_names_the_pull_command(tmp_path: Path) -> None:
    with pytest.raises(SpineError, match="pull-osap-portfolios --release"):
        read_reference_for_period(tmp_path, first_day=date(2012, 1, 2), last_day=LAST)


# ---------------------------------------------------------------- known answers


def test_known_answer_planted_factor(tmp_path: Path) -> None:
    planted_home(tmp_path, weights={"Mom12m": 0.5})
    doc = run(tmp_path, TOOL, RUN)
    assert doc["result"]["branch"] == "read"
    mom = _factor(doc, "Mom12m")
    assert mom["beta"] == pytest.approx(0.5, abs=0.02)
    assert mom["ci95"][0] < 0.5 < mom["ci95"][1]
    assert mom["published_year"] == FIXED["Mom12m"]
    for name in FIXED:
        if name != "Mom12m":
            low, high = _factor(doc, name)["ci95"]
            assert low < 0.0 < high, name
    assert doc["values"]["explained_share"] > 0.9
    assert doc["result"]["months_used_count"] > 80
    assert doc["result"]["vintage"] == "2026.10"
    assert doc["result"]["periods_per_year"] == 12


def test_known_answer_pure_noise(tmp_path: Path) -> None:
    planted_home(tmp_path, weights={}, noise=0.02, seed=1)
    doc = run(tmp_path, TOOL, RUN)
    assert doc["values"]["explained_share"] < 0.2
    for name in FIXED:
        low, high = _factor(doc, name)["ci95"]
        assert low < 0.0 < high, name


def test_labels_sentence_and_plain_words(tmp_path: Path) -> None:
    planted_home(tmp_path, weights={"Mom12m": 0.5})
    doc = run(tmp_path, TOOL, RUN)
    assert LABEL == "reference-series-known-later"
    assert LABEL in doc["labels"]
    assert "exploratory" in doc["labels"] or "declared" in doc["labels"]
    assert SENTENCE in doc["reading"]
    assert "month-to-month variation" in doc["reading"]
    assert "search across all" in doc["reading"].lower() and "exploratory" in doc["reading"]
    assert not FORBIDDEN.search(doc["reading"])
    rows = read_trials(tmp_path)
    assert all(r["verdict"] is None for r in rows)
    assert run(tmp_path, TOOL, RUN)["file"] == doc["file"]


def test_search_top_three_with_benjamini_hochberg(tmp_path: Path) -> None:
    series = planted_home(tmp_path, weights={"Mom12m": 0.5})
    doc = run(tmp_path, TOOL, RUN)
    search = doc["result"]["search"]
    assert search["label"] == f"search across all {len(series)} \u2014 exploratory"
    top = search["top"]
    assert len(top) == 3 and top[0]["signal"] == "Mom12m"
    assert abs(top[0]["r"]) >= abs(top[1]["r"]) >= abs(top[2]["r"])
    assert top[0]["published_year"] == FIXED["Mom12m"]
    # Recompute every correlation from the stored months with the validated functions.
    used = [date.fromisoformat(m) for m in doc["result"]["months_used"]]
    strategy = _strategy_months(tmp_path, used)
    cis = {
        name: correlation_interval(strategy, [rows[m] for m in used])
        for name, rows in series.items()
    }
    names = sorted(cis)
    q = dict(zip(names, benjamini_hochberg([cis[n]["p"] for n in names]).qvalues, strict=True))
    assert search["compared"] == len(series)
    for row in top:
        assert row["r"] == pytest.approx(cis[row["signal"]]["r"], rel=1e-9, abs=1e-12)
        assert row["ci95"] == pytest.approx(cis[row["signal"]]["ci95"], rel=1e-9, abs=1e-12)
        assert row["q"] == pytest.approx(q[row["signal"]], rel=1e-9, abs=1e-12)
    assert "independent months" in search["statement"] and "search" in search["statement"]


def _strategy_months(home: Path, months: list[date]) -> list[float]:
    """The run's compounded month returns, read back from its stored equity."""
    import polars as pl

    frame = pl.read_parquet(home / "runs" / RUN / "equity_curve.parquet")
    days = [t.date() for t in frame["ts"]]
    level = dict(zip(days, frame["equity"], strict=True))
    first: dict[date, date] = {}
    for day in days:
        first.setdefault(month_end(day), day)
    order = sorted(first)
    return [level[first[order[order.index(m) + 1]]] / level[first[m]] - 1.0 for m in months]


def test_too_few_months_is_a_typed_reading(tmp_path: Path) -> None:
    planted_home(tmp_path, first=date(2020, 1, 2), last=date(2022, 12, 30), weights={})
    doc = run(tmp_path, TOOL, RUN)
    assert doc["result"]["branch"] == "too-few-months"
    assert doc["values"]["explained_share"] is None
    assert re.search(r"too few months to read \(\d+ of 80 needed\)", doc["reading"])
    assert LABEL in doc["labels"]


@pytest.mark.parametrize("identity", [CRYPTO, None])
def test_not_us_stock_has_no_numbers(tmp_path: Path, identity: DatasetIdentity | None) -> None:
    planted_home(tmp_path, weights={"Mom12m": 0.5}, identity=identity)
    doc = run(tmp_path, TOOL, RUN)
    assert doc["values"]["explained_share"] is None
    assert doc["result"]["branch"] == ("not-applicable" if identity else "unknown-asset")
    if identity:
        assert (
            "not applicable: these reference factors are us stock factors" in doc["reading"].lower()
        )


def test_collinear_factors_fall_back_to_one_at_a_time(tmp_path: Path) -> None:
    series = factor_returns()
    series["BM"] = dict(series["Size"])
    planted_home(tmp_path, weights={"Mom12m": 0.5}, series=series)
    doc = run(tmp_path, TOOL, RUN)
    assert doc["result"]["branch"] == "collinear-singles"
    assert "collinear" in doc["result"]["refusal"]
    assert doc["values"]["explained_share"] is None
    assert len(doc["result"]["singles"]) == len(FIXED)


def test_held_back_months_are_never_read(tmp_path: Path) -> None:
    base = tmp_path / "base"
    poison = tmp_path / "poison"
    base.mkdir()
    poison.mkdir()
    series = factor_returns()
    planted_home(base, weights={"Mom12m": 0.5}, series=series)
    loud = {
        name: {m: v * 1000.0 if m >= date(2024, 1, 1) else v for m, v in rows.items()}
        for name, rows in series.items()
    }
    # the strategy itself is the same; only the factor file differs after the boundary.
    planted_home(poison, weights={"Mom12m": 0.5}, series=series, file_series=loud)
    # ... and after the run's own data end.
    first, second = run(base, TOOL, RUN), run(poison, TOOL, RUN)
    for key in ("values", "result"):
        assert first[key] == second[key]
    assert "reserved-period-seen" in first["labels"]
    assert max(first["result"]["months_used"]) < "2024-01"
    assert max(month_ends()) > date(2024, 1, 1)


def test_months_after_the_runs_own_end_are_never_read(tmp_path: Path) -> None:
    base, poison = tmp_path / "base", tmp_path / "poison"
    base.mkdir()
    poison.mkdir()
    series = factor_returns()
    end = date(2022, 6, 30)
    loud = {
        n: {m: v * 1000.0 if m > date(2022, 6, 30) else v for m, v in rows.items()}
        for n, rows in series.items()
    }
    planted_home(base, weights={"Mom12m": 0.5}, series=series, last=end)
    planted_home(poison, weights={"Mom12m": 0.5}, series=series, file_series=loud, last=end)
    assert run(base, TOOL, RUN)["result"] == run(poison, TOOL, RUN)["result"]


@pytest.mark.parametrize(
    ("case", "weights", "noise"), [("planted", {"Mom12m": 0.5}, 0.002), ("noise", {}, 0.02)]
)
def test_results_match_the_pinned_fixture(
    tmp_path: Path, case: str, weights: dict[str, float], noise: float
) -> None:
    from tests.unit.test_toolbox_contract import REFERENCE, _assert_close

    planted_home(tmp_path, weights=weights, noise=noise)
    doc = run(tmp_path, TOOL, RUN)
    _assert_close(doc["result"], REFERENCE[f"{TOOL}|{case}|"], case)
