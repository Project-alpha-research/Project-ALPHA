"""Two more Monte Carlo families as checks: calm-and-stormy regimes and Student-t fat tails.

Each entry calls the public path function that ``alpha monte-carlo classical`` calls for its
family, with the command's own defaults and seed names. ``alpha_validation`` computes the numbers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alpha_cli._seeds import semantic_seed
from alpha_cli.toolbox.contract import Output, Param, Result, ToolSpec

if TYPE_CHECKING:
    import numpy as np
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray

TESTS = "tests/unit/test_toolbox_montecarlo_checks.py::"
BASIS = "After-cost bar returns from the stored walk-forward equity curve."
KEYS = ("low", "median", "high", "drop_q95")
# Bound the paths-by-bars matrices that path_metric_arrays allocates, even on long histories.
PATH_CHUNK_CELLS = 4_000_000
# The classical command's smallest state share before it warns that a state rests on few bars.
MIN_STATE_SHARE = 0.10


def _unavailable(reason: str, seed: int) -> Result:
    return Result(
        dict.fromkeys(KEYS), dict.fromkeys(KEYS, reason), details={"seed": seed}, basis=BASIS
    )


def _chunk_rows(n_bars: int) -> int:
    return max(1, PATH_CHUNK_CELLS // n_bars)


def _result(terminal: FloatArray, drawdown: FloatArray, seed: int, **details: Any) -> Result:
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
        details={"seed": seed, **details},
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


def _reading(model: str) -> str:
    return (
        f"Redrawing this run's history with a model that {model} gave a typical final return of"
        " {median:+.1%}. Nine histories in ten ended between {low:+.1%} and {high:+.1%}."
        " One in twenty had a worst drop deeper than {drop_q95:.1%}."
    )


def _states(returns: FloatArray, window: int) -> tuple[FloatArray, np.ndarray]:
    """Label each bar calm or stormy with the command's own causal labeller.

    The classical command labels a validation run's returns from the market's closes. A stored
    run or factor replay holds no closes, so the scored equity line stands in for them: the swing
    of the rule's own recent returns decides the label, and only returns that have a full window of
    earlier returns are labelled. The boundary is frozen from the first half of those bars.
    """
    from datetime import UTC, datetime, timedelta

    import numpy as np

    from alpha_cli.monte_carlo_cmds import _causal_regime_states
    from alpha_core import Bar

    closes = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    start = datetime(2000, 1, 1, tzinfo=UTC)
    bars = [
        Bar(
            symbol="scored",
            ts=start + timedelta(days=i),
            open=float(c),
            high=float(c),
            low=float(c),
            close=float(c),
            volume=0.0,
        )
        for i, c in enumerate(closes)
    ]
    labelled = len(returns) - window
    states, _, _ = _causal_regime_states(
        bars,
        [bar.ts for bar in bars[window + 1 :]],
        train_size=window + 1 + labelled // 2,
        window=window,
    )
    return returns[window:], states


def regime_paths(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    from alpha_core import DataError
    from alpha_validation.path_montecarlo import path_metric_arrays, regime_switching_return_paths

    returns = inputs.stored.scored_returns()
    window = params["regime_window"]
    if params["n_paths"] < 1 or window < 2:
        raise DataError("n_paths must be >= 1 and regime_window must be >= 2")
    if len(returns) < window + 2:
        return _unavailable(
            f"The calm-and-stormy model needs at least {window + 2} scored bar returns.",
            inputs.seed,
        )
    try:
        scored, states = _states(returns, window)
        regime = regime_switching_return_paths(
            scored,
            states,
            n_paths=params["n_paths"],
            min_state_observations=params["min_state_observations"],
            min_state_transitions=params["min_state_transitions"],
            seed=inputs.seed,
        )
    except DataError as exc:
        return _unavailable(f"The calm-and-stormy model could not be fitted: {exc}", inputs.seed)
    terminal = np.empty(params["n_paths"])
    drawdown = np.empty(params["n_paths"])
    step = _chunk_rows(scored.size)
    for start in range(0, params["n_paths"], step):
        stop = min(start + step, params["n_paths"])
        metrics = path_metric_arrays(regime.paths[start:stop])
        terminal[start:stop], drawdown[start:stop] = (
            metrics.terminal_return,
            metrics.maximum_drawdown,
        )
    calm, stormy = regime.state_observations
    thin = min(calm, stormy) / scored.size < MIN_STATE_SHARE
    return _result(
        terminal,
        drawdown,
        inputs.seed,
        calm_bars=calm,
        stormy_bars=stormy,
        thin_state=thin,
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


REGIME_PATHS = ToolSpec(
    id="resampling.regime_paths",
    family="resampling",
    kind="test",
    look="test",
    question=(
        "What range of final return and worst drop do histories give that keep calm and stormy"
        " periods apart?"
    ),
    needs=("stored_equity",),
    params=(
        Param("n_paths", int, 2000, None, "Number of redrawn histories."),
        Param("regime_window", int, 63, None, "Earlier bars whose return swing labels a bar."),
        Param("min_state_observations", int, 20, None, "Fewest bars each state must hold."),
        Param("min_state_transitions", int, 10, None, "Fewest moves out of each state."),
    ),
    outputs=_outputs(),
    reading=_reading("keeps calm and stormy periods apart"),
    caveats=(
        "Calm and stormy bars are labelled from the swing of this run's own recent returns, with"
        " the boundary frozen from the first half of the labelled bars. The classical command"
        " labels them from the market's price swings instead, so its numbers can differ. A state"
        " that holds under 10% of the bars rests on few bars. It assumes the future looks like"
        " this history.",
    ),
    seeded=True,
    legacy_seed=semantic_seed(7, "monte_carlo.regime"),
    time_safety="hindsight",
    poison_test=TESTS + "test_future_input_rejected",
    reference=TESTS + "test_agrees_with_classical_command",
    compute=regime_paths,
)

STUDENT_T_PATHS = ToolSpec(
    id="resampling.student_t_paths",
    family="resampling",
    kind="test",
    look="test",
    question="What range of final return and worst drop do fat-tailed histories give?",
    needs=("stored_equity",),
    params=(Param("n_paths", int, 10_000, None, "Number of redrawn histories."),),
    outputs=_outputs(),
    reading=_reading("allows rare large moves"),
    caveats=(
        "The model matches the mean, swing and tail weight of this run's returns and draws every"
        " bar independently, so it cannot show losing streaks. It assumes the future looks like"
        " this history.",
    ),
    seeded=True,
    legacy_seed=semantic_seed(7, "monte_carlo.student_t"),
    time_safety="hindsight",
    poison_test=TESTS + "test_future_input_rejected",
    reference=TESTS + "test_agrees_with_classical_command",
    compute=student_t_paths,
)
