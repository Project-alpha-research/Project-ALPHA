"""Cost and execution realism checks: one tuple of readings for the registry."""

from alpha_cli.toolbox.families import (
    cost_realism_a,
    cost_realism_b,
    cost_realism_c,
    cost_realism_d,
    cost_realism_e,
    cost_realism_f,
)

CHECKS = (
    *cost_realism_a.CHECKS,
    *cost_realism_b.CHECKS,
    *cost_realism_c.CHECKS,
    *cost_realism_d.CHECKS,
    *cost_realism_e.CHECKS,
    *cost_realism_f.CHECKS,
)
