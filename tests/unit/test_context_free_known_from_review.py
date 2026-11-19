"""Independent proof that a read as of t never returns a CFTC or FINRA row not public at t."""

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_core import DataError
from alpha_data.context import cftc_cot, finra_short, free_http, us_holidays
from alpha_data.context.events import as_known_events, load_events

HOLIDAYS_2023_2026 = {
    date(2023, 1, 2), date(2023, 1, 16), date(2023, 2, 20), date(2023, 5, 29), date(2023, 6, 19),
    date(2023, 7, 4), date(2023, 9, 4), date(2023, 10, 9), date(2023, 11, 10), date(2023, 11, 23),
    date(2023, 12, 25), date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19), date(2024, 5, 27),
    date(2024, 6, 19), date(2024, 7, 4), date(2024, 9, 2), date(2024, 10, 14), date(2024, 11, 11),
    date(2024, 11, 28), date(2024, 12, 25), date(2025, 1, 1), date(2025, 1, 9), date(2025, 1, 20),
    date(2025, 2, 17),
    date(2025, 5, 26), date(2025, 6, 19), date(2025, 7, 4), date(2025, 9, 1), date(2025, 10, 13),
    date(2025, 11, 11), date(2025, 11, 27), date(2025, 12, 25), date(2026, 1, 1), date(2026, 1, 19),
    date(2026, 2, 16), date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 10, 12), date(2026, 11, 11), date(2026, 11, 26), date(2026, 12, 25),
}  # fmt: skip


def eastern_offset_hours(day: date) -> int:
    """US Eastern offset by statute: DST from 2nd Sunday of March to 1st Sunday of November."""
    march = date(day.year, 3, 8) + timedelta(days=(6 - date(day.year, 3, 8).weekday()) % 7)
    nov = date(day.year, 11, 1) + timedelta(days=(6 - date(day.year, 11, 1).weekday()) % 7)
    return 4 if march <= day < nov else 5


def test_every_tuesday_2023_to_2026_matches_hand_rule() -> None:
    day = date(2023, 1, 3)
    while day < date(2026, 12, 20):
        friday = day + timedelta(days=3)
        release = friday
        if any(friday - timedelta(days=n) in HOLIDAYS_2023_2026 for n in range(5)):
            release += timedelta(days=1)
            while release.weekday() > 4 or release in HOLIDAYS_2023_2026:
                release += timedelta(days=1)
        want = datetime(release.year, release.month, release.day, 15, 30, tzinfo=UTC) + timedelta(
            hours=eastern_offset_hours(release)
        )
        assert cftc_cot.known_from(day) == want, day
        day += timedelta(days=7)


def test_known_from_never_before_friday_of_the_as_of_week_any_year() -> None:
    day = date(2000, 1, 3)
    while day < date(2045, 1, 1):
        for step in range(4):  # Monday to Thursday as-of dates
            asof = day + timedelta(days=step)
            friday = asof + timedelta(days=4 - asof.weekday())
            floor = datetime(friday.year, friday.month, friday.day, 20, 30, tzinfo=UTC)
            assert cftc_cot.known_from(asof) >= floor - timedelta(hours=1), asof
        day += timedelta(days=7)


def test_holiday_rule_has_no_year_gap_and_extra_closures_push_later() -> None:
    for year in range(1990, 2060):
        assert len(us_holidays.federal_holidays(year)) == 11
    assert us_holidays.is_us_federal_holiday(date(2018, 12, 5))  # Bush day of mourning
    assert us_holidays.is_us_federal_holiday(date(2025, 1, 9))  # Carter day of mourning
    assert cftc_cot.known_from(date(2018, 12, 4)) == datetime(2018, 12, 10, 20, 30, tzinfo=UTC)


def stamped(period: date, stamp: str) -> dict[str, Any]:
    base = {k: "10" for k in cftc_cot._COUNTS.values()}
    return {
        **base,
        "cftc_contract_market_code": "13874A",
        "market_and_exchange_names": "E-MINI",
        "report_date_as_yyyy_mm_dd": f"{period}T00:00:00.000",
        ":created_at": stamp,
    }


@pytest.mark.parametrize("late_days", [20, 45, 70, 119])
def test_shutdown_late_stamp_wins_over_rule(late_days: int) -> None:
    period = date(2025, 10, 7)
    rule = cftc_cot.known_from(period)
    stamp = rule + timedelta(days=late_days, seconds=17)
    iso = stamp.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    row = cftc_cot.map_rows([stamped(period, iso)], "13874A").row(0, named=True)
    assert row["known_basis"] == "stamp"
    assert row["known_from"] == stamp.replace(microsecond=0)
    seen = as_known_events(
        cftc_cot.map_rows([stamped(period, iso)], "13874A"), as_of=rule + timedelta(days=1)
    )
    assert seen.is_empty()


def test_known_from_is_never_earlier_than_the_rule() -> None:
    period = date(2024, 1, 9)
    rule = cftc_cot.known_from(period)
    for shift in (-400, -30, -1, 0, 1, 30, 119, 120, 121, 900):
        stamp = (rule + timedelta(days=shift)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        got = cftc_cot.map_rows([stamped(period, stamp)], "13874A")["known_from"][0]
        assert got >= rule, shift


def test_rule_only_era_is_labelled() -> None:
    old = cftc_cot.map_rows([stamped(date(2019, 3, 5), "2022-09-13T12:00:00.000Z")], "13874A")
    assert old["known_basis"][0] == "rule-only-era"
    assert old["known_from"][0] == cftc_cot.known_from(date(2019, 3, 5))
    new = cftc_cot.map_rows([stamped(date(2024, 1, 9), "2024-01-09T00:00:00.000Z")], "13874A")
    assert new["known_basis"][0] == "rule"


@pytest.mark.parametrize("stamp", [None, "", "yesterday", "2024-01-12 20:30:47"])
def test_missing_or_unparsable_stamp_fails_loud_never_early(stamp: str | None) -> None:
    record = stamped(date(2024, 1, 9), "x")
    record[":created_at"] = stamp
    with pytest.raises(DataError, match="created_at"):
        cftc_cot.map_rows([record], "13874A")


def test_finra_known_from_is_after_any_plausible_publication() -> None:
    day = date(2023, 1, 2)
    while day < date(2027, 1, 1):
        known = finra_short.known_from(day)
        next_day = day + timedelta(days=1)
        assert known >= datetime(next_day.year, next_day.month, next_day.day, 12, tzinfo=UTC), day
        # 22:00 Eastern on the trade date is the latest imaginable posting; the rule is after it.
        latest = datetime(day.year, day.month, day.day, 22, tzinfo=UTC) + timedelta(
            hours=eastern_offset_hours(day)
        )
        assert known > latest, day
        day += timedelta(days=1)


def finra_file(day: str, symbols: list[str]) -> bytes:
    rows = [f"{day}|{s}|10|0|20|N" for s in symbols]
    head = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market"
    return "\n".join([head, *rows, str(len(rows))]).encode()


def leaky_read(df: pl.DataFrame, as_of: datetime) -> pl.DataFrame:
    """Deliberately wrong reader: filters on the period, ignores known_from."""
    period = "trade_date" if "trade_date" in df.columns else "report_date"
    return df.filter(pl.col(period) <= as_of.date())


def assert_no_unpublished(
    read: Callable[[pl.DataFrame, datetime], pl.DataFrame], df: pl.DataFrame
) -> None:
    for known in df["known_from"].to_list():
        for as_of in (known - timedelta(microseconds=1), known, known + timedelta(hours=1)):
            got = read(df, as_of)
            assert got.filter(pl.col("known_from") > as_of).is_empty()
            assert (known in got["known_from"].to_list()) == (as_of >= known)


def real_read(df: pl.DataFrame, as_of: datetime) -> pl.DataFrame:
    return as_known_events(df, as_of=as_of)


def stored_frames(tmp_path: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    def transport(
        url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        day = url.rsplit("shvol", 1)[1][:8]
        return 200, {}, finra_file(day, ["SPY"])

    finra_short.pull_short_volume(
        data_dir=tmp_path, symbols=["SPY"], start=date(2024, 1, 2), end=date(2024, 1, 3),
        fetched_at=datetime(2024, 2, 1, tzinfo=UTC), client=free_http.Client(transport=transport),
    )  # fmt: skip
    finra = load_events(
        finra_short.table_path(tmp_path, "SPY"),
        source=finra_short.SOURCE,
        schema=finra_short.SCHEMA,
    )
    cot = cftc_cot.map_rows(
        [stamped(date(2024, 1, 9), "2024-01-12T20:30:47.123Z"),
         stamped(date(2024, 1, 16), "2024-01-22T20:30:49.000Z")],
        "13874A",
    )  # fmt: skip
    return finra, cot


def test_real_reader_passes_and_leaky_control_fails(tmp_path: Path) -> None:
    finra, cot = stored_frames(tmp_path)
    for frame in (finra, cot):
        assert_no_unpublished(real_read, frame)
        with pytest.raises(AssertionError):
            assert_no_unpublished(leaky_read, frame)


def test_finra_revision_refused_and_file_bytes_unchanged(tmp_path: Path) -> None:
    stored_frames(tmp_path)
    path = finra_short.table_path(tmp_path, "SPY")
    before = (path.read_bytes(), path.with_suffix(".json").read_bytes())

    def changed(
        url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        day = url.rsplit("shvol", 1)[1][:8]
        return 200, {}, finra_file(day, ["SPY"]).replace(b"|10|0|20|", b"|11|0|20|")

    with pytest.raises(DataError, match="revised"):
        finra_short.pull_short_volume(
            data_dir=tmp_path, symbols=["SPY"], start=date(2024, 1, 2), end=date(2024, 1, 2),
            fetched_at=datetime(2024, 3, 1, tzinfo=UTC), client=free_http.Client(transport=changed),
        )  # fmt: skip
    assert before == (path.read_bytes(), path.with_suffix(".json").read_bytes())


@pytest.mark.parametrize("symbol", ["../X", "A/B", "a", "A\x00", "A\n", "A B", "", "..", "A" * 11])
def test_symbols_never_reach_a_path_unescaped(symbol: str, tmp_path: Path) -> None:
    with pytest.raises(DataError):
        finra_short.table_path(tmp_path, symbol)


def test_slash_symbol_in_a_file_cannot_become_a_file_name(tmp_path: Path) -> None:
    raw = finra_file("20240102", ["BRK/B", "ABCp", "SPY"])
    frame = finra_short.map_file(raw, date(2024, 1, 2), {"SPY"})
    assert frame["symbol"].to_list() == ["SPY"]
    with pytest.raises(DataError):
        finra_short.map_file(finra_file("20240102", ["../x"]), date(2024, 1, 2), None)
    with pytest.raises(DataError):
        finra_short.table_path(tmp_path, "BRK/B")


def test_no_network_when_transport_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: Any) -> Any:
        raise OSError("network blocked")

    monkeypatch.setattr(free_http, "default_transport", refuse)
    with pytest.raises(DataError, match="offline"):
        free_http.Client().get("https://example.invalid/x", "T")
    assert free_http.USER_AGENT == "Project-ALPHA/1.0"
