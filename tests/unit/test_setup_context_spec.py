"""A setup spec may declare context aliases: identity, language, reasons and counts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest
from pydantic import ValidationError

from alpha_core import DataError
from alpha_study.setup import SetupSpec, compile_expr, find_candidates
from alpha_study.setup.context import condition_counts, spells

BASE: dict[str, Any] = dict(
    setup=dict(name="n", idea="i", assets=["SPY"], timeframe="1D", event="close > 1")
)
RICH: dict[str, Any] = dict(
    setup=dict(
        name="n", idea="i", assets=["SPY", "QQQ"], timeframe="1D", event="close > sma(close, 20)"
    ),
    filters={"b": "volume > 1", "a": "close > open"},
    trigger=dict(when="high > prev(high, 1)", within=3),
    reference={"base": "low"},
    exit=dict(direction="short", time_bars=5, stop="2 atr(14)", target="low"),
    study=dict(horizons=[1, 5], primary=5),
)
# Stored expectations: these hashes were computed on the code before `[context]` existed.
OLD_BASE = "68cc308d1e2265e2f73b5a67060b0d0c303c3b6641613299a1643f9d5286326b"
OLD_RICH = "ffa90cc5059027f58f1cb28869fc7a241ccf2ae78c12141d444016aac5917e8a"
BINDING = "cot_nc_net_pct_156w@13874A"


def with_context(base: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {**base, "context": {"es_pos": BINDING}, **extra}


def test_a_spec_without_context_keeps_its_identity() -> None:
    assert SetupSpec.load(BASE).spec_sha256 == OLD_BASE
    assert SetupSpec.load(RICH).spec_sha256 == OLD_RICH
    assert "context" not in SetupSpec.load(BASE).model_dump(mode="json")
    assert "context" not in SetupSpec.load({**BASE, "context": {}}).model_dump(mode="json")
    assert SetupSpec.load({**BASE, "context": {}}).spec_sha256 == OLD_BASE


def test_context_is_part_of_the_identity_and_ignores_key_order() -> None:
    spec = SetupSpec.load(with_context(BASE))
    assert spec.spec_sha256 != OLD_BASE
    assert spec.model_dump(mode="json")["context"] == {"es_pos": BINDING}
    two = {"a_x": "sv_ratio@SELF", "b_y": "cot_nc_net_oi@13874A"}
    one = SetupSpec.load({**BASE, "context": two})
    other = SetupSpec.load({**BASE, "context": dict(reversed(list(two.items())))})
    assert one.spec_sha256 == other.spec_sha256
    changed = SetupSpec.load({**BASE, "context": {**two, "b_y": "cot_nc_net_oi@209742"}})
    assert changed.spec_sha256 != one.spec_sha256


@pytest.mark.parametrize(
    "context",
    [
        {"close": BINDING},
        {"sma": BINDING},
        {"Bad": BINDING},
        {"es_pos": "cot_nc_net_pct_156w"},
        {"es_pos": "@13874A"},
        {"es_pos": "x@a b"},
        {"base": BINDING},
        {"a": BINDING},
    ],
)
def test_bad_aliases_and_bindings_fail_loud(context: dict[str, str]) -> None:
    with pytest.raises((DataError, ValidationError)):
        SetupSpec.load({**RICH, "context": context})


def test_an_alias_works_in_the_event_filters_trigger_and_reference() -> None:
    spec = SetupSpec.load(
        {
            "setup": dict(BASE["setup"], event="es_pos > 0.5"),
            "filters": {"high_pos": "es_pos >= 0.9"},
            "trigger": dict(when="es_pos < 0.2", within=2),
            "reference": {"pos": "es_pos * 2"},
            "context": {"es_pos": BINDING},
        }
    )
    assert spec.context["es_pos"] == BINDING


def test_an_unknown_name_and_an_alias_in_an_exit_still_fail() -> None:
    with pytest.raises((DataError, ValidationError)):
        SetupSpec.load({**BASE, "setup": dict(BASE["setup"], event="es_pos > 1")})
    with pytest.raises((DataError, ValidationError)):
        SetupSpec.load(with_context(BASE, exit=dict(opposite="es_pos > 0.9")))


def ctx_frame(values: list[float | None], reasons: list[str | None] | None = None) -> pl.DataFrame:
    n = len(values)
    stamp = datetime(2021, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        {
            "ts": [stamp + timedelta(days=i) for i in range(n)],
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1.0] * n,
            "ctx_es_pos": pl.Series(values, dtype=pl.Float64),
            "ctx_es_pos_reason": pl.Series(reasons or [None] * n, dtype=pl.String),
        }
    )


def test_the_language_reads_an_alias_with_warm_up_zero_and_a_null_is_never_true() -> None:
    names = frozenset({"es_pos"})
    compiled = compile_expr("es_pos > 0.9", names)
    assert compiled.warmup == 0 and compiled.kind == "boolean"
    frame = ctx_frame([0.95, None, 0.5, 0.91])
    assert frame.select(compiled.expr.alias("x"))["x"].to_list() == [True, None, False, True]
    both = compile_expr("es_pos > 0.9 and close > 1", names)
    assert frame.select(both.expr.alias("x"))["x"].to_list() == [True, None, False, True]
    assert compile_expr("es_pos + close", names).kind == "number"
    with pytest.raises(DataError, match="offending token"):
        compile_expr("es_pos > 0.9")


def spec_with_filter(**extra: Any) -> SetupSpec:
    return SetupSpec.load(
        {
            "setup": dict(BASE["setup"], event="volume == 1"),
            "filters": {"es_hot": "es_pos > 0.9"},
            "context": {"es_pos": BINDING},
            **extra,
        }
    )


def test_find_rejects_by_reason_context_stale_and_not_yet_known() -> None:
    values: list[float | None] = [None, 0.95, 0.5, None, 0.95, 0.95]
    reasons: list[str | None] = ["not-yet-known", None, None, "stale", None, None]
    result = find_candidates(spec_with_filter(), ctx_frame(values, reasons), symbol="SPY")
    assert result["reason"].to_list() == [
        "warm-up",
        None,
        "es_hot",
        "context-stale",
        None,
        "no-next-bar",
    ]
    assert result["detail"].to_list()[3] == "es_hot: context value too old"
    assert result["status"].to_list()[:5] == [
        "rejected",
        "accepted",
        "rejected",
        "rejected",
        "accepted",
    ]


def test_find_needs_the_attached_columns() -> None:
    plain = ctx_frame([0.1]).drop("ctx_es_pos", "ctx_es_pos_reason")
    with pytest.raises(DataError, match="attach"):
        find_candidates(spec_with_filter(), plain, symbol="SPY")


def test_spells_count_separate_runs_not_days() -> None:
    assert spells([True, True, None, True, False, True, True, True]) == 3
    assert spells([]) == 0 and spells([None, False]) == 0


def test_condition_counts_report_true_bars_and_spells() -> None:
    values: list[float | None] = [None, 0.95, 0.95, 0.95, 0.2, 0.95, None, 0.95, 0.95]
    counts = condition_counts(spec_with_filter(), ctx_frame(values))
    assert counts == {"filter:es_hot": dict(true_bars=6, spells=3)}


@pytest.mark.parametrize(
    "text",
    [
        "not within_bars(es_pos > 0.9, 3)",
        "not for_bars(es_pos > 0.9, 3)",
        "not prev(within_bars(es_pos > 0.9, 2), 1)",
        "within_bars(not (es_pos > 0.9), 3)",
    ],
)
def test_a_window_over_a_null_context_value_is_never_true_even_negated(text: str) -> None:
    compiled = compile_expr(text, frozenset({"es_pos"}))
    frame = ctx_frame([None] * 8)
    assert True not in frame.select(compiled.expr.alias("x"))["x"].to_list()


def test_windows_over_context_use_three_valued_logic() -> None:
    names = frozenset({"es_pos"})
    frame = ctx_frame([0.95, None, 0.5, 0.95, 0.95, 0.95, None, 0.2])
    within = compile_expr("within_bars(es_pos > 0.9, 2)", names).expr
    every = compile_expr("for_bars(es_pos > 0.9, 2)", names).expr
    # A known true makes `within` true and a known false makes `for` false; otherwise null.
    assert frame.select(within.alias("x"))["x"].to_list() == [
        None, True, None, True, True, True, True, None,
    ]  # fmt: skip
    assert frame.select(every.alias("x"))["x"].to_list() == [
        None, None, False, False, True, True, None, False,
    ]  # fmt: skip
    # Price-only windows keep their old rule: a missing value inside the window is false.
    plain = compile_expr("within_bars(volume > 0, 2)").expr
    gaps = ctx_frame([0.1] * 3).with_columns(pl.Series("volume", [None, None, 1.0]))
    assert gaps.select(plain.alias("x"))["x"].to_list() == [None, False, True]


def test_an_alias_in_an_exit_says_context_is_not_read_by_exits() -> None:
    for exit_table in (
        dict(opposite="es_pos > 0.9"),
        dict(target="es_pos * 100"),
        dict(stop="low - es_pos"),
    ):
        with pytest.raises((DataError, ValidationError), match=r"\[exit\]"):
            SetupSpec.load(with_context(BASE, exit=exit_table))
