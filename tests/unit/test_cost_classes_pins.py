"""Golden pins: what a rule-test spec means, with and without stated costs (M71, M99)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from alpha_cli.spine.run import assemble_run_spec
from alpha_cli.spine.spec import IdeaSpec, load_spec
from alpha_cli.spine.stores import annualisation
from alpha_cli.spine.trial_record import make_test_key

# Pin change (M99): a spec without costs now takes the class default, so its hash moved; the old
# hash is now the hash of the flat default stated in the spec, which every stored run keeps.
STATED_DEFAULT_HASH = "2668857e7aa7c8b17bcb3ece3f17cdfbc2f6e80fc361721a689a5b4bdf9fbb8b"
STATED_COSTS_HASH = "043f7640fdff3a05e8e273d0dfa5280aba68f34f9b1eba417315e65943a1e6b5"


def test_spec_without_costs_takes_the_class_default() -> None:
    spec = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    assert spec.costs_class_default
    assert spec.spec_sha256 != STATED_DEFAULT_HASH
    assert '"costs":{"fee_bps":1.0,"mode":"class-default","slippage_bps":2.0}' in spec.canonical()


def test_stated_flat_default_keeps_the_old_hash() -> None:
    spec = load_spec(
        None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"], fee_bps=1, slippage_bps=2
    )
    assert not spec.costs_class_default
    assert spec.spec_sha256 == STATED_DEFAULT_HASH


def test_stated_costs_keep_hash_and_numbers() -> None:
    spec = load_spec(
        None, rule="breakout", param=["window=20"], asset=["SPY"], fee_bps=3, slippage_bps=4
    )
    assert spec.spec_sha256 == STATED_COSTS_HASH
    run = assemble_run_spec(spec, "SPY", 252, 2000)
    assert run.fee_bps == pytest.approx(3.0, rel=1e-9, abs=1e-12)
    assert run.slippage_bps == pytest.approx(4.0, rel=1e-9, abs=1e-12)


def test_no_costs_and_stated_default_are_two_specs() -> None:
    """No costs stated asks for the class default; the stated flat default stays as stated."""
    bare = IdeaSpec.model_validate({"assets": ["SPY"], "rule": {"kind": "breakout", "window": 20}})
    stated = IdeaSpec.model_validate(
        {
            "assets": ["SPY"],
            "rule": {"kind": "breakout", "window": 20},
            "costs": {"fee_bps": 1.0, "slippage_bps": 2.0},
        }
    )
    assert bare.costs_class_default and not stated.costs_class_default
    assert bare.spec_sha256 != stated.spec_sha256


def test_test_key_pinned() -> None:
    key = make_test_key(
        STATED_DEFAULT_HASH, ("SPY",), "2020-01-01", "2024-01-01", "1D", store="home", data_id="x"
    )
    assert key is not None
    assert STATED_DEFAULT_HASH in repr(key)


def test_stock_annualisation_unchanged() -> None:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    days = [start + timedelta(days=i) for i in range(3653)]
    sessions = [stamp for stamp in days if stamp.weekday() < 5]
    holidays = {
        stamp
        for year in range(2020, 2031)
        for stamp in [day for day in sessions if day.year == year][:9]
    }
    assert annualisation([s for s in sessions if s not in holidays], bar_size=None)[0] == 252
    assert annualisation(days, bar_size=None)[0] == 365
