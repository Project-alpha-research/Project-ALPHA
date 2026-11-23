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


def _family(n_paths: int, loss: float) -> dict[str, object]:
    return {
        "family": "kronos", "status": "ok", "n_paths": n_paths, "terminal_return_q50": 0.0,
        "terminal_return_q05": -0.1, "terminal_return_q95": 0.1, "maximum_drawdown_q50": -0.05,
        "maximum_drawdown_q95": -0.2, "loss_probability": {"point": loss},
    }


def test_all_eight_paths_lost_is_said_in_counts() -> None:
    from alpha_cli._mc_reading import _family_reading

    said = " ".join(_family_reading(_family(8, 1.0), None, [], WINDOW))
    assert "all 8 simulated paths ended with a loss; 8 paths is too few to rank" in said
    assert "100%" not in said and "of paths" not in said and "5% of" not in said


def test_five_of_eight_paths_lost_is_said_in_counts() -> None:
    from alpha_cli._mc_reading import _family_reading

    said = " ".join(_family_reading(_family(8, 0.625), None, [], WINDOW))
    assert "5 of 8 simulated paths ended with a loss; 8 paths is too few to rank" in said


def test_the_report_lines_give_counts_for_few_paths() -> None:
    from alpha_cli.spine.report_readings import monte_carlo_lines

    line = monte_carlo_lines({"families": [_family(8, 0.625)]})[1]
    assert "paths_below_zero=5 of 8" in line and "0.6250" not in line


def test_many_paths_keep_the_percent_of_paths() -> None:
    from alpha_cli._mc_reading import _family_reading

    assert "62% of paths end with a loss." in " ".join(
        _family_reading(_family(1000, 0.625), None, [], WINDOW)
    )
