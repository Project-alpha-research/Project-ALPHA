"""Redirect allow-list tricks, release-date floor, vintage selection and missing years."""

from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from alpha_core import DataError
from alpha_data.context import free_http, osap_catalogue, osap_portfolios
from tests.unit.test_context_osap_portfolios import FIX, FakeTransport, mapped, pull, wide

HOSTS = osap_portfolios.HOSTS
START = "https://huggingface.co/datasets/x/resolve/b/f"


class Hop:
    """First request redirects to `target`; any later request is recorded and served."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(
        self, url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        self.calls.append((url, dict(headers)))
        if len(self.calls) == 1:
            return 302, {"Location": self.target}, b""
        return 200, {}, b"ok"


@pytest.fixture(autouse=True)
def no_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(free_http, "PAUSE_SECONDS", 0.0)


@pytest.mark.parametrize(
    "target",
    [
        "https://evilhf.co/x",
        "https://hf.co.evil.com/x",
        "https://hf.co@evil.com/x",
        "https://huggingface.co@evil.com/x",
        "https://user:pw@huggingface.co/x",
        "https://huggingface.co:8443/x",
        "https://cdn.hf.co:444/x",
        "https://127.0.0.1/x",
        "https://[::1]/x",
        "https://169.254.169.254/x",
        "http://cdn.hf.co/x",
        "https://huggingface.co.evil.com/x",
        "https://nothf.co/x",
        "https://hf.co/x",
        "//evil.com/x",
        "https://cdn.hf.co:bad/x",
    ],
)
def test_redirect_tricks_are_refused_before_any_request(target: str) -> None:
    hop = Hop(target)
    with pytest.raises(DataError, match="redirect"):
        free_http.Client(transport=hop).get_following(START, "t", HOSTS)
    assert len(hop.calls) == 1


def test_a_listed_host_is_followed_with_only_the_user_agent() -> None:
    hop = Hop("https://us.aws.cdn.hf.co:443/xet/a?sig=1")
    status, body = free_http.Client(transport=hop).get_following(START, "t", HOSTS)
    assert (status, body) == (200, b"ok") and len(hop.calls) == 2
    assert all(h == {"User-Agent": "Project-ALPHA/1.0"} for _, h in hop.calls)


def test_every_hop_is_revalidated_and_the_chain_is_capped() -> None:
    seen: list[str] = []

    def chain(
        url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        seen.append(url)
        nxt = "https://evil.com/x" if len(seen) == 2 else "https://a.hf.co/next"
        return 302, {"location": nxt}, b""

    with pytest.raises(DataError, match="unlisted"):
        free_http.Client(transport=chain).get_following(START, "t", HOSTS)
    assert len(seen) == 2
    seen.clear()

    def loop(
        url: str, headers: Mapping[str, str], timeout: float
    ) -> tuple[int, Mapping[str, str], bytes]:
        seen.append(url)
        return 302, {"Location": "https://a.hf.co/again"}, b""

    with pytest.raises(DataError, match="more than 3"):
        free_http.Client(transport=loop).get_following(START, "t", HOSTS)
    assert len(seen) == 4


def test_the_start_url_must_be_listed_and_other_sources_keep_plain_get() -> None:
    hop = Hop("https://a.hf.co/x")
    with pytest.raises(DataError, match="unlisted"):
        free_http.Client(transport=hop).get_following("https://example.org/f", "t", HOSTS)
    assert not hop.calls
    assert free_http.Client(transport=hop).get(START, "t")[0] == 302  # `get` never follows


def test_the_followed_body_is_size_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(free_http, "MAX_BYTES", 1)
    with pytest.raises(DataError, match="exceeds"):
        free_http.Client(transport=Hop("https://a.hf.co/x")).get_following(START, "t", HOSTS)


def test_the_stored_file_records_the_hash_of_what_was_fetched(tmp_path: Path) -> None:
    pull(tmp_path, FakeTransport(wide()))
    meta = osap_portfolios.table_path(tmp_path, "2024.01").with_suffix(".json").read_text()
    assert "sha256" in meta and "operator" in meta


def test_the_release_date_may_not_be_before_the_newest_month_plus_one_day() -> None:
    newest = date(2023, 12, 31)
    with pytest.raises(DataError, match="earlier than the newest month"):
        mapped(released=newest)
    assert mapped(released=date(2024, 1, 1)).height == 7


def test_two_vintages_read_between_their_release_dates_gives_only_the_older(
    tmp_path: Path,
) -> None:
    pull(tmp_path, FakeTransport(wide()))
    pull(
        tmp_path,
        FakeTransport(wide(scale=2.0)),
        release="2025.01",
        released=date(2025, 1, 20),
        fetched_at=datetime(2025, 2, 1, tzinfo=UTC),
    )
    between = datetime(2024, 9, 1, tzinfo=UTC)
    used, rows = osap_portfolios.read_known(tmp_path, as_of=between)
    assert used == "2024.01" and set(rows["release"]) == {"2024.01"}
    for release in ("2024.01", "2025.01"):  # no old month of a vintage is known before its date
        early = osap_portfolios.read_known(
            tmp_path, as_of=datetime(2025, 1, 20, 23, tzinfo=UTC), release=release
        )[1]
        assert early.height == (7 if release == "2024.01" else 0)
    assert set(rows["known_from"]) == {datetime(2024, 1, 16, tzinfo=UTC)}


def test_a_percent_value_becomes_the_decimal_once() -> None:
    row = mapped().filter(
        (pl.col("signal") == "SynthAccrual") & (pl.col("month") == date(2023, 10, 31))
    )
    assert row["long_short_return"].item() == pytest.approx(0.05)


def test_a_missing_publication_year_stays_missing() -> None:
    text = FIX.read_text().replace("Doe,1999,", "Doe,,")
    docs = osap_catalogue.parse_signal_doc(text.encode())
    df = osap_portfolios.map_returns(wide(), docs, release="2024.01", released=date(2024, 1, 15))
    years = dict(df.group_by("signal").agg(pl.col("published_year").first()).iter_rows())
    assert years["SynthAccrual"] is None and years["SynthMom"] == 2005
