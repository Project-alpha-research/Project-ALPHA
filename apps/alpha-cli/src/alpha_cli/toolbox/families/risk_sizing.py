"""Risk, sizing and attribution checks on a finished run, as one tuple for the registry."""

from alpha_cli.toolbox.families import (
    risk_sizing_a,
    risk_sizing_b,
    risk_sizing_c,
    risk_sizing_d,
    risk_sizing_e,
    risk_sizing_f,
    risk_sizing_g,
)

CHECKS = (
    *risk_sizing_a.CHECKS,
    *risk_sizing_b.CHECKS,
    *risk_sizing_e.CHECKS,
    *risk_sizing_c.CHECKS,
    *risk_sizing_f.CHECKS,
    *risk_sizing_d.CHECKS,
    *risk_sizing_g.CHECKS,
)
