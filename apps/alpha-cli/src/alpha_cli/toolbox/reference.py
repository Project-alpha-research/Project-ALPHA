"""Descriptive reads of reference series that became public after a test's own period.

The one rule (owner decision, 2026-11-20): a check that only DESCRIBES a past result, and is
never an input to a strategy, may read reference series for the test's own period although those
series were published later. Strategy inputs keep the strict known-at rule. A test
(``tests/unit/test_reference_read_structural_guard.py``) keeps this module away from strategy,
engine, spine-run, Setup Lab, hypothesis-scan and RD-Agent code.

``read_reference_for_period`` has three limits: it names the newest stored vintage; it never
returns a month whose end is at or after the held-back boundary; it never returns a month after
the month of the run's own last data day.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox.reserve import RESERVED_DAY
from alpha_data.context import osap_portfolios

if TYPE_CHECKING:
    import polars as pl

LABEL = "reference-series-known-later"
SENTENCE = (
    "The reference factors were published as a data set after this test's period. "
    "This is a description of the result made later, not something the strategy could have used."
)
PULL = "uv run alpha context pull-osap-portfolios --release <RELEASE> --released <DATE>"
# Later than any release: the descriptive read takes every stored row, then cuts it by month.
EVERYTHING = datetime(9999, 12, 31, tzinfo=UTC)


@dataclass(frozen=True)
class ReferenceRead:
    vintage: str
    rows: pl.DataFrame


def _missing() -> SpineError:
    return SpineError(
        "NO_FACTOR_FILE",
        f"No published-factor file is stored. Pull one first: {PULL}",
        f"Run {PULL}",
    )


def vintage_fingerprint(data_dir: Path) -> dict[str, str]:
    """Name and file hash of the newest stored vintage, for the cache key."""
    names = sorted(
        (p.stem for p in (data_dir / osap_portfolios.FOLDER).glob("*.parquet")), reverse=True
    )
    if not names:
        raise _missing()
    raw = osap_portfolios.table_path(data_dir, names[0]).read_bytes()
    return {"reference_vintage": names[0], "reference_sha256": hashlib.sha256(raw).hexdigest()}


def read_reference_for_period(data_dir: Path, *, first_day: date, last_day: date) -> ReferenceRead:
    """Factor rows for the months of ``first_day`` to ``last_day``; descriptive use only."""
    import polars as pl

    name, rows = osap_portfolios.read_known(data_dir, as_of=EVERYTHING)
    if name is None:
        raise _missing()
    first, last = osap_portfolios.month_end(first_day), osap_portfolios.month_end(last_day)
    kept = rows.filter(
        (pl.col("month") >= first) & (pl.col("month") <= last) & (pl.col("month") < RESERVED_DAY)
    )
    return ReferenceRead(
        name, kept.select("signal", "month", "long_short_return", "published_year")
    )
