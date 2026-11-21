"""Review cases for the context join: late releases, the cutoff, one boundary, hand values."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from alpha_cli.spine import reserve as spine_reserve
from alpha_core import DataError, reserve
from alpha_data.context import attach, derived
from alpha_data.context.attach import Binding, attach_context
from alpha_data.sessions import bar_known_at
from alpha_data.timeframe import DAILY
from tests.unit._context_attach_support import (
    CODE,
    CUTOFF,
    approx,
    bars,
    cot_rows,
    daily,
    finra_rows,
    store_cot,
    store_finra,
)


def _on(frame_days: list[date], data_dir: Path, binding: Binding, calendar: str | None) -> list:
    out = attach_context(
        bars(frame_days),
        timeframe=DAILY,
        calendar=calendar,
        bindings={"v": binding},
        data_dir=data_dir,
        cutoff=CUTOFF,
    )
    return out.frame["ctx_v"].to_list()


@pytest.mark.parametrize("basis", ["rule-only-era", "rule"])
def test_a_rule_only_cot_time_waits_one_day_so_a_late_release_cannot_leak(
    tmp_path: Path, basis: str
) -> None:
    # The rule says Friday 15:30 US Eastern; a late release (seen in stamped weeks) can come after
    # the 16:00 close. Without a stamp, the Friday stock bar must not use the report.
    report = date(2019, 6, 4) if basis == "rule-only-era" else date(2023, 6, 6)
    store_cot(tmp_path, cot_rows([dict(report_date=report, nl=300, basis=basis)]))
    fri, mon = report + timedelta(days=3), report + timedelta(days=6)
    got = _on([fri, mon], tmp_path, Binding("cot_nc_net_oi", CODE), "XNYS")
    assert got[0] is None and got[1] == approx(0.3)


def test_a_stamped_cot_release_before_the_close_is_used_that_day(tmp_path: Path) -> None:
    report = date(2023, 6, 6)
    stamp = datetime(2023, 6, 9, 19, 30, 5, tzinfo=UTC)  # 15:30:05 US Eastern (summer time)
    store_cot(tmp_path, cot_rows([dict(report_date=report, nl=300, known_from=stamp)]))
    got = _on([date(2023, 6, 9)], tmp_path, Binding("cot_nc_net_oi", CODE), "XNYS")
    assert got == [approx(0.3)]


def test_a_row_moved_past_the_cutoff_by_the_margin_never_reaches_the_last_crypto_bar(
    tmp_path: Path,
) -> None:
    # Stored known_from is inside the cutoff; with the one-day margin it lands on the reserved
    # instant, which is the decision instant of the 2023-12-31 crypto bar. It must stay unused.
    report = date(2023, 12, 26)
    known = reserve.RESERVED_INSTANT - timedelta(days=1)
    store_cot(
        tmp_path, cot_rows([dict(report_date=report, nl=300, known_from=known, basis="rule")])
    )
    assert _on([date(2023, 12, 31)], tmp_path, Binding("cot_nc_net_oi", CODE), None) == [None]


def test_the_reserved_instant_has_one_home_in_core() -> None:
    assert attach.RESERVED_INSTANT is reserve.RESERVED_INSTANT
    assert spine_reserve.RESERVED_INSTANT is reserve.RESERVED_INSTANT
    assert datetime(2024, 1, 1, tzinfo=UTC) == reserve.RESERVED_INSTANT


def test_finra_on_a_half_day_and_after_a_holiday(tmp_path: Path) -> None:
    wed, fri, mon = date(2023, 11, 22), date(2023, 11, 24), date(2023, 11, 27)  # Thu: holiday
    store_finra(tmp_path, finra_rows("SPY", [(wed, 0.2), (fri, 0.3), (mon, 0.4)]), "SPY")
    got = _on([wed, fri, mon], tmp_path, Binding("sv_ratio", "SPY"), "XNYS")
    assert got == [None, approx(0.2), approx(0.3)]  # the half-day bar closes 18:00 UTC


def test_the_early_bar_stand_in_is_never_earlier_than_the_true_instant() -> None:
    for day in daily(date(2007, 1, 1), 365 * 17):
        ts = datetime(day.year, day.month, day.day, tzinfo=UTC)
        assert bar_known_at(ts, timeframe=DAILY, calendar="XNYS") <= ts + DAILY.duration


def test_hand_values_for_the_cot_series() -> None:
    specs = [
        dict(report_date=date(2020, 1, 7) + timedelta(weeks=i), nl=(i % 10) * 10, cl=i % 3)
        for i in range(156)
    ]
    rows = cot_rows(specs)
    net = derived.derive_cot(rows, "cot_nc_net_oi")["value"].to_list()
    assert net[7] == approx(0.07)
    pct = derived.derive_cot(rows, "cot_nc_net_pct_156w")["value"].to_list()
    # last value 0.05: 80 smaller (digits 0..4, 16 each), 16 equal -> rank 88.5 of 156
    assert pct[154] is None and pct[155] == approx(87.5 / 155)
    chg = derived.derive_cot(rows, "cot_nc_net_chg_4w")["value"].to_list()
    assert chg[3] is None and chg[4] == approx(0.04) and chg[6] == approx(0.04)
    gap = derived.derive_cot(rows, "cot_comm_nc_gap_pct_156w")["value"].to_list()
    # gap_i = (i % 3 - 10 * (i % 10)) / 1000; the last (i = 155) is (2 - 50) / 1000
    values = [(i % 3 - 10 * (i % 10)) / 1000 for i in range(156)]
    less, equal = sum(v < values[-1] for v in values), sum(v == values[-1] for v in values)
    assert gap[155] == approx((less + (equal + 1) / 2 - 1) / 155)


def test_hand_values_for_the_percentile_edges() -> None:
    assert derived.rolling_pct([1.0, None, 3.0, 2.0], 4) == [None, None, None, 0.5]
    assert derived.rolling_pct([None, None, None, 5.0], 4) == [None] * 4  # n = 1
    assert derived.rolling_pct([2.0, 2.0, 2.0], 3)[2] == approx(0.5)  # all tied


def test_hand_values_for_the_finra_series() -> None:
    days = daily(date(2022, 1, 3), 60)
    ratios = [0.1] * 59 + [0.7]
    rows = finra_rows("SPY", list(zip(days, ratios, strict=True)))
    assert derived.derive_sv(rows, "sv_ratio")["value"][59] == approx(0.7)
    five = derived.derive_sv(rows, "sv_ratio_5d")["value"].to_list()
    assert five[3] is None and five[59] == approx((0.4 + 0.7) / 5)
    z = derived.derive_sv(rows, "sv_ratio_z_60d")["value"].to_list()
    # mean 0.11; sample variance (59 * 0.01**2 + 0.59**2) / 59 = 0.006
    assert z[58] is None and z[59] == approx(0.59 / math.sqrt(0.354 / 59))


def test_finra_total_volume_zero_and_nan_fail_loud() -> None:
    zero = finra_rows("SPY", [(date(2022, 1, 3), 0.0)]).with_columns(total_volume=0.0)
    with pytest.raises(DataError, match="total_volume"):
        derived.derive_sv(zero, "sv_ratio")
    nan = finra_rows("SPY", [(date(2022, 1, 3), 0.1)]).with_columns(short_volume=float("nan"))
    with pytest.raises(DataError, match="short_volume"):
        derived.derive_sv(nan, "sv_ratio")
