"""Known answers for the portfolio book maths: correlation, common days, overlap, account shares."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from alpha_cli.spine import book

DAY0 = date(2020, 1, 1)


def near(value: float) -> object:
    return pytest.approx(value, rel=1e-9, abs=1e-12)


def days(n: int, start: date = DAY0, step: int = 1) -> tuple[date, ...]:
    return tuple(start + timedelta(days=i * step) for i in range(n))


def levels(returns: list[float]) -> tuple[float, ...]:
    out = [1.0]
    for r in returns:
        out.append(out[-1] * (1.0 + r))
    return tuple(out)


def wave(n: int) -> list[float]:
    """n returns that repeat +2%, -1%, +0.5%: not constant, easy to shift by hand."""
    return [(0.02, -0.01, 0.005)[i % 3] for i in range(n)]


def series(
    run_id: str,
    returns: list[float],
    *,
    start: date = DAY0,
    held: tuple[bool, ...] | None = None,
) -> book.DailySeries:
    return book.DailySeries(run_id, days(len(returns) + 1, start), levels(returns), held)


def test_correlation_of_three_points_by_hand() -> None:
    # x = 1,2,3 and y = 1,3,2: covariance 0.5, both variances 1.0 (n - 1), so r = 0.5.
    assert book.correlation([1.0, 2.0, 3.0], [1.0, 3.0, 2.0]) == near(0.5)
    assert book.correlation([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == near(-1.0)


def test_correlation_of_a_constant_series_is_not_defined() -> None:
    assert book.correlation([0.0, 0.0, 0.0], [1.0, 3.0, 2.0]) is None


def test_two_identical_series_correlate_at_one() -> None:
    a, b = series("a" * 16, wave(90)), series("b" * 16, wave(90))
    pair = book.pair_reading(a, b)
    assert pair["common_days"] == 90
    assert pair["correlation"] == near(1.0)
    assert pair["correlation_reason"] is None
    assert pair["first_day"] == "2020-01-02" and pair["last_day"] == "2020-03-31"


def test_a_series_shifted_by_one_day_gives_the_lagged_answer() -> None:
    # +1%, -1%, +1% ... against the same pattern one day later: every day has the other sign.
    up_down = [0.01 if i % 2 == 0 else -0.01 for i in range(80)]
    a = series("a" * 16, up_down)
    b = series("b" * 16, up_down, start=DAY0 + timedelta(days=1))
    pair = book.pair_reading(a, b)
    assert pair["common_days"] == 79
    assert pair["correlation"] == near(-1.0)


def test_disjoint_dates_are_too_few_and_print_no_correlation() -> None:
    a = series("a" * 16, wave(90))
    b = series("b" * 16, wave(90), start=date(2021, 6, 1))
    pair = book.pair_reading(a, b)
    assert pair["common_days"] == 0
    assert pair["correlation"] is None
    assert pair["correlation_reason"] == "too few common days to read"
    assert pair["overlap_share"] is None
    assert "too few common days to read" in pair["sentence"]


def test_fifty_nine_common_days_are_too_few_and_sixty_are_read() -> None:
    a = series("a" * 16, wave(59))
    assert book.pair_reading(a, a)["correlation"] is None
    assert book.pair_reading(a, a)["common_days"] == 59
    b = series("b" * 16, wave(60))
    assert book.pair_reading(b, b)["correlation"] == near(1.0)


def test_a_flat_series_has_no_defined_correlation() -> None:
    a = series("a" * 16, wave(70))
    flat = series("b" * 16, [0.0] * 70)
    pair = book.pair_reading(a, flat)
    assert pair["common_days"] == 70
    assert pair["correlation"] is None
    assert pair["correlation_reason"] == "not defined: the returns of one run do not change"
    assert "not defined" in pair["sentence"]


def test_returns_are_taken_between_common_dates() -> None:
    # b has every second day of a. Its level equals a's on those days, so over the common
    # dates both have the same two-day returns: correlation 1.0 on 70 common days.
    a = series("a" * 16, wave(140))
    b = book.DailySeries("b" * 16, a.days[::2], a.equity[::2], None)
    pair = book.pair_reading(a, b)
    assert pair["common_days"] == 70
    assert pair["correlation"] == near(1.0)


def test_overlap_share_by_hand() -> None:
    # Four common days. a is in the market on days 1, 2, 3; b on days 2, 3, 4: both on 2 of 4.
    a = series("a" * 16, wave(4), held=(False, True, True, True, False))
    b = series("b" * 16, wave(4), held=(False, False, True, True, True))
    pair = book.pair_reading(a, b)
    assert pair["both_in_market_days"] == 2
    assert pair["overlap_share"] == near(0.5)
    assert pair["correlation"] is None  # four days: too few


def test_overlap_over_a_gap_counts_a_day_held_inside_the_gap() -> None:
    # b skips every second day. a held only on the skipped days, so a was in the market
    # inside every common interval; b held on every interval: both on 3 of 3.
    a = series("a" * 16, wave(6), held=(False, True, False, True, False, True, False))
    b = book.DailySeries("b" * 16, a.days[::2], a.equity[::2], (False, True, True, True))
    pair = book.pair_reading(a, b)
    assert pair["common_days"] == 3
    assert pair["both_in_market_days"] == 3
    assert pair["overlap_share"] == near(1.0)


def test_overlap_is_not_available_when_a_run_stored_no_exposure() -> None:
    a = series("a" * 16, wave(70), held=(False, *([True] * 70)))
    b = series("b" * 16, wave(70))
    pair = book.pair_reading(a, b)
    assert pair["overlap_share"] is None
    assert pair["overlap_reason"] == f"run {'b' * 16} stored no exposure"
    assert pair["correlation"] == near(1.0)


def test_the_sentence_is_a_reading_without_advice() -> None:
    held = (False, *([True] * 90))
    a = series("a" * 16, wave(90), held=held)
    b = series("b" * 16, wave(90), held=held)
    sentence = book.pair_reading(a, b)["sentence"]
    assert sentence == (
        f"Runs {'a' * 16} and {'b' * 16}: daily returns moved closely together "
        "(correlation 1.00) over 90 common days; both were in the market on 100% of them."
    )
    for word in ("should", "buy", "sell", "profit", "pass", "fail", "safe", "diversif"):
        assert word not in sentence.lower()


def test_invalid_series_fail_loud() -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        book.DailySeries("a" * 16, days(3), (1.0, float("nan"), 1.0), None)
    with pytest.raises(ValueError, match="finite and positive"):
        book.DailySeries("a" * 16, days(3), (1.0, 0.0, 1.0), None)
    with pytest.raises(ValueError, match="one equity value per day"):
        book.DailySeries("a" * 16, days(3), (1.0, 1.0), None)
    with pytest.raises(ValueError, match="strictly increasing"):
        book.DailySeries("a" * 16, (DAY0, DAY0, DAY0), (1.0, 1.0, 1.0), None)
    with pytest.raises(ValueError, match="one exposure value per day"):
        book.DailySeries("a" * 16, days(3), (1.0, 1.0, 1.0), (True,))


def test_correlate_reads_every_pair_and_refuses_bad_counts() -> None:
    runs = [series(c * 16, wave(70)) for c in "abc"]
    result = book.correlate(runs)
    assert [p["runs"] for p in result["pairs"]] == [
        ["a" * 16, "b" * 16],
        ["a" * 16, "c" * 16],
        ["b" * 16, "c" * 16],
    ]
    assert result["min_common_days"] == 60
    with pytest.raises(ValueError, match="2 to 8"):
        book.correlate(runs[:1])
    with pytest.raises(ValueError, match="twice"):
        book.correlate([runs[0], runs[0]])


def _rows() -> list[book.AccountRow]:
    return [
        {"follow_id": "f1", "name": "one", "assets": ["AAA"], "size_pct": 60.0, "open": True},
        {"follow_id": "f2", "name": "two", "assets": ["AAA"], "size_pct": 30.0, "open": True},
        {"follow_id": "f3", "name": "three", "assets": ["BBB"], "size_pct": 40.0, "open": False},
    ]


def test_account_view_adds_sizes_and_exposure_per_asset() -> None:
    view = book.account_view(_rows())
    assert view["total_pct"] == near(130.0)
    assert view["in_market_pct"] == near(90.0)
    assert view["assets"] == [
        {"asset": "AAA", "size_pct": near(90.0), "in_market_pct": near(90.0), "follows": 2},
        {"asset": "BBB", "size_pct": near(40.0), "in_market_pct": near(0.0), "follows": 1},
    ]
    assert view["above_account"] is True
    assert view["sentence"] == "The follows together use 130% of the paper account."
    assert "The follows together use 130% of the paper account." in book.render_account(view)


def test_account_view_at_or_under_one_account_prints_no_line() -> None:
    view = book.account_view(_rows()[1:])
    assert view["total_pct"] == near(70.0)
    assert view["above_account"] is False and view["sentence"] is None
    assert "together use" not in book.render_account(view)
    exact = book.account_view(
        [{"follow_id": "f", "name": "n", "assets": ["A"], "size_pct": 100.0, "open": False}]
    )
    assert exact["above_account"] is False


def test_account_view_with_no_follows() -> None:
    view = book.account_view([])
    assert view["total_pct"] == 0.0 and view["assets"] == [] and view["follows"] == []
    assert book.render_account(view).startswith("No active follows yet (paper).")


def test_days_dropped_from_each_run_are_counted_and_said() -> None:
    # a is a weekday-and-weekend run (140 days); b keeps every second day (70 days).
    a = series("a" * 16, wave(139))
    b = book.DailySeries("b" * 16, a.days[::2], a.equity[::2], None)
    pair = book.pair_reading(a, b)
    assert pair["dropped_days"] == {"a" * 16: 70, "b" * 16: 0}
    assert "dropped 70 days from run " + "a" * 16 in pair["sentence"]
    assert "from run " + "b" * 16 not in pair["sentence"]


def test_no_dropped_days_says_nothing_about_dropping() -> None:
    pair = book.pair_reading(series("a" * 16, wave(90)), series("b" * 16, wave(90)))
    assert pair["dropped_days"] == {"a" * 16: 0, "b" * 16: 0}
    assert "dropped" not in pair["sentence"]


def test_the_header_says_the_returns_are_net_of_fees() -> None:
    result = book.correlate([series("a" * 16, wave(90)), series("b" * 16, wave(90))])
    assert "net of fees" in book.render_correlate(result)
