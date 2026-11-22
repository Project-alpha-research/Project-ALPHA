"""The nightly example config in `research/examples` loads, and every file it names is there and
parses as the spec it is meant to be."""

from __future__ import annotations

import tomllib
from pathlib import Path

from alpha_cli.nightly_config import load_config
from alpha_cli.spine.setup_find import load_setup_spec
from alpha_cli.spine.spec import load_spec

EXAMPLES = Path(__file__).resolve().parents[2] / "research" / "examples"


def test_the_example_config_resolves_every_file_it_names() -> None:
    config = load_config(EXAMPLES / "nightly.example.toml")
    assert config.rule_spec.parent == config.setup_spec.parent == EXAMPLES
    rule = load_spec(config.rule_spec)
    setup = load_setup_spec(config.setup_spec)
    raw = tomllib.loads(config.setup_spec.read_text(encoding="utf-8"))
    assert "exit" in raw  # `alpha setup trade` needs an [exit] table
    assert set(rule.assets) == set(raw["setup"]["assets"]) == set(config.assets)
    assert setup is not None
