"""A filing is invisible before acceptance plus the clock margin; amendments never replace it."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from alpha_data.context.edgar import CLOCK_MARGIN, earnings, map_submission_arrays
from alpha_data.context.events import as_known_events

pytestmark = pytest.mark.bias_guard

ACCEPTED = "2024-01-25T16:05:12.000Z"


def _filings() -> pl.DataFrame:
    arrays = {
        "accessionNumber": ["0000000001-24-000001", "0000000001-24-000009"],
        "filingDate": ["2024-01-25", "2024-02-20"],
        "reportDate": ["2024-01-24", ""],
        "acceptanceDateTime": [ACCEPTED, "2024-02-20T21:00:00.000Z"],
        "form": ["8-K", "8-K/A"],
        "items": ["2.02,9.01", "2.02"],
        "primaryDocument": ["a.htm", "b.htm"],
    }
    return pl.DataFrame(map_submission_arrays(arrays))


def test_filing_not_visible_before_it_was_public() -> None:
    accepted = datetime(2024, 1, 25, 16, 5, 12, tzinfo=UTC)
    df = _filings()
    assert as_known_events(df, as_of=accepted).is_empty()  # margin: not yet known at acceptance
    assert as_known_events(df, as_of=accepted + CLOCK_MARGIN).height == 1


def test_amendment_is_a_later_row_not_a_replacement() -> None:
    df = _filings()
    early = earnings(as_known_events(df, as_of=datetime(2024, 2, 1, tzinfo=UTC)))
    late = earnings(as_known_events(df, as_of=datetime(2024, 3, 1, tzinfo=UTC)))
    assert early["form"].to_list() == ["8-K"]
    assert late["form"].to_list() == ["8-K", "8-K/A"]


def test_future_rows_never_change_an_earlier_read() -> None:
    df = _filings()
    cutoff = datetime(2024, 2, 1, tzinfo=UTC)
    poisoned = df.with_columns(
        pl.when(pl.col("known_from") > cutoff)
        .then(pl.lit("POISON"))
        .otherwise(pl.col("items"))
        .alias("items")
    )
    assert as_known_events(df, as_of=cutoff).equals(as_known_events(poisoned, as_of=cutoff))
    # Leaky control: the same poison must show up once the cutoff passes it.
    later = datetime(2024, 3, 1, tzinfo=UTC)
    assert not as_known_events(df, as_of=later).equals(as_known_events(poisoned, as_of=later))
