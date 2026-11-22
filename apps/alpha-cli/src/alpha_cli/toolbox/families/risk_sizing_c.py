"""Sizing checks on closed trades: Kelly, fractional Kelly and optimal f."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from alpha_cli.toolbox.contract import Output, Result
from alpha_cli.toolbox.families.risk_common import (
    PAST,
    TRADE_BASIS,
    check,
    closed_trades,
    too_few_trades,
    unavailable,
)

if TYPE_CHECKING:
    from numpy.random import Generator

    from alpha_cli.toolbox.inputs import Inputs
    from alpha_validation import FloatArray

TESTS = "test_toolbox_risk_sizing_c"
MIN_TRADES = 20
SIZING_CAVEAT = (
    "It treats each closed trade as one independent bet of the same size and ignores trades held"
    " at the same time, costs of leverage and margin limits. " + PAST
)


def growth_optimal(ret: FloatArray) -> float:
    """The stake (in equity per unit return) that maximises mean log growth; 0 without an edge."""
    import numpy as np
    from scipy.optimize import brentq

    if float(ret.mean()) <= 0:
        return 0.0
    upper = (1 - 1e-9) / -float(ret.min())

    def slope(stake: float) -> float:
        return float(np.mean(ret / (1 + stake * ret)))

    if slope(upper) >= 0:
        raise ValueError("Kelly search bound does not bracket the maximum")
    return float(brentq(slope, 0.0, upper, xtol=1e-14, rtol=1e-14))


def _edge_returns(inputs: Inputs, *, need_edge: bool = False) -> tuple[FloatArray | None, str]:
    import numpy as np

    ret = closed_trades(inputs).ret
    if (why := too_few_trades(len(ret), MIN_TRADES)) is not None:
        return None, why
    if not (ret > 0).any() or not (ret < 0).any():
        return None, "Needs at least one winning and one losing trade."
    if need_edge and float(np.mean(ret)) <= 0:
        return None, "The trades show no positive edge, so the Kelly stake is zero."
    return ret, ""


def kelly(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    keys = ("trades", "win_rate", "payoff_ratio", "kelly_simple", "kelly_growth", "growth_at_kelly")
    ret, why = _edge_returns(inputs)
    if ret is None:
        return unavailable(keys, why, TRADE_BASIS)
    wins, losses = ret[ret > 0], ret[ret < 0]
    p = len(wins) / (len(wins) + len(losses))
    b = float(wins.mean() / -losses.mean())
    stake = growth_optimal(ret)
    values: dict[str, Any] = {
        "trades": len(ret),
        "win_rate": p,
        "payoff_ratio": b,
        # Kelly (1956), as given by Thorp (1969): p - q / b when each trade risks the average loss.
        "kelly_simple": p - (1 - p) / b,
        "kelly_growth": stake,
        "growth_at_kelly": float(np.mean(np.log1p(stake * ret))),
    }
    return Result(values, {}, basis=TRADE_BASIS)


def _compounded(ret: FloatArray, stake: float) -> tuple[float, float]:
    import numpy as np

    from alpha_validation.metrics import max_drawdown

    steps = 1 + stake * ret
    growth = float(np.mean(np.log(steps)))
    return growth, max_drawdown(np.r_[1.0, np.cumprod(steps)])


def fractional_kelly(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    keys = (
        "kelly_growth",
        "growth_full",
        "growth_half",
        "growth_quarter",
        "drawdown_full",
        "drawdown_half",
        "drawdown_quarter",
    )
    ret, why = _edge_returns(inputs, need_edge=True)
    if ret is None:
        return unavailable(keys, why, TRADE_BASIS)
    stake = growth_optimal(ret)
    values: dict[str, Any] = {"kelly_growth": stake}
    # Thorp (1969): stake a fraction of Kelly to give up some growth for a shallower drop.
    for name, share in (("full", 1.0), ("half", 0.5), ("quarter", 0.25)):
        values[f"growth_{name}"], values[f"drawdown_{name}"] = _compounded(ret, stake * share)
    return Result(values, {}, basis=TRADE_BASIS)


def optimal_f(inputs: Inputs, params: dict[str, Any], rng: Generator | None) -> Result:
    import numpy as np

    keys = ("optimal_f", "largest_loss", "terminal_multiple", "geometric_hpr")
    ret, why = _edge_returns(inputs)
    if ret is None:
        return unavailable(keys, why, TRADE_BASIS)
    worst = float(-ret.min())
    grid = np.arange(1, 100) / 100
    # Vince (1990): holding period return 1 + f * r / |worst loss|; the grid keeps f below 1.
    logs = np.log1p(np.outer(grid, ret / worst)).sum(axis=1)
    best = int(logs.argmax())
    values: dict[str, Any] = {
        "optimal_f": float(grid[best]),
        "largest_loss": worst,
        "terminal_multiple": float(math.exp(logs[best])),
        "geometric_hpr": float(math.exp(logs[best] / len(ret))),
    }
    return Result(values, {}, basis=TRADE_BASIS)


CHECKS = (
    check(
        "risk.kelly",
        TESTS,
        question="What stake per trade maximised long-run growth on these trades?",
        answers=("What bet size does the Kelly rule give?", "How much should I size each trade?"),
        situations=("risk-adjusted", "few-trades"),
        needs=("run_trades",),
        outputs=(
            Output("trades", "Closed trades", "Count of closed trades read.", "count"),
            Output(
                "win_rate",
                "Win rate",
                "Winning trades over winning plus losing trades.",
                "fraction",
            ),
            Output(
                "payoff_ratio",
                "Payoff ratio",
                "Average winning return over average losing return.",
                "ratio",
            ),
            Output(
                "kelly_simple",
                "Simple Kelly",
                "p - q / b with p the win rate and b the payoff ratio; zero or below means no"
                " edge.",
                "fraction",
            ),
            Output(
                "kelly_growth",
                "Growth-optimal stake",
                "Equity staked per trade that maximised mean log growth on these trades.",
                "ratio",
            ),
            Output(
                "growth_at_kelly",
                "Growth per trade",
                "Mean log growth per trade at that stake.",
                "ratio",
            ),
        ),
        reading=(
            "Over {trades} trades the win rate was {win_rate:.0%} and the payoff ratio"
            " {payoff_ratio:.2f}."
            " The simple Kelly figure is {kelly_simple:.2f}; the stake that maximised growth was"
            " {kelly_growth:.2f} of equity per trade, giving {growth_at_kelly:.4f} log growth"
            " per trade."
        ),
        caveats=(
            SIZING_CAVEAT
            + " Full Kelly is very sensitive to estimation error; it is a reading of the past,"
            " not a stake.",
        ),
        compute=kelly,
    ),
    check(
        "risk.fractional_kelly",
        TESTS,
        question="How much growth and drawdown do full, half and quarter Kelly stakes give?",
        answers=("What if I only stake half of Kelly?",),
        situations=("risk-adjusted", "drawdown"),
        needs=("run_trades",),
        outputs=(
            Output(
                "kelly_growth",
                "Growth-optimal stake",
                "Equity staked per trade at full Kelly.",
                "ratio",
            ),
            *(
                Output(
                    f"growth_{n}",
                    f"Growth at {n} Kelly",
                    f"Mean log growth per trade at {n} Kelly.",
                    "ratio",
                )
                for n in ("full", "half", "quarter")
            ),
            *(
                Output(
                    f"drawdown_{n}",
                    f"Drawdown at {n} Kelly",
                    f"Deepest peak-to-trough drop of the compounded trades at {n} Kelly.",
                    "fraction",
                )
                for n in ("full", "half", "quarter")
            ),
        ),
        reading=(
            "Full Kelly ({kelly_growth:.2f} of equity per trade) grew {growth_full:.4f} per"
            " trade with a"
            " drop of {drawdown_full:.1%}; half Kelly grew {growth_half:.4f} with"
            " {drawdown_half:.1%};"
            " quarter Kelly {growth_quarter:.4f} with {drawdown_quarter:.1%}."
        ),
        caveats=(SIZING_CAVEAT,),
        compute=fractional_kelly,
    ),
    check(
        "risk.optimal_f",
        TESTS,
        question="What fixed fraction of the largest loss would have grown the trades fastest?",
        answers=("What is the optimal f for these trades?",),
        situations=("risk-adjusted", "few-trades"),
        needs=("run_trades",),
        outputs=(
            Output(
                "optimal_f",
                "Optimal f",
                "Fraction (0.01 to 0.99) of the amount that loses the largest loss that grew the"
                " trades fastest.",
                "fraction",
            ),
            Output(
                "largest_loss",
                "Largest loss",
                "Worst single trade return, as a positive fraction.",
                "fraction",
            ),
            Output(
                "terminal_multiple",
                "Terminal wealth multiple",
                "Product of holding period returns at optimal f.",
                "ratio",
            ),
            Output(
                "geometric_hpr",
                "Geometric mean holding return",
                "Terminal multiple per trade.",
                "ratio",
            ),
        ),
        reading=(
            "Optimal f was {optimal_f:.2f} against a largest loss of {largest_loss:.1%}; it"
            " would have"
            " multiplied the stake by {terminal_multiple:.2f} ({geometric_hpr:.4f} per trade)."
        ),
        caveats=(SIZING_CAVEAT + " Optimal f is tied to the single worst trade seen.",),
        compute=optimal_f,
    ),
)
