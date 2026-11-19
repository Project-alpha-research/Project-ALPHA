"""The closed list of situations a check can be found by. Defined here and nowhere else."""

from typing import Literal

Situation = Literal[
    "looks-too-good",
    "many-tries",
    "drawdown",
    "return-range",
    "works-only-sometimes",
    "calm-or-turbulent",
    "behaviour-change",
    "few-trades",
    "lucky-trades",
    "trade-streaks",
    "long-vs-short",
    "cost-fragile",
    "just-the-market",
    "risk-adjusted",
    "out-of-sample",
    "data-doubt",
]

# Tag -> the plain words an owner would use. Wording follows research/tools/README.md.
SITUATIONS: dict[Situation, str] = {
    "looks-too-good": "The result looks too good",
    "many-tries": "The result looks too good after many tries",
    "drawdown": "Big drawdown, or how deep the drop could get",
    "return-range": "How wide is the return range",
    "works-only-sometimes": "Works in some years or windows only",
    "calm-or-turbulent": "Does it earn in calm or turbulent markets",
    "behaviour-change": "When did the behaviour change",
    "few-trades": "Few trades",
    "lucky-trades": "Profit from a handful of trades",
    "trade-streaks": "Wins and losses cluster or alternate",
    "long-vs-short": "Which side earned the profit",
    "cost-fragile": "Fragile to costs",
    "just-the-market": "Is this just the market going up",
    "risk-adjusted": "Return compared with the risk taken",
    "out-of-sample": "Does it hold up out of sample",
    "data-doubt": "Would a slightly different data feed change the answer",
}
