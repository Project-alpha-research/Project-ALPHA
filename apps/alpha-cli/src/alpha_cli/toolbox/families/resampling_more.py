"""Twelve more resampling and Monte Carlo checks on a finished run (catalogue family E)."""

from alpha_cli.toolbox.families import (
    resampling_more_a,
    resampling_more_b,
    resampling_more_c,
    resampling_more_d,
    resampling_more_e,
)

CHECKS = (
    *resampling_more_a.CHECKS,
    *resampling_more_b.CHECKS,
    *resampling_more_c.CHECKS,
    *resampling_more_d.CHECKS,
    *resampling_more_e.CHECKS,
)
