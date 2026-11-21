"""Known answers for the eight derived context series (recipe context-derived-v1)."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

import polars as pl
import pytest

from alpha_core import DataError
from alpha_data.context import derived
from alpha_data.context.events import TIME
from tests.unit._context_attach_support import approx, cot_rows, daily, finra_rows, weekly

START_2014 = date(2014, 1, 7)
START_2016 = date(2015, 12, 22)


def values(frame: pl.DataFrame) -> list[float | None]:
    out: list[float | None] = frame["value"].to_list()
    return out


def test_recipe_name_and_series_names() -> None:
    assert derived.RECIPE == "context-derived-v1"
    assert derived.COT_SERIES == (
        "cot_nc_net_oi",
        "cot_nc_net_pct_156w",
        "cot_comm_nc_gap_pct_156w",
        "cot_nc_net_chg_4w",
    )
    assert derived.FINRA_SERIES == ("sv_ratio", "sv_ratio_5d", "sv_ratio_z_60d", "sv_breadth_z1")
    assert derived.STALE_DAYS == {"cot": 17, "finra": 5}


def test_cot_net_over_open_interest() -> None:
    rows = cot_rows(
        [
            dict(report_date=date(2020, 1, 7), nl=600, ns=200, oi=1000),
            dict(report_date=date(2020, 1, 14), nl=100, ns=300, oi=500),
        ]
    )
    assert values(derived.derive_cot(rows, "cot_nc_net_oi")) == [
        approx(0.4),
        approx(-0.4),
    ]


def test_rolling_pct_average_rank_for_ties() -> None:
    # window 4 over [1, 2, 2, 3]: the last value 3 is the maximum -> 1.0; at index 2 the
    # window is too short -> None. A tie: [5, 1, 5, 3] last=3: less=1, equal=1 -> rank 2.
    assert derived.rolling_pct([1.0, 2.0, 2.0, 3.0], 4) == [None, None, None, approx(1.0)]
    # [4, 2, 2, 2]: last=2, less=0, equal=3 -> average rank 2.0 -> (2-1)/(4-1) = 1/3
    assert derived.rolling_pct([4.0, 2.0, 2.0, 2.0], 4)[3] == approx(1 / 3)


def test_rolling_pct_skips_unknown_values_but_keeps_window_positions() -> None:
    # window 4: [1, None, 3, 2]: available {1,3,2}; last=2 -> rank 2 of 3 -> (2-1)/(3-1) = 0.5
    assert derived.rolling_pct([1.0, None, 3.0, 2.0], 4)[3] == approx(0.5)
    # a None at the current position stays None
    assert derived.rolling_pct([1.0, 2.0, 3.0, None], 4)[3] is None


def test_pct_156w_known_answer_ties_and_warm_up() -> None:
    specs = [dict(report_date=d, nl=i) for i, d in enumerate(weekly(START_2014, 158))]
    specs[156]["nl"] = 0
    specs[157]["nl"] = 77
    out = values(derived.derive_cot(cot_rows(specs), "cot_nc_net_pct_156w"))
    assert all(v is None for v in out[:155])  # warm-up: 156 reports
    assert out[155] == approx(1.0)  # newest value is the maximum of its window
    assert out[156] == approx(0.0)  # newest value is the minimum
    # window rows 2..157: 75 values 2..76 and the 0 are below 77; two values equal 77.
    assert out[157] == approx((76 + 1.5 - 1) / 155)


def test_gap_pct_156w_known_answer() -> None:
    specs = [
        dict(report_date=d, cl=i, cs=0, nl=0, ns=0) for i, d in enumerate(weekly(START_2014, 157))
    ]
    out = values(derived.derive_cot(cot_rows(specs), "cot_comm_nc_gap_pct_156w"))
    assert out[154] is None and out[155] == approx(1.0)
    assert out[156] == approx(1.0)


def test_net_change_over_four_reports() -> None:
    specs = [
        dict(report_date=d, nl=n)
        for d, n in zip(weekly(START_2014, 6), [0, 100, 50, 10, 400, 30], strict=True)
    ]
    out = values(derived.derive_cot(cot_rows(specs), "cot_nc_net_chg_4w"))
    assert out[:4] == [None] * 4  # warm-up: 5 reports
    assert out[4] == approx(0.4)  # (400 - 0) / 1000
    assert out[5] == approx(-0.07)  # (30 - 100) / 1000


def test_known_eff_is_the_cumulative_maximum_of_known_from() -> None:
    t = [datetime(2020, 1, d, tzinfo=UTC) for d in (20, 10, 15, 30)]
    specs = [
        dict(report_date=p, known_from=k)
        for p, k in zip(weekly(date(2020, 1, 7), 4), t, strict=True)
    ]
    frame = derived.derive_cot(cot_rows(specs), "cot_nc_net_oi")
    assert frame["known_eff"].to_list() == [t[0], t[0], t[0], t[3]]
    assert frame.schema["known_eff"] == TIME


def test_cot_non_finite_input_fails_loud() -> None:
    rows = cot_rows([dict(report_date=date(2020, 1, 7), nl=5, oi=0)])
    with pytest.raises(DataError, match="open_interest"):
        derived.derive_cot(rows, "cot_nc_net_oi")


def test_shutdown_windows_are_one_named_constant_with_inclusive_ends() -> None:
    assert (
        (date(2018, 12, 18), date(2019, 3, 5)),
        (date(2013, 10, 1), date(2013, 10, 29)),
    ) == derived.SHUTDOWN_WINDOWS
    assert derived.UNVERIFIED == "cot-delayed-release-unverified"


def test_rule_only_rows_in_a_shutdown_window_are_unknown() -> None:
    # 2015-12-22 + n weeks: n=155 is 2018-12-11 (outside), 156 is 2018-12-18 (window start).
    specs = [dict(report_date=d, nl=i) for i, d in enumerate(weekly(START_2016, 173))]
    frame = derived.derive_cot(cot_rows(specs), "cot_nc_net_pct_156w")
    out, reason = values(frame), frame["reason"].to_list()
    assert out[155] == approx(1.0) and reason[155] is None
    for n in (156, 157, 167):  # 2018-12-18, 2018-12-25, 2019-03-05 (window end, inclusive)
        assert out[n] is None and reason[n] == "cot-delayed-release-unverified"
    # 2019-03-12 is outside; the window holds 156 reports, 12 of them unknown: 144 are ranked.
    assert out[168] == approx(1.0) and reason[168] is None
    # the 4-report change is null while either end is unknown, defined once both are known
    chg = values(derived.derive_cot(cot_rows(specs), "cot_nc_net_chg_4w"))
    assert chg[168] is None  # the earlier end, report 164, is unknown
    assert chg[172] == approx(0.004)


def test_a_known_basis_stamp_row_in_a_window_is_not_dropped() -> None:
    specs = [dict(report_date=date(2019, 1, 8), nl=100, basis="stamp")]
    assert values(derived.derive_cot(cot_rows(specs), "cot_nc_net_oi")) == [approx(0.1)]


def test_sv_ratio_and_five_day_mean() -> None:
    ratios = [0.1, 0.2, 0.3, 0.4, 0.5, 0.9]
    items = list(zip(daily(date(2023, 6, 1), 6), ratios, strict=True))
    rows = finra_rows("SPY", items)
    assert values(derived.derive_sv(rows, "sv_ratio")) == [approx(r) for r in ratios]
    out = values(derived.derive_sv(rows, "sv_ratio_5d"))
    assert out[:4] == [None] * 4
    assert out[4] == approx(0.3)
    assert out[5] == approx(0.46)  # (0.2 + 0.3 + 0.4 + 0.5 + 0.9) / 5


def test_sv_z_60d_known_answer_warm_up_and_zero_std() -> None:
    flat = [0.5] * 59
    rows = finra_rows("SPY", list(zip(daily(date(2023, 1, 1), 60), [*flat, 0.6], strict=True)))
    out = values(derived.derive_sv(rows, "sv_ratio_z_60d"))
    assert all(v is None for v in out[:59])  # warm-up: 60 days; std 0 on the flat prefix anyway
    # one value 0.1 above 59 equal values: z = 59 / sqrt(60) with the sample std (ddof 1)
    assert out[59] == approx(59 / math.sqrt(60))
    same = finra_rows("SPY", list(zip(daily(date(2023, 1, 1), 60), [0.5] * 60, strict=True)))
    assert values(derived.derive_sv(same, "sv_ratio_z_60d"))[59] is None  # std 0 -> null


def test_sv_non_finite_input_fails_loud() -> None:
    rows = finra_rows("SPY", [(date(2023, 6, 1), 0.2)]).with_columns(total_volume=pl.lit(0.0))
    with pytest.raises(DataError, match="total_volume"):
        derived.derive_sv(rows, "sv_ratio")
    with pytest.raises(DataError, match="short_volume"):
        derived.derive_sv(
            finra_rows("SPY", [(date(2023, 6, 1), 0.2)]).with_columns(
                short_volume=pl.lit(math.nan)
            ),
            "sv_ratio",
        )


def _z(rows: list[tuple[date, float | None, datetime]]) -> pl.DataFrame:
    return pl.DataFrame(
        dict(
            period=[r[0] for r in rows],
            known_eff=[r[2] for r in rows],
            value=[r[1] for r in rows],
            reason=[None] * len(rows),
        ),
        schema=dict(period=pl.Date, known_eff=TIME, value=pl.Float64, reason=pl.String),
    )


def test_breadth_share_of_symbols_above_one_and_label() -> None:
    d1, d2 = date(2023, 6, 1), date(2023, 6, 2)
    k = [datetime(2023, 6, n, 12, tzinfo=UTC) for n in (2, 3, 4, 5)]
    out = derived.derive_breadth(
        {
            "A": _z([(d1, 2.0, k[0]), (d2, 3.0, k[1])]),
            "B": _z([(d1, 0.0, k[2]), (d2, 1.5, k[1])]),
            "C": _z([(d2, None, k[3])]),  # a row with no usable z is not counted
        }
    )
    assert out["period"].to_list() == [d1, d2]
    assert values(out) == [approx(0.5), approx(1.0)]
    # known_eff: newest input over the symbols read, then a running maximum
    assert out["known_eff"].to_list() == [k[2], k[3]]
    assert derived.breadth_label(3) == "3 stored names, not market-wide"
