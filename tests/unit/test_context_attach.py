"""The one join: context values onto bars by availability, with staleness and the reserve cut."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import polars as pl
import pytest

from alpha_core import DataError
from alpha_core.reserve import RESERVED_DAY
from alpha_data.context.attach import AttachResult, Binding, attach_context
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


def run(
    frame: pl.DataFrame,
    data_dir: Path,
    bindings: dict[str, Binding],
    *,
    calendar: str | None = None,
    cutoff: datetime = CUTOFF,
    symbol: str | None = None,
) -> AttachResult:
    return attach_context(
        frame,
        timeframe=DAILY,
        calendar=calendar,
        bindings=bindings,
        data_dir=data_dir,
        cutoff=cutoff,
        symbol=symbol,
    )


def col(result: AttachResult, name: str) -> list[object]:
    return result.frame[name].to_list()


def test_finra_day_t_is_used_by_stock_bar_t_plus_1_and_not_bar_t(tmp_path: Path) -> None:
    thu, fri, mon, tue = (date(2023, 6, n) for n in (8, 9, 12, 13))
    store_finra(tmp_path, finra_rows("SPY", [(thu, 0.2), (fri, 0.3), (mon, 0.4)]), "SPY")
    out = run(
        bars([thu, fri, mon, tue]),
        tmp_path,
        {"sv": Binding("sv_ratio", "SPY")},
        calendar="XNYS",
    )
    assert col(out, "ctx_sv") == [None, 0.2, 0.3, 0.4]  # Friday 0.3 is not used on Friday
    assert col(out, "ctx_sv_age_days") == [None, 1, 3, 1]
    assert col(out, "ctx_sv_stale") == [False, False, False, False]


def test_btc_cot_friday_release_is_used_by_the_friday_crypto_bar(tmp_path: Path) -> None:
    report = date(2023, 6, 6)  # Tuesday; rule release Friday 2023-06-09 15:30 US Eastern
    store_cot(tmp_path, cot_rows([dict(report_date=report, nl=300, ns=100, oi=1000)]), "133741")
    thu, fri, sat = date(2023, 6, 8), date(2023, 6, 9), date(2023, 6, 10)
    out = run(bars([thu, fri, sat]), tmp_path, {"p": Binding("cot_nc_net_oi", "133741")})
    got = col(out, "ctx_p")
    assert got[0] is None and got[1] == approx(0.2)
    assert got[2] == approx(0.2)
    assert col(out, "ctx_p_age_days") == [None, 4, 5]  # bar decision instant is ts + 1 day


@pytest.mark.parametrize(("age", "stale"), [(16, False), (17, False), (18, True)])
def test_cot_staleness_limit_is_17_days(tmp_path: Path, age: int, stale: bool) -> None:
    period = date(2023, 6, 6)
    store_cot(tmp_path, cot_rows([dict(report_date=period, nl=300)]))
    bar = period + timedelta(days=age - 1)  # decision instant = bar + 1 day -> date = period + age
    out = run(bars([bar]), tmp_path, {"p": Binding("cot_nc_net_oi", CODE)})
    assert col(out, "ctx_p_age_days") == [age] and col(out, "ctx_p_stale") == [stale]
    assert col(out, "ctx_p") == ([None] if stale else [approx(0.3)])


@pytest.mark.parametrize(("age", "stale"), [(5, False), (6, True)])
def test_finra_staleness_limit_is_5_days(tmp_path: Path, age: int, stale: bool) -> None:
    period = date(2023, 6, 1)
    store_finra(tmp_path, finra_rows("SPY", [(period, 0.25)]), "SPY")
    bar = period + timedelta(days=age - 1)
    out = run(bars([bar]), tmp_path, {"sv": Binding("sv_ratio", "SPY")})
    assert col(out, "ctx_sv_age_days") == [age] and col(out, "ctx_sv_stale") == [stale]
    assert col(out, "ctx_sv") == ([None] if stale else [approx(0.25)])


def test_before_any_known_row_is_null_not_stale(tmp_path: Path) -> None:
    store_cot(tmp_path, cot_rows([dict(report_date=date(2023, 6, 6), nl=300)]))
    out = run(bars([date(2023, 6, 1)]), tmp_path, {"p": Binding("cot_nc_net_oi", CODE)})
    assert col(out, "ctx_p") == [None] and col(out, "ctx_p_stale") == [False]
    assert col(out, "ctx_p_age_days") == [None] and col(out, "ctx_p_reason") == ["not-yet-known"]


def test_a_row_with_period_before_the_bar_but_known_later_is_invisible(tmp_path: Path) -> None:
    period = date(2023, 6, 6)
    late = datetime(2023, 6, 16, 20, tzinfo=UTC)  # a late stamp: known ten days after its period
    store_cot(tmp_path, cot_rows([dict(report_date=period, nl=300, known_from=late)]))
    days = [date(2023, 6, 12), date(2023, 6, 15), date(2023, 6, 16), date(2023, 6, 17)]
    out = run(bars(days), tmp_path, {"p": Binding("cot_nc_net_oi", CODE)})
    got = col(out, "ctx_p")
    assert got[:2] == [None, None] and got[2] == approx(0.3)
    assert col(out, "ctx_p_age_days")[2] == 11


def test_value_known_effective_waits_for_the_newest_input(tmp_path: Path) -> None:
    # Report B (later period) is released before report A, which it must wait for.
    a, b = date(2023, 1, 3), date(2023, 1, 10)
    release_a, release_b = (
        datetime(2023, 1, 20, 20, tzinfo=UTC),
        datetime(2023, 1, 13, 20, tzinfo=UTC),
    )
    rows = cot_rows(
        [
            dict(report_date=a, nl=100, known_from=release_a),
            dict(report_date=b, nl=200, known_from=release_b),
        ]
    )
    store_cot(tmp_path, rows)
    out = run(
        bars([date(2023, 1, 15), date(2023, 1, 21)]),
        tmp_path,
        {"p": Binding("cot_nc_net_oi", CODE)},
    )
    # bar 1: row B was released but its own cumulative maximum is A's later release
    assert col(out, "ctx_p")[0] is None
    assert col(out, "ctx_p")[1] == approx(0.2)  # latest period known


def test_shutdown_window_row_is_null_with_a_named_reason(tmp_path: Path) -> None:
    store_cot(tmp_path, cot_rows([dict(report_date=date(2019, 1, 8), nl=300)]))
    out = run(bars([date(2019, 1, 20)]), tmp_path, {"p": Binding("cot_nc_net_oi", CODE)})
    assert col(out, "ctx_p") == [None]
    assert col(out, "ctx_p_reason") == ["cot-delayed-release-unverified"]
    assert col(out, "ctx_p_stale") == [False]


def _fixture_rows(extra: bool, poison: float | None = None) -> pl.DataFrame:
    periods = [date(2023, 11, 7) + timedelta(weeks=n) for n in range(8)]
    specs = [dict(report_date=p, nl=100 + 10 * n) for n, p in enumerate(periods)]
    if extra:  # periods on or after the reserved day, including one stamped as known early
        specs.append(dict(report_date=RESERVED_DAY + timedelta(days=1), nl=900))
        specs.append(
            dict(
                report_date=RESERVED_DAY + timedelta(days=8),
                nl=900,
                known_from=datetime(2023, 12, 1, tzinfo=UTC),
            )
        )
    return cot_rows(specs)


def test_reserved_periods_never_appear_and_change_nothing(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    other = tmp_path_factory.mktemp("with-reserved")
    store_cot(tmp_path, _fixture_rows(extra=False))
    store_cot(other, _fixture_rows(extra=True))
    days = daily(date(2023, 11, 1), 120)  # runs past the reserved day
    bind = {"p": Binding("cot_nc_net_oi", CODE)}
    clean, with_extra = run(bars(days), tmp_path, bind), run(bars(days), other, bind)
    assert clean.frame.equals(with_extra.frame)
    assert clean.used_rows_sha256 == with_extra.used_rows_sha256
    stamps = clean.frame["ts"].to_list()
    assert max(stamps) < datetime.combine(RESERVED_DAY, time.min, tzinfo=UTC)
    assert 0.9 not in [v for v in col(with_extra, "ctx_p") if v is not None]
    assert clean.source_table_sha256 != with_extra.source_table_sha256  # provenance differs


@pytest.mark.parametrize(
    "cutoff",
    [datetime.combine(RESERVED_DAY, time.min, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)],
)
def test_a_cutoff_at_or_after_the_reserved_instant_is_refused(
    tmp_path: Path, cutoff: datetime
) -> None:
    store_cot(tmp_path, _fixture_rows(extra=False))
    with pytest.raises(DataError, match="reserved"):
        run(
            bars([date(2023, 11, 20)]),
            tmp_path,
            {"p": Binding("cot_nc_net_oi", CODE)},
            cutoff=cutoff,
        )


def test_a_naive_cutoff_is_refused(tmp_path: Path) -> None:
    store_cot(tmp_path, _fixture_rows(extra=False))
    with pytest.raises(DataError, match="UTC"):
        run(
            bars([date(2023, 11, 20)]),
            tmp_path,
            {"p": Binding("cot_nc_net_oi", CODE)},
            cutoff=datetime(2023, 12, 1),
        )


def test_unknown_series_and_self_key(tmp_path: Path) -> None:
    store_finra(tmp_path, finra_rows("SPY", [(date(2023, 6, 1), 0.25)]), "SPY")
    with pytest.raises(DataError, match="unknown context series"):
        run(bars([date(2023, 6, 2)]), tmp_path, {"x": Binding("nope", "SPY")})
    out = run(bars([date(2023, 6, 2)]), tmp_path, {"sv": Binding("sv_ratio", "SELF")}, symbol="SPY")
    assert col(out, "ctx_sv") == [approx(0.25)]
    with pytest.raises(DataError, match="SELF"):
        run(bars([date(2023, 6, 2)]), tmp_path, {"sv": Binding("sv_ratio", "SELF")})


def test_receipt_fields_are_recorded_and_track_used_rows(tmp_path: Path) -> None:
    store_finra(
        tmp_path, finra_rows("SPY", [(date(2023, 6, 1), 0.25), (date(2023, 6, 2), 0.35)]), "SPY"
    )
    bind = {"sv": Binding("sv_ratio", "SPY")}
    first = run(bars([date(2023, 6, 5)]), tmp_path, bind)
    assert first.recipe == "context-derived-v1" and set(first.used_rows_sha256) == {"sv"}
    assert (
        len(first.used_rows_sha256["sv"]) == 64
        and len(first.source_table_sha256["finra-short-volume:SPY"]) == 64
    )
    store_finra(
        tmp_path, finra_rows("SPY", [(date(2023, 6, 1), 0.25), (date(2023, 6, 2), 0.36)]), "SPY"
    )
    second = run(bars([date(2023, 6, 5)]), tmp_path, bind)
    assert second.used_rows_sha256 != first.used_rows_sha256


def test_breadth_label_and_count_follow_the_stored_set(tmp_path: Path) -> None:
    days = daily(date(2023, 3, 1), 61)

    def ratios(last: float, pattern: tuple[float, float]) -> list[tuple[date, float]]:
        vals = [pattern[n % 2] for n in range(60)] + [last]
        return list(zip(days, vals, strict=True))

    store_finra(tmp_path, finra_rows("AAA", ratios(0.6, (0.5, 0.5))), "AAA")
    store_finra(tmp_path, finra_rows("BBB", ratios(0.8, (0.5, 0.5))), "BBB")
    store_finra(tmp_path, finra_rows("CCC", ratios(0.5, (0.4, 0.6))), "CCC")
    out = run(
        bars([days[-1] + timedelta(days=2)]), tmp_path, {"b": Binding("sv_breadth_z1", "ALL")}
    )
    # day 61: AAA and BBB each sit 59/sqrt(60) above a flat window; CCC is near its own mean
    assert col(out, "ctx_b") == [approx(2 / 3)]
    assert out.notes["b"] == "3 stored names, not market-wide"
