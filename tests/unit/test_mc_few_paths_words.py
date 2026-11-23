"""A Monte Carlo run with few paths gives a count and the window, never a percentage."""

from __future__ import annotations

from alpha_cli._mc_reading import rank_sentence

WINDOW = "window 2 January 2024 to 30 June 2024"


def test_eight_paths_say_all_eight_and_too_few_to_rank() -> None:
    said = rank_sentence(0.10, [0.01 * i for i in range(8)], WINDOW)
    assert "above all 8 simulated paths, which is too few to rank" in said
    assert "100%" not in said and WINDOW in said


def test_some_below_few_paths_gives_a_count() -> None:
    said = rank_sentence(0.035, [0.01 * i for i in range(8)], WINDOW)
    assert "above 4 of 8 simulated paths" in said


def test_many_paths_still_give_a_percentage() -> None:
    said = rank_sentence(0.5, [i / 1000 for i in range(1000)], WINDOW)
    assert said.endswith("above 50% of the simulated paths.")
