"""Predeclared tool sets, in execution order."""

SETS = {
    "market-context": ("market.attribution", "market.vol_regimes", "market.changepoints"),
    "rdagent-post-judge": ("resampling.sharpe_interval", "resampling.block_bootstrap_paths"),
}
