"""One explicit catalogue. Legacy names are read only at the storage boundary."""

from alpha_cli.spine.errors import SpineError
from alpha_cli.toolbox.contract import ToolSpec
from alpha_cli.toolbox.families.costs import BREAK_EVEN
from alpha_cli.toolbox.families.market import ATTRIBUTION, CHANGEPOINTS, VOL_REGIMES
from alpha_cli.toolbox.families.overfit import DEFLATED_SHARPE
from alpha_cli.toolbox.families.performance import CONCENTRATION, DOWNSIDE_RATIOS, SIDE_CONTRIBUTION
from alpha_cli.toolbox.families.resampling import (
    BLOCK_PATHS,
    DRAWDOWN_DISTRIBUTION,
    RETURN_INTERVAL,
    SHARPE_INTERVAL,
)
from alpha_cli.toolbox.families.robustness import START_END_DATES
from alpha_cli.toolbox.families.trades import DEPENDENCE

SPECS = (
    ATTRIBUTION,
    VOL_REGIMES,
    CHANGEPOINTS,
    DOWNSIDE_RATIOS,
    START_END_DATES,
    SIDE_CONTRIBUTION,
    CONCENTRATION,
    BREAK_EVEN,
    SHARPE_INTERVAL,
    RETURN_INTERVAL,
    DRAWDOWN_DISTRIBUTION,
    DEPENDENCE,
    DEFLATED_SHARPE,
    BLOCK_PATHS,
)
ALIASES = {
    "attribution": ATTRIBUTION.id,
    "regimes": VOL_REGIMES.id,
    "changepoints": CHANGEPOINTS.id,
}
METRIC_OUTPUTS = {
    metric: (spec, output)
    for spec in SPECS
    for output in spec.outputs
    for metric in (f"{spec.id}.{output.key}", output.legacy_metric)
    if metric
}


def get(tool_id: str) -> ToolSpec:
    for spec in SPECS:
        if spec.id == tool_id:
            return spec
    raise SpineError(
        "UNKNOWN_TOOL",
        f"Unknown tool {tool_id!r}.",
        "Run alpha tool list.",
        [spec.id for spec in SPECS],
    )
