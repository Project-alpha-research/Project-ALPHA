"""Time estimates come from a stubbed clock: first measured unit times the units in all."""

from __future__ import annotations

from pathlib import Path

import pytest

from alpha_cli._estimate import UnitTimer, read_rate, say_minutes, write_rate
from alpha_cli.test_cmds import RunClock, expected_line, rate_key


class Ticks:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_the_first_unit_times_all_units() -> None:
    ticks = Ticks()
    timer = UnitTimer(8, clock=ticks)
    assert timer.expected() is None
    timer.start()
    ticks.now += 30.0
    timer.finish_unit()
    assert timer.expected() == pytest.approx(240.0, rel=1e-9, abs=1e-12)


def test_a_prior_gives_the_first_guess_and_a_measurement_replaces_it() -> None:
    ticks = Ticks()
    timer = UnitTimer(4, prior_per_unit=100.0, clock=ticks)
    assert timer.expected() == pytest.approx(400.0, rel=1e-9, abs=1e-12)
    timer.start()
    ticks.now += 10.0
    timer.finish_unit()
    assert timer.expected() == pytest.approx(40.0, rel=1e-9, abs=1e-12)


def test_alpha_test_states_its_estimate_again_after_the_first_asset(tmp_path: Path) -> None:
    said: list[str] = []
    clock = RunClock(4, None, said.append)
    ticks = Ticks()
    clock.timer = UnitTimer(4, clock=ticks)
    clock.stage("reading the data for AAA (1 of 4)")
    assert said == [] and clock.timer.expected() is None
    clock.stage("testing AAA (1 of 4)")
    ticks.now += 120.0
    clock.stage("testing BBB (2 of 4)")
    assert said == ["alpha test: measured on the first asset: about 8 minutes in all."]
    ticks.now += 120.0
    clock.stage("testing CCC (3 of 4)")
    assert len(said) == 1


def test_a_big_spec_is_not_given_the_estimate_of_a_small_one(tmp_path: Path) -> None:
    write_rate(tmp_path, "test_asset", 30.0)
    rate = read_rate(tmp_path, "test_asset")
    assert rate == 30.0
    assert UnitTimer(2, prior_per_unit=rate).expected() == 60.0
    assert UnitTimer(10, prior_per_unit=rate).expected() == 300.0


def test_no_prior_means_no_made_up_number() -> None:
    assert "no time estimate yet" in expected_line(None, units=3)
    assert "about 5 minutes" in expected_line(300.0, units=3)
    assert say_minutes(40.0) == "about 40 seconds"


def test_rates_survive_bad_files(tmp_path: Path) -> None:
    (tmp_path / "timing_rates.json").write_text("not json")
    assert read_rate(tmp_path, "test_asset") is None
    write_rate(tmp_path, "test_asset", 5.0)
    assert read_rate(tmp_path, "test_asset") == 5.0
    write_rate(tmp_path, "test_asset", float("nan"))
    assert read_rate(tmp_path, "test_asset") == 5.0


def test_a_first_asset_that_could_not_be_read_does_not_stop_the_clock() -> None:
    """Asset 1 had no data, so the first "testing" stage is asset 2: the clock starts there."""
    said: list[str] = []
    clock = RunClock(3, None, said.append)
    ticks = Ticks()
    clock.timer = UnitTimer(3, clock=ticks)
    clock.stage("testing BBB (2 of 3)")
    ticks.now += 60.0
    clock.stage("testing CCC (3 of 3)")
    assert said == ["alpha test: measured on the first asset: about 3 minutes in all."]


def test_two_assets_get_the_measured_estimate_too() -> None:
    said: list[str] = []
    clock = RunClock(2, None, said.append)
    ticks = Ticks()
    clock.timer = UnitTimer(2, clock=ticks)
    clock.stage("testing AAA (1 of 2)")
    ticks.now += 45.0
    clock.stage("testing BBB (2 of 2)")
    assert said == ["alpha test: measured on the first asset: about 2 minutes in all."]


def test_only_a_run_that_tested_every_asset_keeps_its_rate(tmp_path: Path) -> None:
    """A repeat is read from the stored run in a moment; its time is no rate for a real test."""
    ticks = Ticks()
    for executed, error in ((False, None), (True, "DataError: no bars")):
        clock = RunClock(1, None, lambda _: None)
        clock.timer = UnitTimer(1, clock=ticks)
        clock.stage("testing AAA (1 of 1)")
        ticks.now += 0.1
        clock.finish(tmp_path, "test_asset", [{"executed": executed, "error": error}])
        assert read_rate(tmp_path, "test_asset") is None
    clock = RunClock(1, None, lambda _: None)
    clock.timer = UnitTimer(1, clock=ticks)
    clock.stage("testing AAA (1 of 1)")
    ticks.now += 30.0
    clock.finish(tmp_path, "test_asset", [{"executed": True, "error": None}])
    assert read_rate(tmp_path, "test_asset") == pytest.approx(30.0, rel=1e-9, abs=1e-12)


def test_each_rule_kind_keeps_its_own_rate() -> None:
    """An owner rule with its nearby settings costs more per asset than a built-in rule."""
    assert rate_key(True, "owner", False) != rate_key(True, "ma_cross", False)
    assert rate_key(True, "ma_cross", False) != rate_key(False, "ma_cross", False)
    assert rate_key(True, "ma_cross", True) != rate_key(True, "ma_cross", False)
