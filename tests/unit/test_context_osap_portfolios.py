"""Published-factor return series: units, known-from clock, vintages, strict parsing, no leaks."""

import io
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from alpha_core import DataError
from alpha_data.context import free_http, osap_catalogue, osap_portfolios
from alpha_data.context.events import load_events

FIX = Path(__file__).parents[1] / "fixtures/context/osap/signal_doc_sample.csv"
NOW = datetime(2024, 2, 1, tzinfo=UTC)
RELEASED = date(2024, 1, 15)
MONTHS = [date(2023, 10, 31), date(2023, 11, 30), date(2023, 12, 31)]


def docs() -> list[osap_catalogue.SignalDoc]:
    return osap_catalogue.parse_signal_doc(FIX.read_bytes())


def wide(
    months: list[date] | None = None,
    extra: dict[str, list[float | None]] | None = None,
    scale: float = 1.0,
) -> bytes:
    """A wide long-short file in the source's real layout: date, then one column per predictor."""
    dates = months or MONTHS
    columns: dict[str, Any] = {"date": dates}
    columns["SynthAccrual"] = [5.0 * scale, -2.5 * scale, None][: len(dates)]
    columns["SynthMom"] = [1.0 * scale, 2.0 * scale, 3.0 * scale][: len(dates)]
    columns["SynthOption"] = [None, 0.5 * scale, -0.5 * scale][: len(dates)]
    columns.update(extra or {})
    frame = pl.DataFrame(columns, schema_overrides={"date": pl.Date})
    buffer = io.BytesIO()
    frame.write_parquet(buffer)
    return buffer.getvalue()


def mapped(raw: bytes | None = None, released: date = RELEASED) -> pl.DataFrame:
    return osap_portfolios.map_returns(raw or wide(), docs(), release="2024.01", released=released)


class FakeTransport:
    """Serves the release's two files; the data file sits behind a redirect to a signed host."""

    def __init__(self, parquet: bytes, csv: bytes | None = None, hop: str | None = None) -> None:
        self.parquet, self.csv = parquet, csv if csv is not None else FIX.read_bytes()
        self.hop = hop or "https://us.aws.cdn.hf.co/xet/abc?sig=1"
        self.urls: list[str] = []
        self.headers: list[Mapping[str, str]] = []
        self.timeouts: list[float] = []

    def __call__(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        self.urls.append(url)
        self.headers.append(headers)
        self.timeouts.append(timeout)
        if url.endswith("SignalDoc.csv"):
            return 200, {}, self.csv
        if "PredictorLSretWide" in url:
            return 302, {"Location": self.hop}, b""
        if url == self.hop:
            return 200, {}, self.parquet
        return 404, {}, b""


@pytest.fixture(autouse=True)
def no_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(free_http, "PAUSE_SECONDS", 0.0)


def pull(
    home: Path,
    transport: FakeTransport,
    release: str = "2024.01",
    released: date = RELEASED,
    fetched_at: datetime = NOW,
) -> dict[str, object]:
    return osap_portfolios.pull_portfolios(
        data_dir=home,
        release=release,
        released=released,
        fetched_at=fetched_at,
        client=free_http.Client(transport=transport),
    )


def test_catalogue_parses_the_real_header_and_keeps_only_facts() -> None:
    found = docs()
    assert [d.acronym for d in found] == [
        "SynthAccrual",
        "SynthMom",
        "SynthOption",
        "SynthPlacebo",
        "SynthDropped",
    ]
    first = found[0]
    assert (first.short_name, first.year, first.sign, first.sample_start) == (
        "SynAcc",
        1999,
        -1,
        1970,
    )
    assert first.data_category == "Accounting" and first.category == "accruals"
    assert found[2].journal is None
    assert not hasattr(first, "definition")


def test_catalogue_fails_loud_on_a_changed_header_or_duplicate_signal() -> None:
    text = FIX.read_text().replace("Acronym,Cat.Signal", "Name,Cat.Signal", 1)
    with pytest.raises(DataError, match="Acronym"):
        osap_catalogue.parse_signal_doc(text.encode())
    lines = FIX.read_text().splitlines()
    with pytest.raises(DataError, match="duplicate"):
        osap_catalogue.parse_signal_doc("\n".join([*lines, lines[1]]).encode())
    bad_year = FIX.read_text().replace(",1999,", ",19x9,", 1)
    with pytest.raises(DataError, match="Year"):
        osap_catalogue.parse_signal_doc(bad_year.encode())


def test_percent_is_converted_to_decimal_exactly_once() -> None:
    assert osap_portfolios.percent_to_decimal(5.0) == 0.05
    df = mapped()
    row = df.filter((pl.col("signal") == "SynthAccrual") & (pl.col("month") == MONTHS[0]))
    assert row["long_short_return"].item() == pytest.approx(0.05)
    again = mapped(wide(scale=2.0))
    doubled = again.filter((pl.col("signal") == "SynthAccrual") & (pl.col("month") == MONTHS[0]))
    assert doubled["long_short_return"].item() == pytest.approx(0.10)
    assert "decimal" in osap_portfolios.UNIT_NOTE and "percent" in osap_portfolios.UNIT_NOTE


def test_rows_carry_signal_month_return_published_year_release_and_known_from() -> None:
    df = mapped()
    assert df.height == 7  # nulls are months a signal has no return, not rows
    assert set(df["signal"].unique()) == {"SynthAccrual", "SynthMom", "SynthOption"}
    assert set(df["release"]) == {"2024.01"}
    years = dict(zip(df["signal"], df["published_year"], strict=True))
    assert years == {"SynthAccrual": 1999, "SynthMom": 2005, "SynthOption": 2010}
    assert df.schema == osap_portfolios.SCHEMA


def test_last_trading_day_stamps_become_calendar_month_ends() -> None:
    assert osap_portfolios.month_end(date(2023, 12, 29)) == date(2023, 12, 31)
    assert osap_portfolios.month_end(date(2024, 2, 28)) == date(2024, 2, 29)
    stamped = [date(2023, 9, 29), date(2023, 10, 31), date(2023, 12, 29)]
    df = mapped(wide(months=stamped))
    assert sorted(df["month"].unique()) == [
        date(2023, 9, 30),
        date(2023, 10, 31),
        date(2023, 12, 31),
    ]
    two_in_one = [date(2023, 12, 28), date(2023, 12, 29), date(2024, 1, 31)]
    with pytest.raises(DataError, match="duplicate"):
        mapped(wide(months=two_in_one))


def test_known_from_is_the_later_of_month_lag_and_release() -> None:
    old_month, basis = osap_portfolios.known_from(date(2023, 10, 31), date(2024, 1, 15))
    assert old_month == datetime(2024, 1, 16, tzinfo=UTC) and basis == "release"
    late_month, basis = osap_portfolios.known_from(date(2024, 3, 31), date(2024, 1, 15))
    assert late_month == datetime(2024, 4, 1, 12, tzinfo=UTC) and basis == "month-lag"
    df = mapped()
    assert set(df["known_from"]) == {datetime(2024, 1, 16, tzinfo=UTC)}
    earliest = df["known_from"].min()
    assert isinstance(earliest, datetime)
    assert earliest > datetime.combine(MONTHS[-1], datetime.min.time(), UTC)


def test_early_read_returns_nothing_and_known_rows_appear_at_the_release(tmp_path: Path) -> None:
    pull(tmp_path, FakeTransport(wide()))
    before = datetime(2024, 1, 15, 23, 59, tzinfo=UTC)
    used, early = osap_portfolios.read_known(tmp_path, as_of=before)
    assert used is None and early.is_empty()
    used, later = osap_portfolios.read_known(tmp_path, as_of=datetime(2024, 1, 16, tzinfo=UTC))
    assert used == "2024.01" and later.height == 7


def leaky_read(path: Path, as_of: datetime) -> pl.DataFrame:
    """The mistake the clock prevents: filtering on the month instead of on known_from."""
    stored = load_events(path, source=osap_portfolios.SOURCE, schema=osap_portfolios.SCHEMA)
    return stored.filter(pl.col("month") <= as_of.date())


def leaks(rows: pl.DataFrame, as_of: datetime) -> bool:
    return bool(rows.filter(pl.col("known_from") > as_of).height)


def test_a_deliberately_leaky_read_is_caught_by_the_check(tmp_path: Path) -> None:
    pull(tmp_path, FakeTransport(wide()))
    as_of = datetime(2023, 12, 31, 12, tzinfo=UTC)
    path = osap_portfolios.table_path(tmp_path, "2024.01")
    assert leaks(leaky_read(path, as_of), as_of)  # the control fails the check, as it must
    _, proper = osap_portfolios.read_known(tmp_path, as_of=as_of)
    assert not leaks(proper, as_of) and proper.is_empty()


def test_a_second_release_is_a_new_vintage_and_the_first_is_untouched(tmp_path: Path) -> None:
    pull(tmp_path, FakeTransport(wide()))
    first = osap_portfolios.table_path(tmp_path, "2024.01")
    before = first.read_bytes()
    revised = wide(scale=1.5)
    pull(
        tmp_path,
        FakeTransport(revised),
        release="2025.01",
        released=date(2025, 1, 20),
        fetched_at=datetime(2025, 2, 1, tzinfo=UTC),
    )
    assert first.read_bytes() == before
    assert osap_portfolios.table_path(tmp_path, "2025.01").exists()
    old_used, old = osap_portfolios.read_known(tmp_path, as_of=datetime(2024, 6, 1, tzinfo=UTC))
    new_used, new = osap_portfolios.read_known(tmp_path, as_of=datetime(2025, 6, 1, tzinfo=UTC))
    assert (old_used, new_used) == ("2024.01", "2025.01")
    key = (pl.col("signal") == "SynthAccrual") & (pl.col("month") == MONTHS[0])
    assert old.filter(key)["long_short_return"].item() == pytest.approx(0.05)
    assert new.filter(key)["long_short_return"].item() == pytest.approx(0.075)
    pinned_used, pinned = osap_portfolios.read_known(
        tmp_path, as_of=datetime(2025, 6, 1, tzinfo=UTC), release="2024.01"
    )
    assert pinned_used == "2024.01" and pinned.equals(old)


def test_pulling_the_same_release_again_is_a_no_op_but_a_changed_one_is_refused(
    tmp_path: Path,
) -> None:
    pull(tmp_path, FakeTransport(wide()))
    path = osap_portfolios.table_path(tmp_path, "2024.01")
    before = path.read_bytes()
    pull(tmp_path, FakeTransport(wide()), fetched_at=datetime(2024, 3, 1, tzinfo=UTC))
    assert path.read_bytes() == before
    with pytest.raises(DataError, match="new release"):
        pull(tmp_path, FakeTransport(wide(scale=3.0)))
    assert path.read_bytes() == before


def test_pull_summary_counts_signals_and_months_and_states_unit_and_rule(tmp_path: Path) -> None:
    report = pull(tmp_path, FakeTransport(wide()))
    assert report["release"] == "2024.01" and report["released"] == "2024-01-15"
    assert (report["signals"], report["months"], report["rows"]) == (3, 3, 7)
    assert (report["first_month"], report["last_month"]) == ("2023-10-31", "2023-12-31")
    assert report["unit"] == osap_portfolios.UNIT_NOTE
    assert report["known_from_rule"] == osap_portfolios.KNOWN_RULE
    meta = json.loads(
        osap_portfolios.table_path(tmp_path, "2024.01").with_suffix(".json").read_text()
    )
    assert meta["release"] == "2024.01" and meta["released"] == "2024-01-15"
    assert meta["license"].startswith("CC BY 4.0")
    listed = osap_portfolios.describe(tmp_path)
    assert listed[0]["key"] == "2024.01" and listed[0]["signals"] == 3 and listed[0]["months"] == 3


def test_the_network_is_polite_and_redirects_stay_on_the_release_hosts(tmp_path: Path) -> None:
    transport = FakeTransport(wide())
    pull(tmp_path, transport)
    assert all(h["User-Agent"] == "Project-ALPHA/1.0" for h in transport.headers)
    assert set(transport.timeouts) == {30}
    assert transport.urls[0].startswith(
        "https://huggingface.co/datasets/OpenSourceAP/CrossSection/resolve/"
    )
    assert "Data-Release-2024.01" in transport.urls[0]
    evil = FakeTransport(wide(), hop="https://example.org/steal")
    with pytest.raises(DataError, match="redirect"):
        pull(tmp_path / "x", evil)
    assert not (tmp_path / "x").exists()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (wide(extra={"SynthMom": [1.0, float("inf"), 3.0]}), "finite"),
        (wide(extra={"SynthMom": [1.0, float("nan"), 3.0]}), "finite"),
        (wide(months=[MONTHS[0], MONTHS[0], MONTHS[2]]), "duplicate"),
        (wide(months=[MONTHS[1], MONTHS[0], MONTHS[2]]), "disordered"),
        (wide(months=[date(2023, 10, 15), MONTHS[1], MONTHS[2]]), "month end"),
        (wide(extra={"Mystery": [1.0, 2.0, 3.0]}), "unknown column"),
    ],
)
def test_invalid_data_fails_loud_and_stores_nothing(
    tmp_path: Path, raw: bytes, message: str
) -> None:
    with pytest.raises(DataError, match=message):
        pull(tmp_path, FakeTransport(raw))
    assert not list(tmp_path.rglob("*.parquet"))


def test_a_stored_table_that_was_edited_fails_its_hash_check(tmp_path: Path) -> None:
    pull(tmp_path, FakeTransport(wide()))
    path = osap_portfolios.table_path(tmp_path, "2024.01")
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(DataError, match="sha256"):
        osap_portfolios.read_known(tmp_path, as_of=datetime(2030, 1, 1, tzinfo=UTC))


def test_release_and_release_date_are_checked(tmp_path: Path) -> None:
    for bad in ("2024", "24.01", "../x", "2024.1"):
        with pytest.raises(DataError, match="release"):
            osap_portfolios.table_path(tmp_path, bad)
    with pytest.raises(DataError, match="released"):
        pull(tmp_path, FakeTransport(wide()), released=date(2024, 3, 1))
