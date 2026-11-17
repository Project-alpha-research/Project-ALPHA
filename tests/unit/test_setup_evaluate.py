"""Candidate decisions on known daily paths."""

from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest

from alpha_core import DataError
from alpha_study.setup import SetupSpec, find_candidates, summarise
from tests.unit.test_setup_spec import EXAMPLE, minimal


def bars(values: list[int] | list[float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": [
                datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(len(values))
            ],
            "open": [float(v) for v in values],
            "close": [float(v) for v in values],
            "high": [float(v + 1) for v in values],
            "low": [float(v - 1) for v in values],
            "volume": [100.0] * len(values),
        }
    )


def worked_bars() -> pl.DataFrame:
    return bars(list(range(100, 165)) + [140, 140, 140, 170, 172, 173])


def test_worked_example() -> None:
    import tomllib

    result = find_candidates(
        SetupSpec.load(tomllib.loads(EXAMPLE)), worked_bars(), symbol="BTC/USDT"
    )
    assert result.height == 1
    row = result.row(0, named=True)
    assert row["candidate_id"] == 1
    assert row["status"] == "accepted" and row["reason"] is None
    assert row["event_ts"] == worked_bars()["ts"][68]
    assert row["trigger_ts"] == row["event_ts"]
    assert row["entry_ts"] == worked_bars()["ts"][69]
    assert row["entry_price"] == pytest.approx(172)
    assert row["ref_avg20"] == pytest.approx(sum(worked_bars()["close"][49:69]) / 20)


def test_filter_order_and_summary() -> None:
    data = minimal(filters={"first": "close < 0", "second": "close > 99"})
    result = find_candidates(SetupSpec.load(data), bars([1, 2, 3]), symbol="BTC/USDT")
    assert result["reason"].to_list() == ["first"] * 3
    assert result["detail"].to_list() == ["first: false"] * 3
    data["filters"] = dict(reversed(list(data["filters"].items())))
    assert (
        find_candidates(SetupSpec.load(data), bars([1]), symbol="BTC/USDT")["reason"][0] == "second"
    )
    assert summarise(result) == {
        "accepted": 0,
        "pending": 0,
        "rejected": {"first": 3},
        "first_event": bars([1])["ts"][0],
        "last_event": bars([1, 2, 3])["ts"][2],
    }


@pytest.mark.parametrize("offset, reason", [(0, None), (3, None), (4, "no-trigger")])
def test_trigger_inclusive_edges(offset: int, reason: str | None) -> None:
    data = minimal(trigger={"when": "close == 9", "within": 3})
    data["setup"]["event"] = "volume == 101"
    values = [2] * 6
    values[offset] = 9
    frame = bars(values).with_columns(pl.Series("volume", [101, 100, 100, 100, 100, 100]))
    row = find_candidates(SetupSpec.load(data), frame, symbol="BTC/USDT").row(0, named=True)
    assert row["reason"] == reason
    if reason is None:
        assert row["trigger_ts"] == frame["ts"][offset]
        assert row["entry_ts"] == frame["ts"][offset + 1]


def test_next_bar_warmup_nulls_and_empty_schema() -> None:
    data = minimal(reference={"level": "sma(close, 3)"})
    result = find_candidates(SetupSpec.load(data), bars([1, 2, 3, 4]), symbol="BTC/USDT")
    assert result["reason"].to_list() == [None, "no-next-bar"]
    assert result["entry_price"].to_list() == pytest.approx([4, None])
    empty = find_candidates(SetupSpec.load(data), bars([1]), symbol="BTC/USDT")
    assert empty.schema == result.schema
    assert summarise(empty) == {
        "accepted": 0,
        "pending": 0,
        "rejected": {},
        "first_event": None,
        "last_event": None,
    }
    for extra in [
        {"filters": {"f": "close / 0 > 1"}},
        {"reference": {"r": "close / 0"}},
    ]:
        rejected = find_candidates(
            SetupSpec.load(minimal(**extra)), bars([1, 2]), symbol="BTC/USDT"
        )
        assert rejected["reason"].to_list() == ["warm-up"] * 2
    # A null trigger value is false, not warm-up: the window is searched to its end.
    never = minimal(trigger={"when": "close / 0 > 1", "within": 1})
    searched = find_candidates(SetupSpec.load(never), bars([1, 2]), symbol="BTC/USDT")
    assert searched["reason"].to_list() == ["no-trigger", "pending-trigger"]
    data = minimal()
    data["setup"]["event"] = "close / 0 > 1"
    assert find_candidates(SetupSpec.load(data), bars([1, 2]), symbol="BTC/USDT").is_empty()


@pytest.mark.parametrize("kind", ["missing", "unsorted", "duplicate", "null", "nan", "inf", "ts"])
def test_invalid_bars(kind: str) -> None:
    frame = bars([1, 2, 3])
    if kind == "missing":
        frame = frame.drop("open")
    elif kind == "unsorted":
        frame = frame.reverse()
    elif kind == "duplicate":
        frame = pl.concat([frame, frame.tail(1)])
    elif kind in {"null", "nan", "inf"}:
        frame = frame.with_columns(
            pl.lit({"null": None, "nan": float("nan"), "inf": float("inf")}[kind]).alias("close")
        )
    else:
        frame = frame.with_columns(pl.col("ts").cast(pl.String))
    with pytest.raises(DataError):
        find_candidates(SetupSpec.load(minimal()), frame, symbol="BTC/USDT")


def test_trigger_first_match_and_future_null_counts_false() -> None:
    data = minimal(trigger={"when": "volume > 100", "within": 3})
    data["setup"]["event"] = "close == 1"
    source = bars([1, 2, 3, 4, 5]).with_columns(pl.Series("volume", [100, None, 101, 102, 100]))
    row = find_candidates(SetupSpec.load(data), source, symbol="BTC/USDT").row(0, named=True)
    assert row["trigger_ts"] == source["ts"][2]
    assert row["entry_ts"] == source["ts"][3]
    assert row["entry_price"] == pytest.approx(4)


@pytest.mark.parametrize(
    "extra",
    [
        {"filters": {"ready": "sma(close, 3) > 0"}},
        {"trigger": {"when": "sma(close, 3) > 0", "within": 0}},
    ],
)
def test_largest_warmup_includes_filter_and_trigger(extra: dict[str, Any]) -> None:
    source = bars([1, 2, 3, 4])
    result = find_candidates(SetupSpec.load(minimal(**extra)), source, symbol="BTC/USDT")
    assert result["event_ts"].to_list() == source["ts"].to_list()[2:]
    assert result["reason"].to_list() == [None, "no-next-bar"]


def test_aware_utc_and_asset_membership() -> None:
    spec = SetupSpec.load(minimal())
    with pytest.raises(DataError, match="UTC"):
        find_candidates(
            spec, bars([1]).with_columns(pl.col("ts").dt.replace_time_zone(None)), symbol="BTC/USDT"
        )
    with pytest.raises(DataError, match="assets"):
        find_candidates(spec, bars([1]), symbol="SPY")


def test_empty_typed_bars_and_acceptance_summary() -> None:
    spec = SetupSpec.load(minimal())
    source = bars([1, 2, 3])
    result = find_candidates(spec, source, symbol="BTC/USDT")
    assert summarise(result)["accepted"] == 2
    assert summarise(result)["rejected"] == {"no-next-bar": 1}
    empty = find_candidates(spec, source.head(0), symbol="BTC/USDT")
    assert empty.schema == result.schema
    assert empty.is_empty()


@pytest.mark.parametrize(
    "length, status, reason",
    [
        (2, "pending", "pending-trigger"),  # window bars 0..3, only 0..1 supplied
        (3, "pending", "pending-trigger"),
        (4, "rejected", "no-trigger"),  # the whole window has been seen
        (6, "rejected", "no-trigger"),
    ],
)
def test_unfinished_trigger_window_is_pending_not_rejected(
    length: int, status: str, reason: str
) -> None:
    data = minimal(trigger={"when": "close == 9", "within": 3})
    data["setup"]["event"] = "volume == 101"
    frame = bars([2] * length).with_columns(pl.Series("volume", [101] + [100] * (length - 1)))
    result = find_candidates(SetupSpec.load(data), frame, symbol="BTC/USDT")
    row = result.row(0, named=True)
    assert (row["status"], row["reason"]) == (status, reason)
    assert row["trigger_ts"] is None and row["entry_ts"] is None and row["entry_price"] is None
    summary = summarise(result)
    assert summary["pending"] == (1 if status == "pending" else 0)
    assert summary["rejected"] == ({} if status == "pending" else {"no-trigger": 1})


def test_pending_candidate_resolves_when_later_bars_arrive() -> None:
    data = minimal(trigger={"when": "close == 9", "within": 3})
    data["setup"]["event"] = "volume == 101"
    frame = bars([2, 2, 9, 5]).with_columns(pl.Series("volume", [101, 100, 100, 100]))
    spec = SetupSpec.load(data)
    assert find_candidates(spec, frame.head(2), symbol="BTC/USDT")["reason"][0] == "pending-trigger"
    assert find_candidates(spec, frame.head(3), symbol="BTC/USDT")["reason"][0] == "no-next-bar"
    done = find_candidates(spec, frame, symbol="BTC/USDT").row(0, named=True)
    assert done["status"] == "accepted" and done["entry_price"] == pytest.approx(5)


def test_missing_volume_mid_series_is_not_relabelled_warm_up() -> None:
    # Review finding: a null filter operand after warm-up is a false condition.
    data = minimal(filters={"active": "within_bars(volume > 50, 5)"})
    frame = bars(list(range(1, 13))).with_columns(
        pl.Series("volume", [60.0] * 6 + [None] + [60.0] * 5)
    )
    result = find_candidates(SetupSpec.load(data), frame, symbol="BTC/USDT")
    assert "warm-up" not in result["reason"].to_list()


def test_null_trigger_on_event_bar_keeps_searching_the_window() -> None:
    # Review finding: a missing value on the event bar is not a warm-up rejection.
    data = minimal(trigger={"when": "volume > 50", "within": 3})
    data["setup"]["event"] = "close == 7"
    frame = bars(list(range(1, 13))).with_columns(
        pl.Series("volume", [10.0] * 6 + [None] + [60.0] * 5)
    )
    row = find_candidates(SetupSpec.load(data), frame, symbol="BTC/USDT").row(0, named=True)
    assert row["status"] == "accepted" and row["trigger_ts"] == frame["ts"][7]
