"""Boundary and point-in-time examples for the four daily data health groups."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from alpha_core import ActionType, CorporateAction, DataError, UniverseMembership
from alpha_data.health import HealthCheck, HealthReport, health_report
from alpha_data.sessions import sessions_between

DAY = timedelta(days=1)
START = datetime(2024, 1, 2, tzinfo=UTC)


def frame(prices: list[float], *, start: datetime = START) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": [start + DAY * i for i in range(len(prices))],
            **{key: prices for key in ("open", "high", "low", "close")},
            "volume": [10.0] * len(prices),
        }
    )


def check(report: HealthReport, name: str) -> HealthCheck:
    return next(item for item in report.checks if item.id == name)


def crypto(bars: pl.DataFrame, when: datetime | None = None) -> HealthReport:
    if when is None:
        last = bars["ts"].max()
        assert isinstance(last, datetime)
        when = last + DAY
    return health_report(bars, symbol="X", calendar=None, report_time=when)


def test_clean_and_inapplicable_checks() -> None:
    result = crypto(frame([100.0, 101.0, 102.0]))
    assert result.verdict == "pass"
    assert {item.status for item in result.checks} == {"pass", "not-applicable"}
    assert all(item.threshold and item.finding for item in result.checks)
    assert check(result, "survivorship").status == "not-applicable"


@pytest.mark.parametrize(
    ("ratio", "peer", "status", "words"),
    [
        (2.06, None, "warn", "no other series"),
        (2.061, None, "pass", ""),
        (2.0, 104.99, "fail", "other series were quiet"),
        (2.0, 105.0, "warn", "market also moved sharply"),
        (0.2, 90.0, "warn", "market also moved sharply"),
        (1.5, None, "warn", "no other series"),
    ],
)
def test_unflagged_split(ratio: float, peer: float | None, status: str, words: str) -> None:
    peers = [] if peer is None else [frame([100.0, peer])]
    result = health_report(
        frame([100.0, 100.0 / ratio]),
        symbol="X",
        calendar="XNYS",
        report_time=START + DAY * 2,
        peers=peers,
    )
    item = check(result, "unflagged_split")
    assert item.status == status and words in item.finding.lower()


@pytest.mark.parametrize(
    ("age", "announced", "status"),
    [(3, True, "pass"), (4, True, "warn"), (-1, False, "warn"), (-1, True, "pass")],
)
def test_split_window_uses_exchange_sessions_and_knowledge(
    age: int, announced: bool, status: str
) -> None:
    # Move on Jan 9; Jan 4 and Jan 3 are three and four exchange sessions earlier.
    ex = {3: date(2024, 1, 4), 4: date(2024, 1, 3), -1: date(2024, 1, 10)}[age]
    action = CorporateAction(
        symbol="X",
        action_type=ActionType.SPLIT,
        ratio=2,
        ex_date=ex,
        announce_date=date(2024, 1, 2) if announced else None,
    )
    bars = frame([100.0, 50.0], start=START + DAY * 6)
    result = health_report(
        bars, symbol="X", calendar="XNYS", report_time=START + DAY * 10, actions=[action]
    )
    assert check(result, "unflagged_split").status == status


@pytest.mark.parametrize(
    ("price", "ratio", "status"),
    [(50.0, 2.0, "pass"), (100.0, 2.0, "fail"), (100.0, 1.1, "not-applicable")],
)
def test_recorded_splits_use_adapter_rule(price: float, ratio: float, status: str) -> None:
    action = CorporateAction(
        symbol="X", action_type=ActionType.SPLIT, ratio=ratio, ex_date=date(2024, 1, 3)
    )
    report = health_report(
        frame([100.0, price]),
        symbol="X",
        calendar="XNYS",
        report_time=START + DAY * 2,
        actions=[action],
    )
    assert check(report, "recorded_splits_applied").status == status


@pytest.mark.parametrize(
    ("ratio", "status", "words"),
    [
        (49.99, "not-applicable", ""),
        (50.0, "warn", "extreme overnight jump"),
        (0.02, "warn", "extreme overnight jump"),
        (1001.0, "warn", "1000"),
        (0.0101, "warn", "100"),
        (2000.0, "warn", "2000"),
    ],
)
def test_redenomination(ratio: float, status: str, words: str) -> None:
    item = check(crypto(frame([100.0, 100.0 / ratio])), "unflagged_split")
    assert item.status == status and words in item.finding


def test_timestamps_duplicates_and_timezone() -> None:
    bars = frame([100.0, 101.0, 102.0])
    result = crypto(bars[[1, 0, 1]])
    assert check(result, "increasing").count == 1
    assert check(result, "duplicate_timestamps").count == 1
    assert check(crypto(bars[[0, 0, 1]]), "increasing").status == "fail"
    naive = bars.with_columns(pl.col("ts").dt.replace_time_zone(None))
    assert check(crypto(naive, START + DAY * 3), "timezone").count == 3
    with pytest.raises(DataError, match="UTC"):
        crypto(bars, START.replace(tzinfo=None))


def test_exchange_sessions_and_close() -> None:
    # The July 3 early close precedes a holiday and weekend.
    start = datetime(2024, 7, 3, tzinfo=UTC)
    bars = frame([10.0, 11.0, 12.0], start=start)

    def at(rows: pl.DataFrame, when: datetime) -> HealthReport:
        return health_report(rows, symbol="X", calendar="XNYS", report_time=when)

    assert check(at(bars, start + DAY * 3), "non_session").example_dates == (date(2024, 7, 4),)
    clean = at(bars[[0, 2]], start + DAY * 3)
    assert clean.verdict == "pass"
    assert (
        check(at(bars.head(1), start + timedelta(hours=16, minutes=59)), "partial_bar").status
        == "fail"
    )
    assert check(at(bars.head(1), start + timedelta(hours=17)), "partial_bar").status == "pass"
    assert (
        check(at(bars.head(1), start + DAY * 9 + timedelta(hours=21)), "stale_tail").status
        == "warn"
    )
    assert (
        check(at(bars.head(1), start + DAY * 8 + timedelta(hours=21)), "stale_tail").status
        == "pass"
    )


def test_historical_session_range() -> None:
    start = datetime(1993, 1, 4, tzinfo=UTC)
    report = health_report(
        frame([10.0, 11.0], start=start), symbol="X", calendar="XNYS", report_time=start + DAY * 2
    )
    assert report.verdict == "pass"


@pytest.mark.parametrize(
    ("bad", "value"),
    [
        ("low", 101.0),
        ("open", 0.0),
        ("high", float("nan")),
        ("volume", -1.0),
        ("volume", float("inf")),
    ],
)
def test_bar_invariants(bad: str, value: float) -> None:
    bars = frame([100.0] * 8).with_columns(pl.lit(value).alias(bad))
    item = check(crypto(bars), "ohlcv")
    assert item.count == 8 and len(item.example_dates) == 5 and item.status == "fail"


@pytest.mark.parametrize(
    ("size", "missing", "status"), [(50, 0, "pass"), (50, 1, "warn"), (49, 1, "fail")]
)
def test_missing_grid(size: int, missing: int, status: str) -> None:
    bars = frame([float(100 + i) for i in range(size)])
    if missing:
        bars = bars.filter(pl.col("ts") != START + DAY)
    item = check(crypto(bars), "missing_sessions")
    assert item.status == status and item.count == missing


@pytest.mark.parametrize(
    ("size", "zeros", "status"), [(20, 0, "pass"), (20, 1, "warn"), (19, 1, "fail")]
)
def test_zero_volume(size: int, zeros: int, status: str) -> None:
    bars = frame([100.0] * size).with_columns(
        pl.Series("volume", [0.0] * zeros + [1.0] * (size - zeros))
    )
    assert check(crypto(bars), "zero_volume").status == status


@pytest.mark.parametrize(
    ("prices", "status"),
    [
        ([100.0] * 9 + [120.0, 104.0], "fail"),
        ([100.0] * 9 + [120.0, 104.01], "pass"),
        ([100.0] * 10 + [80.0, 96.0], "fail"),
        ([100.0] * 10 + [115.0, 100.0], "pass"),
        ([100.0, 114.0] * 7 + [140.0, 114.0], "pass"),
        ([100.0] * 11 + [130.0], "pass"),
        ([100.0, 114.0] * 7 + [100.0] * 62 + [120.0, 100.0], "fail"),
    ],
)
def test_spike_threshold_and_snapback(prices: list[float], status: str) -> None:
    assert check(crypto(frame(prices)), "spike_snaps_back").status == status


@pytest.mark.parametrize(("n", "status"), [(4, "pass"), (5, "warn"), (9, "warn")])
def test_stale_run_counts_runs(n: int, status: str) -> None:
    item = check(crypto(frame([99.0] + [100.0] * n)), "stale_run")
    assert item.status == status and item.count == int(n >= 5)


def test_survivorship_requires_leaver_bars_in_membership() -> None:
    bars = frame([100.0, 101.0])
    leaver = UniverseMembership(
        symbol="Y", effective_from=START.date(), effective_to=(START + DAY).date()
    )

    def audit(history: list[UniverseMembership] | None, other: pl.DataFrame) -> HealthCheck:
        report = health_report(
            bars,
            symbol="X",
            calendar=None,
            report_time=START + DAY * 2,
            universe_bars={"Y": other},
            memberships=history,
        )
        return check(report, "survivorship")

    assert "survivors only" in audit(None, bars).finding.lower()
    assert audit([], bars).status == "fail"
    assert audit([leaver], bars.tail(1)).status == "fail"
    assert audit([leaver], bars).status == "pass"
    assert audit([leaver], bars).count == 1


def test_future_poison_does_not_confirm_a_spike_or_change_prior_findings() -> None:
    bars = frame([100.0] * 9 + [120.0, 100.0, 0.0])
    cutoff = START + DAY * 10
    prior = crypto(bars.head(10), cutoff)
    at_cutoff = crypto(bars.head(11), cutoff)
    assert check(at_cutoff, "partial_bar").example_dates == (cutoff.date(),)
    assert [c for c in prior.checks if c.id != "partial_bar"] == [
        c for c in at_cutoff.checks if c.id != "partial_bar"
    ]
    poisoned = crypto(bars, cutoff)
    assert check(poisoned, "future_bar").status == "fail"
    assert [c for c in at_cutoff.checks if c.id != "future_bar"] == [
        c for c in poisoned.checks if c.id != "future_bar"
    ]
    assert check(crypto(bars.head(11)), "spike_snaps_back").status == "fail"


def test_all_four_groups_pass_with_recorded_split_and_historical_leaver() -> None:
    bars = frame([100.0, 50.0, 51.0, 52.0])
    action = CorporateAction(
        symbol="X", action_type=ActionType.SPLIT, ex_date=date(2024, 1, 3), ratio=2
    )
    member = UniverseMembership(
        symbol="Y", effective_from=START.date(), effective_to=date(2024, 1, 5)
    )
    report = health_report(
        bars,
        symbol="X",
        calendar="XNYS",
        report_time=START + DAY * 4,
        actions=[action],
        memberships=[member],
        universe_bars={"Y": bars.head(2)},
    )
    assert all(item.status == "pass" for item in report.checks)
    assert report.verdict == "pass"


def test_daily_grid_distinguishes_misplaced_bar_and_missing_session() -> None:
    bars = frame([100.0, 101.0, 102.0])
    shifted = bars.with_columns(
        pl.Series("ts", [START, START + DAY + timedelta(hours=1), START + DAY * 2])
    )
    report = crypto(shifted)
    assert check(report, "daily_grid").example_dates == (date(2024, 1, 3),)
    assert check(report, "missing_sessions").count == 1
    stock = health_report(bars[[0, 2]], symbol="X", report_time=START + DAY * 3, calendar="XNYS")
    assert check(stock, "missing_sessions").example_dates == (date(2024, 1, 3),)


def test_inverse_redenomination_names_the_observed_ratio() -> None:
    item = check(crypto(frame([10.0, 10000.0])), "unflagged_split")
    assert "1/1000" in item.finding


def test_no_comparable_peer_and_median_peer_move() -> None:
    bars = frame([100.0, 50.0])
    for peers, status in [
        ([frame([100.0, 101.0], start=START + DAY * 8)], "warn"),
        ([frame([100.0, 101.0]), frame([100.0, 102.0]), frame([100.0, 180.0])], "fail"),
        ([frame([100.0, 90.0]), frame([100.0, 100.0]), frame([100.0, 110.0])], "warn"),
    ]:
        report = health_report(
            bars, symbol="X", calendar="XNYS", report_time=START + DAY * 2, peers=peers
        )
        assert check(report, "unflagged_split").status == status


def test_future_rows_preserve_a_partial_bar_finding_at_the_cutoff() -> None:
    bars = frame([100.0, 101.0, 102.0])
    cutoff = START + DAY + timedelta(hours=12)
    prior = crypto(bars.head(2), cutoff)
    poisoned = crypto(bars, cutoff)
    prior_findings = [item for item in prior.checks if cutoff.date() in item.example_dates]
    assert prior_findings
    assert [
        item for item in poisoned.checks if cutoff.date() in item.example_dates
    ] == prior_findings


def sessions(first: date, count: int) -> list[datetime]:
    days = sessions_between("XNYS", first, first + DAY * (count * 2 + 10))[:count]
    return [datetime.combine(day, datetime.min.time(), UTC) for day in days]


def stock(prices: list[float], first: date = date(2024, 1, 2)) -> pl.DataFrame:
    return frame(prices).with_columns(pl.Series("ts", sessions(first, len(prices))))


def after_last(bars: pl.DataFrame) -> datetime:
    last = bars["ts"].max()
    assert isinstance(last, datetime)
    return last + DAY


@pytest.mark.parametrize(("kept", "status"), [(0.55, "pass"), (0.62, "pass"), (0.5, "warn")])
def test_a_real_crash_is_a_split_only_when_a_split_ratio_fits(kept: float, status: str) -> None:
    bars = stock([100.0, 100.0 * kept, 100.0 * kept])
    report = health_report(bars, symbol="X", report_time=after_last(bars))
    assert check(report, "unflagged_split").status == status


def test_coarse_ticks_repeating_only_the_close_are_not_frozen() -> None:
    bars = stock([26.5] * 8).with_columns(
        pl.Series("high", [26.75, 26.625, 26.875, 26.75, 26.625, 26.75, 26.875, 26.625]),
        pl.Series("low", [26.25, 26.375, 26.125, 26.25, 26.375, 26.25, 26.125, 26.375]),
    )
    report = health_report(bars, symbol="X", report_time=after_last(bars))
    assert check(report, "stale_run").status == "pass"
    assert report.verdict == "pass"


def test_halted_days_with_no_volume_are_zero_volume_not_a_frozen_run() -> None:
    prices = [40.0 + i for i in range(14)] + [53.0] * 6
    bars = stock(prices).with_columns(pl.Series("volume", [10.0] * 14 + [0.0] * 6))
    report = health_report(bars, symbol="X", report_time=after_last(bars))
    assert check(report, "stale_run").status == "pass"
    assert check(report, "zero_volume").status == "fail"
    assert "6 of 20 bars have zero volume" in check(report, "zero_volume").finding


def test_recorded_splits_outside_the_bars_are_not_faults() -> None:
    bars = stock([100.0, 50.0, 51.0, 52.0])
    days = [ts.date() for ts in sessions(date(2024, 1, 2), 4)]

    def split(ex: date) -> CorporateAction:
        return CorporateAction(symbol="X", action_type=ActionType.SPLIT, ratio=2, ex_date=ex)

    def audit(rows: pl.DataFrame, *actions: CorporateAction) -> HealthCheck:
        report = health_report(rows, symbol="X", report_time=after_last(bars), actions=actions)
        return check(report, "recorded_splits_applied")

    assert audit(bars, split(days[1]), split(date(2019, 6, 3))).status == "pass"
    # A measurable split inside the bars whose neighbour bar is missing cannot be checked.
    assert audit(bars[[0, 2, 3]], split(days[1])).status == "warn"


def test_a_stock_listed_recently_is_judged_from_its_first_bar() -> None:
    bars = stock([20.0 + 0.1 * i for i in range(30)], first=date(2024, 6, 3))
    report = health_report(bars, symbol="X", report_time=after_last(bars))
    assert check(report, "missing_sessions").status == "pass"
    assert report.verdict == "pass"


def test_a_crypto_listing_day_with_a_wild_range_is_not_a_redenomination() -> None:
    closes = [1.0 + 0.01 * i for i in range(12)]
    bars = frame(closes).with_columns(
        pl.Series("open", [0.1, *closes[:-1]]),
        pl.Series("high", [10.0, *closes[1:]]),
        pl.Series("low", [0.05, *closes[:-1]]),
    )
    assert crypto(bars).verdict == "pass"


def test_future_stock_bars_change_no_finding_dated_before_the_report_time() -> None:
    prices = [100.0] * 30 + [50.0, 50.0] + [100.0 + i for i in range(20)]
    bars = stock(prices).with_columns(pl.Series("volume", [10.0] * 40 + [0.0] * 2 + [10.0] * 10))
    cutoff = after_last(bars)
    future = stock([200.0, 20.0, 200.0, 1.0, 1.0], first=cutoff.date() + DAY)
    poisoned = pl.concat([bars, future, future.head(1)])
    before = health_report(bars, symbol="X", report_time=cutoff, peers=[stock([100.0] * 52)])
    after = health_report(poisoned, symbol="X", report_time=cutoff, peers=[stock([100.0] * 52)])
    assert check(before, "unflagged_split").status == "fail"
    assert check(before, "zero_volume").status == "warn"
    assert check(after, "future_bar").count == 6
    assert [c for c in before.checks if c.id != "future_bar"] == [
        c for c in after.checks if c.id != "future_bar"
    ]
