"""Planted answers added after adversarial review: units, signs, number words, precision, flags."""

from alpha_cli.spine.honesty_scenarios import BASE_SCENARIOS, H1, Scenario

_DRAWDOWN = "The worst full-sample drawdown was -34.4% [a1a1a1a1:full_sample_max_drawdown]."
_SHARPE = "0.81 [a1a1a1a1:oos_sharpe]"
MORE = (
    Scenario(
        "H6",
        "drawdown written as a loss of a magnitude",
        True,
        H1.replace(_DRAWDOWN, _DRAWDOWN.replace("was -34.4%", "was a loss of 34.4%")),
        frozenset(),
    ),
    Scenario(
        "H7",
        "en dash as a minus sign",
        True,
        H1.replace("-34.4%", "–34.4%"),
        frozenset(),
    ),
    Scenario(
        "H8",
        "sentences that only look like a flag denial",
        True,
        H1 + "No flag was missed. Two assets were tested.\n",
        frozenset(),
    ),
    Scenario(
        "D14",
        "percent sign on a ratio",
        False,
        H1.replace(_SHARPE, "81% [a1a1a1a1:oos_sharpe]"),
        frozenset({"UNIT_MISMATCH"}),
    ),
    Scenario(
        "D15",
        "drawdown sign dropped without a magnitude word",
        False,
        H1.replace("was -34.4%", "was 34.4%"),
        frozenset({"VALUE_MISMATCH"}),
    ),
    Scenario(
        "D16",
        "invented number written in words",
        False,
        H1 + "Over the last year the Sharpe was one point eight.\n",
        frozenset({"UNTAGGED_NUMBER"}),
    ),
    Scenario(
        "D17",
        "ratio rounded to a whole number",
        False,
        H1.replace(_SHARPE, "1 [a1a1a1a1:oos_sharpe]"),
        frozenset({"PRECISION_TOO_LOW"}),
    ),
)
SCENARIOS = BASE_SCENARIOS + MORE
