"""Published factors on legacy provenance: the asset kind is read from the stored bars' calendar."""

from pathlib import Path

import pytest

from alpha_cli.toolbox.families.context import PUBLISHED_FACTORS
from alpha_cli.toolbox.runner import run
from alpha_data.adapters.base import DatasetIdentity
from tests.unit.published_factors_support import (
    US_STOCK,
    factor_returns,
    month_ends,
    write_factor_file,
    write_run,
)
from tests.unit.test_spine_tools import RUN

TOOL = "context.published_factors"
LABEL = "asset-kind-inferred-from-calendar"
SENTENCE = (
    "This data set does not record what kind of asset it is. It was traded on a US stock "
    "exchange calendar, so it is treated as a US-listed stock or fund."
)
FUND = "for a bond or commodity fund these stock factors mean little"


def _home(
    home: Path, *, calendar: str, source: str, identity: DatasetIdentity | None = None
) -> None:
    series = factor_returns()
    write_factor_file(home, series)
    monthly = {m: 0.5 * series["Mom12m"][m] for m in month_ends()}
    write_run(home, monthly, identity=identity, calendar=calendar, source=source)


@pytest.mark.parametrize("source", ["yfinance", "stooq"])
def test_legacy_data_on_a_us_calendar_is_read_and_labelled(tmp_path: Path, source: str) -> None:
    _home(tmp_path, calendar="sessions", source=source)
    doc = run(tmp_path, TOOL, RUN)
    assert doc["result"]["branch"] == "read"
    assert doc["result"]["asset_kind_basis"] == "calendar"
    assert LABEL in doc["labels"]
    assert SENTENCE in doc["reading"]
    assert FUND in doc["reading"]
    assert isinstance(doc["values"]["explained_share"], float)


def test_a_24_7_market_on_an_equity_source_cannot_be_told(tmp_path: Path) -> None:
    _home(tmp_path, calendar="everyday", source="yfinance")
    doc = run(tmp_path, TOOL, RUN)
    assert doc["result"]["branch"] == "unknown-asset"
    assert LABEL not in doc["labels"]
    assert doc["values"]["explained_share"] is None


def test_a_crypto_source_is_not_applicable_even_on_session_days(tmp_path: Path) -> None:
    _home(tmp_path, calendar="sessions", source="ccxt:binance")
    doc = run(tmp_path, TOOL, RUN)
    assert doc["result"]["branch"] == "not-applicable"
    assert LABEL not in doc["labels"]


def test_an_unknown_source_cannot_be_told(tmp_path: Path) -> None:
    _home(tmp_path, calendar="sessions", source="somewhere")
    assert run(tmp_path, TOOL, RUN)["result"]["branch"] == "unknown-asset"


def test_a_stored_identity_is_decided_by_the_identity_alone(tmp_path: Path) -> None:
    _home(tmp_path, calendar="everyday", source="alpaca", identity=US_STOCK)
    doc = run(tmp_path, TOOL, RUN)
    assert doc["result"]["branch"] == "read"
    assert LABEL not in doc["labels"]
    assert SENTENCE not in doc["reading"]
    assert "asset_kind_basis" not in doc["result"]


def test_the_tool_version_is_bumped_so_an_old_cannot_tell_is_not_served() -> None:
    assert PUBLISHED_FACTORS.version == 2
