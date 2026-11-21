"""The owner rule in a spec: canonical form, refusals, labels, family key and words."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

from alpha_cli.spine.spec import IdeaSpec, load_spec

RSI_DIP: dict[str, Any] = {
    "long_when": [
        {"left": {"indicator": "rsi", "params": [14]}, "op": "<", "right": {"value": 30}},
        {"left": {"source": "close"}, "op": ">", "right": {"indicator": "sma", "params": [200]}},
    ]
}


def idea(spec: dict[str, Any], name: str = "") -> IdeaSpec:
    return IdeaSpec.model_validate(
        {"name": name, "assets": ["SPY"], "rule": {"kind": "owner", "spec": spec}}
    )


def rsi_below(level: float, window: int = 14) -> dict[str, Any]:
    cond = {"left": {"indicator": "rsi", "params": [window]}, "op": "<", "right": {"value": level}}
    return {"long_when": [cond]}


def test_canonical_form_is_inline_with_defaults_and_a_constant_name() -> None:
    plain = idea({**RSI_DIP, "name": "my dip"}, name="rsi-dip")
    rule = json.loads(plain.canonical())["rule"]
    assert rule["kind"] == "owner"
    assert rule["spec"]["history"] == 800  # default history: 4 x the 200-bar warm-up
    assert rule["spec"]["name"] == "owner-rule"
    assert rule["spec"]["version"] == 1 and rule["spec"]["short_when"] == []
    other = idea({**RSI_DIP, "name": "another name"}, name="rsi-dip")
    unnamed = idea(RSI_DIP, name="rsi-dip")
    assert plain.spec_sha256 == other.spec_sha256 == unnamed.spec_sha256
    assert plain.rule.strategy == "rules" and plain.rule.kind == "owner"


def test_integers_and_floats_and_file_forms_give_the_same_hash(tmp_path: Path) -> None:
    ints = idea(rsi_below(30))
    floats = idea(rsi_below(30.0))
    assert ints.spec_sha256 == floats.spec_sha256
    toml = tmp_path / "idea.toml"
    toml.write_text(
        'name = "dip"\nassets = ["SPY"]\n[rule]\nkind = "owner"\n[rule.spec]\n'
        "long_when = [\n"
        '  { left = { indicator = "rsi", params = [14] }, op = "<", right = { value = 30 } },\n'
        "]\n"
    )
    from_toml = load_spec(toml)
    path = tmp_path / "idea.json"
    path.write_text(json.dumps(tomllib.loads(toml.read_text())))
    assert from_toml.spec_sha256 == load_spec(path).spec_sha256
    assert from_toml.rule == idea(rsi_below(30), name="dip").rule
    assert json.loads(from_toml.canonical()) == json.loads(
        IdeaSpec.model_validate_json(from_toml.canonical()).canonical()
    )


def test_default_name_is_owner_plus_the_shape() -> None:
    first, second = idea(rsi_below(30)), idea(rsi_below(25))
    assert first.name == second.name and first.name.startswith("owner-")
    assert len(first.name) == len("owner-") + 8
    assert idea(RSI_DIP).name != first.name
    assert idea(rsi_below(30), name="mine").name == "mine"


def test_short_side_is_refused_not_dropped() -> None:
    both = {**RSI_DIP, "short_when": rsi_below(70)["long_when"]}
    with pytest.raises(ValueError, match="short side is not built yet in alpha test"):
        idea(both)
    only_short = {"short_when": rsi_below(70)["long_when"]}
    with pytest.raises(ValueError, match="short side is not built yet"):
        idea(only_short)
    assert idea({**RSI_DIP, "short_when": []}).spec_sha256 == idea(RSI_DIP).spec_sha256


def test_volume_indicator_is_refused() -> None:
    vsa = {
        "long_when": [
            {"left": {"indicator": "vsa", "params": [20]}, "op": ">", "right": {"value": 0}}
        ]
    }
    with pytest.raises(ValueError, match="vsa.*volume"):
        idea(vsa)


@pytest.mark.parametrize(
    "left, right",
    [
        ({"source": "close"}, {"value": 400}),
        ({"indicator": "sma", "params": [20]}, {"value": 400}),
        ({"source": "close"}, {"indicator": "rsi", "params": [14]}),
    ],
)
def test_a_price_level_must_not_meet_a_fixed_number(
    left: dict[str, Any], right: dict[str, Any]
) -> None:
    """The Tier-1 null rebuilds prices from returns starting at 1, so a fixed price level has no
    meaning there. Refuse it rather than draw a wrong null."""
    with pytest.raises(ValueError, match="price level"):
        idea({"long_when": [{"left": left, "op": ">", "right": right}]})


def test_scale_free_comparisons_are_allowed() -> None:
    zero = {"left": {"indicator": "macd", "params": [12, 26, 9], "field": "histogram"}}
    idea({"long_when": [{**zero, "op": ">", "right": {"value": 0}}]})
    idea(
        {
            "long_when": [
                {"left": {"source": "close"}, "op": ">", "right": {"source": "close", "lag": 20}}
            ]
        }
    )
    idea(rsi_below(30))


def test_unknown_kinds_and_keys_still_fail_loud() -> None:
    with pytest.raises(ValueError, match="known.*ma_cross.*breakout.*tsmom"):
        IdeaSpec.model_validate({"assets": ["SPY"], "rule": {"kind": "oops"}})
    with pytest.raises(ValueError):
        IdeaSpec.model_validate(
            {"assets": ["SPY"], "rule": {"kind": "owner", "spec": RSI_DIP, "x": 1}}
        )
    with pytest.raises(ValueError, match="comparison|conditions|long_when"):
        idea({"long_when": []})


def test_labels_name_the_high_low_approximation() -> None:
    assert idea(RSI_DIP).rule.labels == ()
    atr = {
        "long_when": [
            {
                "left": {"indicator": "atr", "params": [14]},
                "op": ">",
                "right": {"indicator": "atr", "params": [50]},
            }
        ]
    }
    high = {
        "long_when": [
            {"left": {"source": "high"}, "op": ">", "right": {"source": "high", "lag": 20}}
        ]
    }
    for spec in (atr, high):
        assert idea(spec).rule.labels == ("null-closes-for-high-low",)
    old = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    assert old.rule.labels == ()


def test_params_are_the_flat_numbers() -> None:
    rule = idea(RSI_DIP).rule
    assert rule.params == {
        "long_when[0].left.params[0]": 14.0,
        "long_when[0].right.value": 30.0,
        "long_when[1].right.params[0]": 200.0,
    }


def test_family_key_of_old_kinds_is_the_kind() -> None:
    for kind, params in (
        ("ma_cross", ["fast=5", "slow=20"]),
        ("breakout", ["window=20"]),
        ("tsmom", ["lookback=20"]),
    ):
        assert load_spec(None, rule=kind, param=params, asset=["SPY"]).rule.family_key == kind


def family(spec: dict[str, Any]) -> str:
    return idea(spec).rule.family_key


def test_thirty_thresholds_are_one_family() -> None:
    keys = {family(rsi_below(level)) for level in range(5, 35)}
    windows = {family(rsi_below(30, window)) for window in range(2, 32)}
    assert len(keys) == 1 and windows == keys
    (key,) = keys
    assert key.startswith("owner:") and len(key) == len("owner:") + 12


def test_a_different_structure_is_another_family() -> None:
    base = family(rsi_below(30))
    assert family(RSI_DIP) != base
    above = {
        "long_when": [
            {"left": {"indicator": "rsi", "params": [14]}, "op": ">", "right": {"value": 70}}
        ]
    }
    assert family(above) != base
    ema = {
        "long_when": [
            {"left": {"indicator": "ema", "params": [14]}, "op": "<", "right": {"value": 0}}
        ]
    }
    assert family(ema) != base
    lagged = {
        "long_when": [
            {"left": {"source": "close"}, "op": ">", "right": {"source": "close", "lag": 20}}
        ]
    }
    plain = {"long_when": [{"left": {"source": "close"}, "op": ">", "right": {"source": "high"}}]}
    assert family(lagged) != family(plain)


def test_order_strictness_and_sides_do_not_change_the_family() -> None:
    reordered = {"long_when": list(reversed(RSI_DIP["long_when"]))}
    assert family(reordered) == family(RSI_DIP)
    strict = rsi_below(30)
    loose = {"long_when": [{**strict["long_when"][0], "op": "<="}]}
    assert family(loose) == family(strict)
    flipped = {
        "long_when": [
            {"left": {"value": 30}, "op": ">", "right": {"indicator": "rsi", "params": [14]}}
        ]
    }
    assert family(flipped) == family(strict)
    cross = {
        "long_when": [
            {
                "left": {"indicator": "sma", "params": [20]},
                "op": ">",
                "right": {"indicator": "sma", "params": [50]},
            }
        ]
    }
    swapped = {
        "long_when": [
            {
                "left": {"indicator": "sma", "params": [50]},
                "op": "<",
                "right": {"indicator": "sma", "params": [20]},
            }
        ]
    }
    assert family(cross) == family(swapped)
    assert family({**strict, "history": 400}) == family(strict)


def test_words_say_the_rule_in_plain_language() -> None:
    from alpha_cli.spine.owner_rule import OwnerRule, rule_words

    rule = idea(RSI_DIP).rule
    assert isinstance(rule, OwnerRule)
    words = rule_words(rule.spec)
    assert words == rule.words
    assert words == "Long while RSI(14) < 30 and close > SMA(200), flat otherwise."
    assert "profit" not in words
