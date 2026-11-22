"""Time-series diagnostics (family J of the toolbox plan): checks on the run's return series."""

from __future__ import annotations

from alpha_cli.toolbox.families.timeseries_a import CHECKS as CHECKS_A
from alpha_cli.toolbox.families.timeseries_b import CHECKS as CHECKS_B
from alpha_cli.toolbox.families.timeseries_c import CHECKS as CHECKS_C
from alpha_cli.toolbox.families.timeseries_d import CHECKS as CHECKS_D

CHECKS = (*CHECKS_A, *CHECKS_B, *CHECKS_C, *CHECKS_D)
