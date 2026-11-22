"""Rule and strategy performance statistics: one tuple of checks for the registry."""

from alpha_cli.toolbox.families import (
    performance_stats_a,
    performance_stats_b,
    performance_stats_c,
    performance_stats_d,
)

CHECKS = (
    *performance_stats_a.CHECKS,
    *performance_stats_b.CHECKS,
    *performance_stats_c.CHECKS,
    *performance_stats_d.CHECKS,
)
