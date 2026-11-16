"""Prefix causality, including the one explicitly future-dependent entry bar."""

import random
import tomllib

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from alpha_study.setup import SetupSpec, compile_expr, find_candidates
from tests.unit.test_setup_evaluate import bars, worked_bars
from tests.unit.test_setup_spec import EXAMPLE, minimal

pytestmark = pytest.mark.bias_guard


def variants(frame, k):
    after = pl.col("ts") > frame["ts"][k]
    multiplied = frame.with_columns(
        [
            pl.when(after).then(pl.col(c) * 1000).otherwise(pl.col(c)).alias(c)
            for c in ("open", "high", "low", "close", "volume")
        ]
    )
    huge = frame.with_columns(
        [
            pl.when(after).then(value).otherwise(pl.col(c)).alias(c)
            for c, value in {
                "open": 1e12,
                "high": 2e12,
                "low": 1e11,
                "close": 1.5e12,
                "volume": 1e15,
            }.items()
        ]
    )
    return [frame, frame.head(k + 1), multiplied, huge]


def assert_prefix(expr, frame, k):
    results = [
        variant.with_columns(expr.alias("value")).select("value").head(k + 1)
        for variant in variants(frame, k)
    ]
    for result in results[1:]:
        assert_frame_equal(results[0], result, check_exact=True)


def generated_expressions():
    rng = random.Random(1401)

    def number(depth):
        if depth == 0:
            return rng.choice(["open", "high", "low", "close", "volume", "2"])
        x, n = number(depth - 1), rng.randint(1, 8)
        choice = rng.randrange(12)
        if choice < 7:
            fn = ["prev", "sma", "ema", "highest", "lowest", "pct_change", "abs"][choice]
            return f"{fn}({x})" if fn == "abs" else f"{fn}({x}, {n})"
        if choice == 7:
            return f"atr({n})"
        return f"({x} {rng.choice(['+', '-', '*', '/'])} {number(depth - 1)})"

    def boolean(depth):
        if depth == 0:
            return f"({number(1)} {rng.choice(['<', '<=', '>', '>=', '==', '!='])} {number(1)})"
        choice = rng.randrange(7)
        if choice < 3:
            fn = ["prev", "for_bars", "within_bars"][choice]
            return f"{fn}({boolean(depth - 1)}, {rng.randint(1, 5)})"
        if choice < 5:
            return f"{['crosses_above', 'crosses_below'][choice - 3]}({number(1)}, {number(1)})"
        if choice == 5:
            return f"not ({boolean(depth - 1)})"
        return f"({boolean(depth - 1)} {rng.choice(['and', 'or'])} {boolean(depth - 1)})"

    return [number(2) if i % 2 else boolean(2) for i in range(220)]


def test_generated_expression_prefixes():
    expressions = generated_expressions()
    assert len(set(expressions)) >= 200
    frame = bars([50 + ((i * 17) % 23) for i in range(80)])
    for text in expressions:
        for k in [11, 39, 63]:
            assert_prefix(compile_expr(text).expr, frame, k)


ENTRY = ["entry_ts", "entry_price"]
OUTCOME = ["status", "reason", "detail", "trigger_ts", *ENTRY]


def assert_candidates_causal(spec, source, k):
    """Compare every candidate whose event is at or before k across the future variants.

    What may legitimately differ, and nothing else:
    - trigger exactly at k: the entry is bar k+1's open, so the truncated frame must say
      `no-next-bar` with no entry, and a poisoned frame keeps `entry_ts` but not the price;
    - trigger window still open at k (trigger found after k, or the window ends after k):
      the truncated frame must say `pending-trigger`, never a definite rejection, and a
      poisoned frame may resolve it either way. Event, symbol and references still match.
    Returns how many rows were compared in full, at the k+1 edge, and as open windows.
    """
    stamps = source["ts"].to_list()
    index = {ts: i for i, ts in enumerate(stamps)}
    within = spec.trigger.within if spec.trigger is not None else 0
    full = find_candidates(spec, source, symbol="BTC/USDT")
    known = full.filter(pl.col("event_ts") <= stamps[k])
    counts = {"full": 0, "edge": 0, "open": 0}
    for number, variant in enumerate(variants(source, k)[1:]):
        truncated = number == 0
        actual = find_candidates(spec, variant, symbol="BTC/USDT")
        seen = actual.filter(pl.col("event_ts") <= stamps[k])
        # Same candidates, same numbering; the truncated frame holds nothing else.
        assert seen["candidate_id"].to_list() == known["candidate_id"].to_list()
        if truncated:
            assert actual.height == known.height
        for want, got in zip(known.iter_rows(named=True), seen.iter_rows(named=True), strict=True):
            event = index[want["event_ts"]]
            trigger = index[want["trigger_ts"]] if want["trigger_ts"] is not None else None
            stable = [name for name in want if name not in OUTCOME]
            assert [got[name] for name in stable] == [want[name] for name in stable]
            searched = spec.trigger is not None and want["reason"] in {
                None,
                "no-next-bar",
                "no-trigger",
                "pending-trigger",
            }
            if searched and (trigger is None or trigger > k) and event + within > k:
                if truncated:
                    assert (got["status"], got["reason"]) == ("pending", "pending-trigger")
                    assert [got[name] for name in ["trigger_ts", *ENTRY]] == [None] * 3
                counts["open"] += 1
            elif trigger == k:
                assert got["trigger_ts"] == want["trigger_ts"]
                if truncated:
                    assert (got["status"], got["reason"]) == ("rejected", "no-next-bar")
                    assert got["entry_ts"] is None and got["entry_price"] is None
                else:
                    # Bar k+1 exists in a poisoned frame: same entry bar, poisoned price.
                    assert got["entry_ts"] == want["entry_ts"] == stamps[k + 1]
                    assert (got["status"], got["reason"]) == (want["status"], want["reason"])
                counts["edge"] += 1
            else:
                # Decided strictly before k+1 is needed: every field is identical.
                assert trigger is None or trigger < k
                assert got == want
                counts["full"] += 1
    return counts


def breakout_case():
    breakout = minimal(
        filters={"volume": "volume > prev(volume)"},
        reference={"level": "prev(highest(high, 3))"},
        trigger={"when": "close > prev(high)", "within": 3},
    )
    breakout["setup"]["event"] = "close > prev(highest(high, 3))"
    frame = bars([50 + ((i * 17) % 23) for i in range(80)]).with_columns(
        pl.Series("volume", [100 + i % 7 for i in range(80)])
    )
    return SetupSpec.load(breakout), frame


def delayed_trigger_case():
    """A pullback whose trigger comes on a later bar, or not at all, inside the window."""
    delayed = minimal(
        reference={"avg": "sma(close, 5)"}, trigger={"when": "close > prev(high)", "within": 1}
    )
    delayed["setup"]["event"] = "crosses_below(close, sma(close, 5))"
    return SetupSpec.load(delayed), breakout_case()[1]


def test_example_and_breakout_candidate_prefixes():
    totals = {"full": 0, "edge": 0, "open": 0}
    example = SetupSpec.load(tomllib.loads(EXAMPLE))
    for spec, source in [(example, worked_bars()), breakout_case(), delayed_trigger_case()]:
        texts = [
            spec.setup.event,
            *spec.filters.values(),
            *spec.reference.values(),
            spec.trigger.when,
        ]
        for k in range(1, source.height - 1):
            for text in texts:
                assert_prefix(compile_expr(text).expr, source, k)
            for name, count in assert_candidates_causal(spec, source, k).items():
                totals[name] += count
    # Every branch of the comparison must really have been exercised.
    assert totals["full"] >= 100 and totals["edge"] >= 5 and totals["open"] >= 5, totals
    spec, source = delayed_trigger_case()
    reasons = set(find_candidates(spec, source, symbol="BTC/USDT")["reason"].to_list())
    assert {None, "no-trigger"} <= reasons, reasons


def test_guard_catches_deliberately_leaky_twin():
    with pytest.raises(AssertionError):
        assert_prefix(pl.col("close").shift(-1), bars(list(range(20))), 8)
