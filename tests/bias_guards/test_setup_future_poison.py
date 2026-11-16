"""Prefix causality, including the one explicitly future-dependent entry bar."""

import math
import random
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from alpha_study.setup import SetupSpec, compile_expr, evaluate, find_candidates
from tests.unit.test_setup_evaluate import bars, worked_bars
from tests.unit.test_setup_spec import EXAMPLE, minimal

pytestmark = pytest.mark.bias_guard

Decision = Callable[
    [int, SetupSpec, dict[str, list[Any]], int], tuple[str | None, str | None, int | None]
]


OHLCV = ("open", "high", "low", "close", "volume")


def rich_bars(n: int, seed: int = 7) -> pl.DataFrame:
    """A random walk where open, close and volume all differ: no degenerate comparisons."""
    rng = random.Random(seed)
    close, rows = 100.0, []
    for _ in range(n):
        open_ = close * (1 + rng.uniform(-0.02, 0.02))
        close = open_ * (1 + rng.uniform(-0.03, 0.03))
        high = max(open_, close) * (1 + rng.uniform(0, 0.02))
        low = min(open_, close) * (1 - rng.uniform(0, 0.02))
        rows.append((open_, high, low, close, float(rng.randint(50, 500))))
    frame = pl.DataFrame(rows, schema=list(OHLCV), orient="row")
    stamps = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(n)]
    return frame.with_columns(pl.Series("ts", stamps))


def variants(frame: pl.DataFrame, k: int, *, evaluator: bool = False) -> list[pl.DataFrame]:
    """(a) full, (b) truncated after k, (c) x1000 after k, (d) huge but valid after k,
    (e) volume missing after k, and for raw expressions (f) NaN everywhere after k
    (the evaluator itself refuses non-finite bars, so (f) is expression-only)."""
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
    missing = frame.with_columns(
        pl.when(after).then(None).otherwise(pl.col("volume")).alias("volume")
    )
    out = [frame, frame.head(k + 1), multiplied, huge, missing]
    if not evaluator:
        nan = frame.with_columns(
            [pl.when(after).then(math.nan).otherwise(pl.col(c)).alias(c) for c in OHLCV]
        )
        out.append(nan)
    return out


def assert_prefix(expr: pl.Expr, frame: pl.DataFrame, k: int) -> None:
    results = [
        variant.with_columns(expr.alias("value")).select("value").head(k + 1)
        for variant in variants(frame, k)
    ]
    for result in results[1:]:
        assert_frame_equal(results[0], result, check_exact=True)


def generated_expressions() -> list[str]:
    rng = random.Random(1401)

    def number(depth: int) -> str:
        if depth == 0:
            # 0 is in the leaves so division by zero is generated too.
            return rng.choice(["open", "high", "low", "close", "volume", "2", "0", "1.5"])
        x, n = number(depth - 1), rng.randint(1, 30)
        choice = rng.randrange(15)
        if choice < 7:
            fn = ["prev", "sma", "ema", "highest", "lowest", "pct_change", "abs"][choice]
            return f"{fn}({x})" if fn == "abs" else f"{fn}({x}, {n})"
        if choice == 7:
            return f"atr({n})"
        if choice == 8:
            return f"(-{x})"
        if choice == 9:
            return f"{rng.choice(['prev', 'pct_change'])}({x}, n={rng.randint(1, 5)})"
        return f"({x} {rng.choice(['+', '-', '*', '/'])} {number(depth - 1)})"

    def boolean(depth: int) -> str:
        if depth == 0:
            return f"({number(1)} {rng.choice(['<', '<=', '>', '>=', '==', '!='])} {number(1)})"
        choice = rng.randrange(7)
        if choice < 3:
            fn = ["prev", "for_bars", "within_bars"][choice]
            return f"{fn}({boolean(depth - 1)}, {rng.randint(1, 5)})"
        if choice < 5:
            # The second argument is sometimes a bare literal level.
            b = rng.choice([number(1), str(rng.randint(0, 200))])
            return f"{['crosses_above', 'crosses_below'][choice - 3]}({number(1)}, {b})"
        if choice == 5:
            return f"not ({boolean(depth - 1)})"
        return f"({boolean(depth - 1)} {rng.choice(['and', 'or'])} {boolean(depth - 1)})"

    return [number(3) if i % 2 else boolean(2) for i in range(220)]


def test_generated_expression_prefixes() -> None:
    expressions = generated_expressions()
    assert len(set(expressions)) >= 200
    # Every vocabulary term and operator appears in the generated set.
    joined = " ".join(expressions)
    for term in [*OHLCV, "prev(", "sma(", "ema(", "atr(", "highest(", "lowest(", "pct_change("]:
        assert term in joined, term
    for term in ["abs(", "crosses_above(", "crosses_below(", "for_bars(", "within_bars("]:
        assert term in joined, term
    for term in [" + ", " - ", " * ", " / ", "(-", "n=", " < ", " <= ", " > ", " >= "]:
        assert term in joined, term
    for term in [" == ", " != ", " and ", " or ", "not ", "/ 0)"]:
        assert term in joined, term
    frame = rich_bars(120).with_columns(
        # A missing volume mid-series is legal input; it must not leak either.
        pl.when(pl.int_range(pl.len()) == 30).then(None).otherwise(pl.col("volume")).alias("volume")
    )
    for text in expressions:
        for k in [11, 39, 63, 100]:
            assert_prefix(compile_expr(text).expr, frame, k)


ENTRY = ["entry_ts", "entry_price"]
OUTCOME = ["status", "reason", "detail", "trigger_ts", *ENTRY]


def assert_candidates_causal(spec: SetupSpec, source: pl.DataFrame, k: int) -> dict[str, int]:
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
    assert_next_open(full, source)
    known = full.filter(pl.col("event_ts") <= stamps[k])
    counts = {"full": 0, "edge": 0, "open": 0}
    for number, variant in enumerate(variants(source, k, evaluator=True)[1:]):
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


def assert_next_open(candidates: pl.DataFrame, source: pl.DataFrame) -> None:
    """Entry is always the open of the bar after the trigger: never the trigger bar itself
    (decided at its close) and never later. Prefix poisoning cannot see this, so check it."""
    stamps, opens = source["ts"].to_list(), source["open"].to_list()
    index = {ts: i for i, ts in enumerate(stamps)}
    for row in candidates.iter_rows(named=True):
        if row["entry_ts"] is None:
            assert row["status"] != "accepted"
            continue
        trigger = index[row["trigger_ts"]]
        assert index[row["event_ts"]] <= trigger
        assert index[row["entry_ts"]] == trigger + 1
        assert row["entry_price"] == opens[trigger + 1]


def breakout_case() -> tuple[SetupSpec, pl.DataFrame]:
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


def delayed_trigger_case() -> tuple[SetupSpec, pl.DataFrame]:
    """A pullback whose trigger comes on a later bar, or not at all, inside the window."""
    delayed = minimal(
        reference={"avg": "sma(close, 5)"}, trigger={"when": "close > prev(high)", "within": 1}
    )
    delayed["setup"]["event"] = "crosses_below(close, sma(close, 5))"
    return SetupSpec.load(delayed), breakout_case()[1]


def test_example_and_breakout_candidate_prefixes() -> None:
    totals = {"full": 0, "edge": 0, "open": 0}
    example = SetupSpec.load(tomllib.loads(EXAMPLE))
    rich = rich_bars(90, seed=11)
    cases = [
        (example, worked_bars()),
        breakout_case(),
        delayed_trigger_case(),
        (breakout_case()[0], rich),
        (delayed_trigger_case()[0], rich),
    ]
    for spec, source in cases:
        assert spec.trigger is not None
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


def test_guard_catches_deliberately_leaky_twin() -> None:
    with pytest.raises(AssertionError):
        assert_prefix(pl.col("close").shift(-1), bars(list(range(20))), 8)


def _leaky_decision(reach: int) -> Decision:
    """A twin of the real decision whose trigger search reaches `reach` bars past the window."""
    real = evaluate._decision

    def decision(
        i: int, spec: SetupSpec, values: dict[str, list[Any]], length: int
    ) -> tuple[str | None, str | None, int | None]:
        if spec.trigger is None:
            return real(i, spec, values, length)
        widened = spec.model_copy(
            update={
                "trigger": spec.trigger.model_copy(update={"within": spec.trigger.within + reach})
            }
        )
        reason, detail, trigger = real(i, widened, values, length)
        if reason == "pending-trigger" and i + spec.trigger.within < length:
            return "no-trigger", detail, None  # looks decided although it peeked ahead
        return reason, detail, trigger

    return decision


def test_guard_catches_an_evaluator_that_searches_past_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(evaluate, "_decision", _leaky_decision(1))
    spec, source = delayed_trigger_case()
    with pytest.raises(AssertionError):
        for k in range(1, source.height - 1):
            assert_candidates_causal(spec, source, k)


def test_guard_catches_entry_at_the_trigger_bar_open() -> None:
    spec, source = breakout_case()
    honest = find_candidates(spec, source, symbol="BTC/USDT")
    assert_next_open(honest, source)
    stamps, opens = source["ts"].to_list(), source["open"].to_list()
    index = {ts: i for i, ts in enumerate(stamps)}
    leaky = honest.with_columns(
        pl.col("trigger_ts").alias("entry_ts"),
        pl.col("trigger_ts")
        .map_elements(lambda ts: opens[index[ts]] if ts is not None else None, pl.Float64)
        .alias("entry_price"),
    )
    with pytest.raises(AssertionError):
        assert_next_open(leaky, source)


def test_guard_catches_a_leak_hidden_behind_nan_and_null() -> None:
    # A leak that reads a later row only through a null/NaN path is still caught.
    frame = rich_bars(40)
    with pytest.raises(AssertionError):
        assert_prefix(pl.col("volume").shift(-3).is_null(), frame, 20)
