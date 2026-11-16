"""Setup parsing, identity and validation."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from alpha_core import DataError
from alpha_study.setup import SetupSpec
from alpha_study.setup.spec import parse_exit

EXAMPLE = """
[setup]
name = "reclaim-20d-after-3-below"
idea = "Daily close back above the 20-day average after three closes below it"
assets = ["BTC/USDT", "SPY"]
timeframe = "1D"
event = "crosses_above(close, sma(close, 20))"
[filters]
three_below = "prev(for_bars(close < sma(close, 20), 3))"
uptrend = "sma(close, 50) > prev(sma(close, 50), 10)"
[trigger]
when = "close > prev(high)"
within = 3
[reference]
avg20 = "sma(close, 20)"
[exit]
time_bars = 10
stop = "2 atr(14)"
target = "3 atr(14)"
opposite = "close < sma(close, 20)"
[study]
horizons = [1, 3, 5, 10]
primary = 5
"""


def minimal(**updates):
    data = {
        "setup": {
            "name": "test",
            "idea": "test idea",
            "assets": ["BTC/USDT"],
            "timeframe": "1D",
            "event": "close > 0",
        }
    }
    data.update(updates)
    return data


def test_load_identity_and_frozen(tmp_path):
    import tomllib

    toml = tmp_path / "setup.toml"
    toml.write_text(EXAMPLE)
    data = tomllib.loads(EXAMPLE)
    js = tmp_path / "setup.json"
    js.write_text(json.dumps(data))
    spec = SetupSpec.load(toml)
    assert spec == SetupSpec.load(js) == SetupSpec.load(data)
    # Key order does not matter anywhere except inside [filters].
    reordered = {key: dict(reversed(list(data[key].items()))) for key in reversed(data)}
    reordered["filters"] = dict(data["filters"])
    assert spec.spec_sha256 == SetupSpec.load(reordered).spec_sha256
    payload = spec.model_dump(mode="json")
    payload["filters"] = [[name, text] for name, text in spec.filters.items()]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert spec.spec_sha256 == hashlib.sha256(canonical.encode()).hexdigest()
    assert list(spec.filters) == ["three_below", "uptrend"]
    assert SetupSpec.load(spec.model_dump(mode="json")) == spec
    with pytest.raises(ValidationError):
        spec.setup.name = "changed"
    with pytest.raises(TypeError):
        spec.filters["new"] = "close > 1"


def test_filter_order_is_part_of_the_identity():
    # Filter order decides the rejection reason, so swapped filters are a different spec.
    data = minimal(filters={"first": "close < 0", "second": "close > 99"})
    swapped = minimal(filters={"second": "close > 99", "first": "close < 0"})
    assert SetupSpec.load(data).spec_sha256 != SetupSpec.load(swapped).spec_sha256
    assert SetupSpec.load(data).spec_sha256 == SetupSpec.load(minimal(**data)).spec_sha256
    two = {"a": "close", "b": "open"}
    assert (
        SetupSpec.load(minimal(reference=two)).spec_sha256
        == SetupSpec.load(minimal(reference=dict(reversed(list(two.items()))))).spec_sha256
    )


@pytest.mark.parametrize("section", ["context", "dates", "session"])
def test_next_piece(section):
    with pytest.raises((DataError, ValidationError), match="next piece"):
        SetupSpec.load(minimal(**{section: {"x": 1}}))
    with pytest.raises((DataError, ValidationError), match="next piece"):
        data = minimal()
        data["setup"][section] = "future"
        SetupSpec.load(data)


@pytest.mark.parametrize("section", [None, "setup", "trigger", "exit", "study"])
def test_unknown_keys(section):
    data = minimal(
        trigger={"when": "close > 0", "within": 2}, study={"horizons": [1], "primary": 1}
    )
    if section is None:
        data["typo"] = 1
    else:
        data.setdefault(section, {})["typo"] = 1
    with pytest.raises((DataError, ValidationError), match="typo.*known keys"):
        SetupSpec.load(data)


@pytest.mark.parametrize(
    "update",
    [
        {"study": {"horizons": [1, 3], "primary": 5}},
        {"study": {"horizons": [], "primary": 1}},
        {"trigger": {"when": "close", "within": 3}},
        {"trigger": {"when": "close > 0", "within": -1}},
        {"filters": {"oops": "close"}},
        {"reference": {"oops": "close > 0"}},
        {"exit": {"stop": "-2 atr(14)"}},
        {"exit": {"target": "2 atr(0)"}},
        {"exit": {"time_bars": 0}},
        {"exit": {"opposite": "close"}},
    ],
)
def test_invalid_sections(update):
    with pytest.raises((DataError, ValidationError)):
        SetupSpec.load(minimal(**update))


@pytest.mark.parametrize(
    "text, kind", [("2 atr(14)", "atr"), ("3 %", "percent"), ("prev(low)", "level")]
)
def test_exit_forms(text, kind):
    assert parse_exit(text).kind == kind


def test_daily_only_and_suffix(tmp_path):
    data = minimal()
    data["setup"]["timeframe"] = "1h"
    with pytest.raises((DataError, ValidationError)):
        SetupSpec.load(data)
    with pytest.raises(DataError, match="suffix"):
        SetupSpec.load(tmp_path / "setup.yaml")
