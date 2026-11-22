"""Family I of the toolbox: regime and conditional analysis of the scored run."""

from dataclasses import replace

from alpha_cli.toolbox.families.regimes_breaks import CHOW, CUSUM_MEAN, CUSUM_VARIANCE
from alpha_cli.toolbox.families.regimes_calendar import (
    DAY_OF_WEEK,
    HALLOWEEN,
    MONTH_OF_YEAR,
    TURN_OF_MONTH,
)
from alpha_cli.toolbox.families.regimes_market import ASYMMETRIC_BETA, BULL_BEAR, TREND_RANGE
from alpha_cli.toolbox.families.regimes_periods import SUB_PERIOD, YEAR_BY_YEAR
from alpha_cli.toolbox.families.regimes_search import BAI_PERRON, SUP_F
from alpha_cli.toolbox.situations import Situation

_ALL = (
    YEAR_BY_YEAR,
    SUB_PERIOD,
    DAY_OF_WEEK,
    MONTH_OF_YEAR,
    TURN_OF_MONTH,
    HALLOWEEN,
    BULL_BEAR,
    ASYMMETRIC_BETA,
    TREND_RANGE,
    CHOW,
    CUSUM_MEAN,
    CUSUM_VARIANCE,
    SUP_F,
    BAI_PERRON,
)

_ONLY_SOMETIMES: tuple[Situation, ...] = ("works-only-sometimes",)
_CHANGE: tuple[Situation, ...] = ("behaviour-change",)
_FOUND: dict[str, tuple[Situation, ...]] = {
    YEAR_BY_YEAR.id: _ONLY_SOMETIMES,
    SUB_PERIOD.id: _ONLY_SOMETIMES,
    DAY_OF_WEEK.id: _ONLY_SOMETIMES,
    MONTH_OF_YEAR.id: _ONLY_SOMETIMES,
    TURN_OF_MONTH.id: _ONLY_SOMETIMES,
    HALLOWEEN.id: _ONLY_SOMETIMES,
    BULL_BEAR.id: ("just-the-market", "works-only-sometimes"),
    ASYMMETRIC_BETA.id: ("just-the-market",),
    TREND_RANGE.id: _ONLY_SOMETIMES,
    CHOW.id: _CHANGE,
    CUSUM_MEAN.id: _CHANGE,
    CUSUM_VARIANCE.id: _CHANGE,
    SUP_F.id: _CHANGE,
    BAI_PERRON.id: _CHANGE,
}
CHECKS = tuple(replace(check, situations=_FOUND[check.id]) for check in _ALL)
