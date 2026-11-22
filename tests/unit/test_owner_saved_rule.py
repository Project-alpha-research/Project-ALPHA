"""A spec file may name a saved owner rule; it resolves to the inline rule before hashing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from alpha_cli.rules_cmds import rule_path
from alpha_cli.spine.owner_rule import OwnerRule
from alpha_cli.spine.spec import load_spec
from alpha_core import DataError
from alpha_strategies.rules import canonical_json, parse_rule_spec

SPEC: dict[str, Any] = {
    "name": "rsi dip",
    "long_when": [
        {"left": {"indicator": "rsi", "params": [14]}, "op": "<", "right": {"value": 30}},
        {"left": {"source": "close"}, "op": ">", "right": {"indicator": "sma", "params": [200]}},
    ],
}
INLINE = (
    'assets = ["SPY"]\n[rule]\nkind = "owner"\n'
    "[[rule.spec.long_when]]\n"
    'left = {indicator = "rsi", params = [14]}\nop = "<"\nright = {value = 30}\n'
    "[[rule.spec.long_when]]\n"
    'left = {source = "close"}\nop = ">"\nright = {indicator = "sma", params = [200]}\n'
)


def _save(data_dir: Path, name: str, spec: dict[str, Any]) -> Path:
    path = rule_path(data_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(parse_rule_spec(spec)) + "\n", encoding="utf-8")
    return path


def _file(tmp_path: Path, saved: str, extra: str = "") -> Path:
    path = tmp_path / "idea.toml"
    path.write_text(f'assets = ["SPY"]\n[rule]\nkind = "owner"\nsaved = "{saved}"\n{extra}')
    return path


def test_saved_and_inline_have_the_same_hash_family_and_stored_rule(tmp_path: Path) -> None:
    _save(tmp_path / "home", "rsi-dip", SPEC)
    inline = tmp_path / "inline.toml"
    inline.write_text(INLINE)
    saved = load_spec(_file(tmp_path, "rsi-dip"), data_dir=tmp_path / "home")
    plain = load_spec(inline, data_dir=tmp_path / "home")
    assert saved.spec_sha256 == plain.spec_sha256
    assert saved.rule.family_key == plain.rule.family_key
    assert saved.model_dump(mode="json") == plain.model_dump(mode="json")
    assert saved.name == plain.name
    assert "saved" not in json.dumps(saved.model_dump(mode="json"))


def test_a_later_edit_of_the_saved_rule_does_not_change_a_loaded_spec(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _save(home, "rsi-dip", SPEC)
    before = load_spec(_file(tmp_path, "rsi-dip"), data_dir=home)
    edited = json.loads(json.dumps(SPEC))
    edited["long_when"][0]["right"]["value"] = 25
    _save(home, "rsi-dip", edited)
    after = load_spec(_file(tmp_path, "rsi-dip"), data_dir=home)
    assert before.spec_sha256 != after.spec_sha256
    assert isinstance(before.rule, OwnerRule)
    assert before.rule.spec["long_when"][0]["right"] == {"value": 30}


def test_a_missing_saved_rule_fails_loud_with_its_name(tmp_path: Path) -> None:
    with pytest.raises((ValueError, DataError), match="no-such-rule"):
        load_spec(_file(tmp_path, "no-such-rule"), data_dir=tmp_path / "home")


def test_an_invalid_saved_rule_fails_loud_with_its_name(tmp_path: Path) -> None:
    home = tmp_path / "home"
    path = rule_path(home, "broken")
    path.parent.mkdir(parents=True)
    path.write_text('{"name": "x", "long_when": []}', encoding="utf-8")
    with pytest.raises((ValueError, DataError), match="broken"):
        load_spec(_file(tmp_path, "broken"), data_dir=home)


def test_a_saved_rule_with_a_short_side_is_refused_with_its_name(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _save(home, "shorty", {**SPEC, "short_when": SPEC["long_when"][:1]})
    with pytest.raises((ValueError, DataError), match="shorty"):
        load_spec(_file(tmp_path, "shorty"), data_dir=home)


def test_saved_with_an_inline_spec_is_refused(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _save(home, "rsi-dip", SPEC)
    extra = "[rule.spec]\nlong_when = []\n"
    with pytest.raises((ValueError, DataError), match="saved"):
        load_spec(_file(tmp_path, "rsi-dip", extra), data_dir=home)


def test_a_bad_saved_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises((ValueError, DataError), match="../x"):
        load_spec(_file(tmp_path, "../x"), data_dir=tmp_path / "home")


def test_saved_needs_a_data_dir(tmp_path: Path) -> None:
    with pytest.raises((ValueError, DataError), match="rsi-dip"):
        load_spec(_file(tmp_path, "rsi-dip"))
