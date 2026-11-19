"""The Student-t Monte Carlo family as a check: fat-tailed redraws of a run's own returns.

The entry calls the public path function that ``alpha monte-carlo classical`` calls for this
family, with the command's own default and seed name. ``alpha_validation`` computes the numbers.
The command's calm-and-stormy family is not an entry: it labels bars from the market's closes,
and a check on stored equity receives no market series.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli._seeds import semantic_seed
from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray

TESTS = "tests/unit/test_toolbox_montecarlo_checks.py::"
BASIS = "After-cost bar returns from the stored walk-forward equity curve."
KEYS = ("low", "median", "high", "drop_q95")
# Bound the paths-by-bars matrices that path_metric_arrays allocates, even on long histories.
PATH_CHUNK_CELLS = 4_000_000


def _unavailable(reason: str, seed: int) -> Result:
    return Result(
        dict.fromkeys(KEYS), dict.fromkeys(KEYS, reason), details={"seed": seed}, basis=BASIS
    )


def _chunk_rows(n_bars: int) -> int:
    return max(1, PATH_CHUNK_CELLS // n_bars)


def _result(terminal: FloatArray, drawdown: FloatArray, seed: int) -> Result:
    import numpy as np

    # The same quantiles summarize_path_family takes of the same per-path outcomes.
    low, median, high = np.quantile(terminal, [0.05, 0.50, 0.95])
    return Result(
        {
            "low": float(low),
            "median": float(median),
            "high": float(high),
            "drop_q95": float(np.quantile(drawdown, 0.95)),
        },
        {},
        basis=BASIS,
        details={"seed": seed},
    )


def _outputs() -> tuple[Output, ...]:
    return (
        Output(
            "low",
            "Low final return",
            "5th percentile of final return: one history in 20 ended lower.",
            "fraction",
        ),
        Output("median", "Typical final return", "Median final return.", "fraction"),
        Output(
            "high",
            "High final return",
            "95th percentile of final return: one history in 20 ended higher.",
            "fraction",
        ),
        Output(
            "drop_q95",
            "1-in-20 worst drop",
            "95th percentile of the worst drops: one history in 20 fell further.",
            "fraction",
        ),
    )


def student_t_paths(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    from alpha_core import DataError
    from alpha_validation.path_montecarlo import path_metric_arrays, student_t_return_paths

    returns = inputs.stored.scored_returns()
    n_paths = params["n_paths"]
    if len(returns) < 2:
        return _unavailable("Paths need at least 2 scored bar returns.", inputs.seed)
    if returns.min() == returns.max():
        return _unavailable("Fat-tailed paths need varying scored returns.", inputs.seed)
    if n_paths < 1:
        raise DataError(f"n_paths must be >= 1, got {n_paths}")
    terminal = np.empty(n_paths)
    drawdown = np.empty(n_paths)
    step = _chunk_rows(len(returns))
    # student_t_return_paths calls default_rng(seed), which reuses a supplied Generator, so
    # chunks continue one stream and reproduce a single large draw.
    chunk: dict[str, Any] = {"seed": np.random.default_rng(inputs.seed)}
    for start in range(0, n_paths, step):
        stop = min(start + step, n_paths)
        paths = student_t_return_paths(returns, **{**chunk, "n_paths": stop - start})
        metrics = path_metric_arrays(paths)
        terminal[start:stop], drawdown[start:stop] = (
            metrics.terminal_return,
            metrics.maximum_drawdown,
        )
    return _result(terminal, drawdown, inputs.seed)


STUDENT_T_PATHS = ToolSpec(
    id="resampling.student_t_paths",
    answers=(
        "How bad could the drawdown get if returns have fatter tails?",
        "What range of final return do fat-tailed histories give?",
    ),
    situations=("drawdown", "return-range"),
    family="resampling",
    kind="test",
    look="test",
    question="What range of final return and worst drop do fat-tailed histories give?",
    needs=("stored_equity",),
    params=(Param("n_paths", int, 10_000, None, "Number of redrawn histories."),),
    outputs=_outputs(),
    reading=(
        "This re-draws the run's past returns at random; it is not a forecast. Each bar was drawn"
        " on its own from a fat-tailed (Student-t) curve fitted to the run's returns, so rare large"
        " moves come up more often than on a bell curve. The typical redrawn history ended at"
        " about {median:+.1%}. Nine histories in ten ended between about {low:+.1%} and"
        " {high:+.1%}. One in twenty had a worst drop deeper than about {drop_q95:.1%}."
    ),
    caveats=(
        "The model matches the mean, swing and tail weight of this run's returns and draws every"
        " bar independently, so it cannot show losing streaks. It assumes the future looks like"
        " this history. The numbers move a little with the seed: on 7,500 bars the high end moved"
        " about 3% of its value between seeds, so read them as approximate.",
    ),
    seeded=True,
    legacy_seed=semantic_seed(7, "monte_carlo.student_t"),
    time_safety="hindsight",
    poison_test=TESTS + "test_future_input_rejected",
    reference=TESTS + "test_agrees_with_classical_command",
    compute=student_t_paths,
)
