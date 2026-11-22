"""Parameter variants of an owner rule: windows and constants at 0.8 and 1.2, capped."""

from __future__ import annotations

from typing import Any

from alpha_cli.spine.owner_rule import OwnerRule, canonical_spec
from alpha_cli.spine.owner_variants import MAX_VARIANTS, owner_variants


def _spec(*conditions: dict[str, Any], history: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"long_when": list(conditions)}
    if history is not None:
        out["history"] = history
    return canonical_spec(out)


def _rsi(window: int, level: float) -> dict[str, Any]:
    return {"left": {"indicator": "rsi", "params": [window]}, "op": "<", "right": {"value": level}}


def _sma(window: int) -> dict[str, Any]:
    right = {"indicator": "sma", "params": [window]}
    return {"left": {"source": "close"}, "op": ">", "right": right}


def _rights(found: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    return [variant["long_when"][0]["right"] for _, variant in found]


def test_a_window_and_a_constant_give_four_variants() -> None:
    found = owner_variants(_spec(_rsi(14, 30)))
    assert len(found) == 4
    pairs = {
        (v["long_when"][0]["left"]["params"][0], v["long_when"][0]["right"]["value"])
        for _, v in found
    }
    assert pairs == {(11, 30.0), (17, 30.0), (14, 24.0), (14, 36.0)}


def test_windows_round_to_whole_bars_with_a_floor_of_two() -> None:
    found = owner_variants(_spec(_sma(3)))
    assert sorted(r["params"][0] for r in _rights(found)) == [2, 4]
    assert owner_variants(_spec(_sma(2))) == []  # 1.6 and 2.4 both round back to 2


def test_a_variant_equal_to_the_original_is_skipped() -> None:
    found = owner_variants(_spec(_sma(2)))
    assert all(r["params"] != [2] for r in _rights(found))
    assert all(variant != _spec(_sma(2)) for _, variant in found)


def test_a_zero_constant_is_not_varied() -> None:
    cond = {
        "left": {"indicator": "macd", "params": [12, 26, 9], "field": "histogram"},
        "op": ">",
        "right": {"value": 0},
    }
    found = owner_variants(_spec(cond))
    assert found and all(r == {"value": 0.0} for r in _rights(found))


def test_the_list_is_capped_in_a_fixed_order() -> None:
    spec = _spec(_rsi(14, 30), _sma(50), _sma(100), _sma(200), _rsi(7, 70), history=1000)
    found = owner_variants(spec)
    assert len(found) == MAX_VARIANTS == 8
    assert len({name for name, _ in found}) == 8
    assert found == owner_variants(spec)
    assert found[0][0] == "condition 1 left window 14 to 11"


def test_every_variant_is_a_valid_owner_rule_that_differs_from_the_original() -> None:
    spec = _spec(_rsi(14, 30), _sma(200))
    for _, variant in owner_variants(spec):
        assert variant != spec
        OwnerRule(kind="owner", spec=variant)


def test_a_window_past_the_history_widens_it_only_as_far_as_needed() -> None:
    found = owner_variants(_spec(_sma(100), history=100))
    grown = [v for _, v in found if v["long_when"][0]["right"]["params"] == [120]]
    assert len(grown) == 1 and grown[0]["history"] == 120


def test_macd_variants_name_which_window_moved() -> None:
    cond = {
        "left": {"indicator": "macd", "params": [12, 26, 12], "field": "line"},
        "op": ">",
        "right": {"indicator": "macd", "params": [12, 26, 12], "field": "signal"},
    }
    names = [name for name, _ in owner_variants(_spec(cond))]
    assert len(names) == len(set(names)) == 8
    assert "condition 1 left fast window 12 to 10" in names
    assert "condition 1 left signal window 12 to 10" in names


def test_bollinger_width_is_not_a_window() -> None:
    right = {"indicator": "bbands", "params": [20, 2], "field": "lower"}
    found = owner_variants(_spec({"left": {"source": "close"}, "op": "<", "right": right}))
    assert {r["params"][1] for r in _rights(found)} == {2}
    assert sorted(r["params"][0] for r in _rights(found)) == [16, 24]


def test_a_lag_is_varied_with_a_floor_of_one_and_zero_is_left() -> None:
    cond = {"left": {"source": "close"}, "op": ">", "right": {"source": "close", "lag": 5}}
    assert sorted(r["lag"] for r in _rights(owner_variants(_spec(cond)))) == [4, 6]
    flat = {"left": {"source": "close"}, "op": ">", "right": {"source": "close"}}
    assert owner_variants(_spec(flat)) == []


def test_a_channel_window_is_varied() -> None:
    channel = {"indicator": "highest", "params": [20], "field": "high", "lag": 1}
    found = owner_variants(_spec({"left": {"source": "close"}, "op": ">", "right": channel}))
    assert sorted(r["params"][0] for r in _rights(found)) == [16, 24]
