"""A chart pattern is reported on the day it became known, never on the day of its extreme.

The setup language has no pivot primitive: a swing low is written as "the low k bars ago is
the lowest of the last 2k+1 bars", which can only be true k bars after the low. These tests
pin that a double bottom written this way is reported no earlier than its second low plus k
bars, and that changing any bar after a cut leaves every decision up to the cut unchanged.
"""

import random
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from alpha_study.setup import SetupSpec, find_candidates

CONFIRM = 3  # bars on each side of a swing low
LOW = f"prev(low, {CONFIRM})"
DOUBLE_BOTTOM = {
    "setup": {
        "name": "double-bottom",
        "idea": "A second swing low within 2% of the lowest low 10 to 49 bars earlier",
        "assets": ["SPY"],
        "timeframe": "1D",
        "event": (
            f"{LOW} == lowest(low, {2 * CONFIRM + 1})"
            f" and {LOW} <= lowest(prev(low, 10), 40) * 1.02"
            f" and {LOW} >= lowest(prev(low, 10), 40) * 0.98"
        ),
    },
    "filters": {"bounce": f"highest(high, 20) >= {LOW} * 1.1"},
    "reference": {"second_low": LOW, "first_low": "lowest(prev(low, 10), 40)"},
}
# Columns fixed by bars up to the event bar itself; the rest need the next bar.
DECIDED_AT_EVENT = ["candidate_id", "event_ts", "ref_second_low", "ref_first_low"]


def frame(closes: list[float]) -> pl.DataFrame:
    stamps = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(len(closes))]
    return pl.DataFrame(
        {
            "ts": stamps,
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [100.0] * len(closes),
        }
    )


def textbook() -> pl.DataFrame:
    """First low on day 50 (low 79), rally to day 58, second low on day 66 (low 79.5)."""
    closes = [130.0 - i for i in range(30)]  # days 0-29
    closes += [100.0 - i for i in range(21)]  # days 30-50, close 80 on day 50
    closes += [80.0 + 2 * i for i in range(1, 9)]  # days 51-58, up to 96
    closes += [96.0 - 2 * i for i in range(1, 8)]  # days 59-65, down to 82
    closes += [80.5]  # day 66: the second low
    closes += [80.5 + 2 * i for i in range(1, 20)]  # days 67-85
    return frame(closes)


SECOND_LOW = 66


def walk(n: int, seed: int) -> pl.DataFrame:
    rng = random.Random(seed)
    closes, close = [], 100.0
    for _ in range(n):
        close *= 1 + rng.uniform(-0.03, 0.03)
        closes.append(close)
    return frame(closes)


def spec() -> SetupSpec:
    return SetupSpec.load(DOUBLE_BOTTOM)


def test_textbook_double_bottom_is_known_three_bars_after_the_second_low() -> None:
    bars = textbook()
    result = find_candidates(spec(), bars, symbol="SPY")
    assert result.height == 1
    row = result.row(0, named=True)
    assert row["event_ts"] == bars["ts"][SECOND_LOW + CONFIRM]
    assert row["status"] == "accepted"
    assert row["entry_ts"] == bars["ts"][SECOND_LOW + CONFIRM + 1]
    assert row["ref_second_low"] == pytest.approx(79.5)
    assert row["ref_first_low"] == pytest.approx(79.0)


@pytest.mark.parametrize("last", range(SECOND_LOW, SECOND_LOW + CONFIRM))
def test_double_bottom_is_not_reported_before_it_is_confirmed(last: int) -> None:
    # Bars end on the second low or within the confirmation bars: nothing is known yet.
    assert find_candidates(spec(), textbook().head(last + 1), symbol="SPY").height == 0


def test_double_bottom_on_the_last_bar_is_known_but_has_no_entry() -> None:
    bars = textbook().head(SECOND_LOW + CONFIRM + 1)
    row = find_candidates(spec(), bars, symbol="SPY").row(0, named=True)
    assert row["event_ts"] == bars["ts"][-1]
    assert (row["status"], row["reason"], row["entry_ts"]) == ("rejected", "no-next-bar", None)


def poisoned(bars: pl.DataFrame, cut: int, seed: int) -> list[pl.DataFrame]:
    """Bars after `cut` truncated, replaced by a different random walk, or mirrored."""
    rng = random.Random(seed)
    after = bars.height - cut - 1
    other = walk(bars.height, seed + 1000)
    scale = bars["close"][cut] / other["close"][cut]
    replaced = pl.concat(
        [
            bars.head(cut + 1),
            other.slice(cut + 1).with_columns(
                pl.col(c) * scale for c in ("open", "high", "low", "close")
            ),
        ]
    )
    shuffled = list(range(cut + 1, bars.height))
    rng.shuffle(shuffled)
    mixed = pl.concat(
        [
            bars.head(cut + 1),
            bars[shuffled].with_columns(pl.Series("ts", bars["ts"].slice(cut + 1, after))),
        ]
    )
    return [bars.head(cut + 1), replaced, mixed]


@pytest.mark.parametrize("seed", [3, 11, 29])
def test_changing_bars_after_a_cut_changes_nothing_decided_by_the_cut(seed: int) -> None:
    bars = walk(600, seed)
    full = find_candidates(spec(), bars, symbol="SPY")
    assert full.height >= 3, "the walk should contain a few double bottoms"
    for cut in range(60, 590, 23):
        cut_ts = bars["ts"][cut]
        for variant in poisoned(bars, cut, seed):
            other = find_candidates(spec(), variant, symbol="SPY")
            # Everything about an event on or before the cut is fixed at the event bar...
            assert_frame_equal(
                full.filter(pl.col("event_ts") <= cut_ts).select(DECIDED_AT_EVENT),
                other.filter(pl.col("event_ts") <= cut_ts).select(DECIDED_AT_EVENT),
            )
            # ...and an event strictly before the cut also has its next-open entry fixed.
            assert_frame_equal(
                full.filter(pl.col("event_ts") < cut_ts),
                other.filter(pl.col("event_ts") < cut_ts),
            )
