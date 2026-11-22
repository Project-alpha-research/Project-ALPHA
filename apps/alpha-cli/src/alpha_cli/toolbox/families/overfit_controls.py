"""Overfitting and multiple-testing controls on a finished run: every check in one tuple."""

from alpha_cli.toolbox.families import overfit_controls_a, overfit_controls_b, overfit_controls_c

CHECKS = (*overfit_controls_a.CHECKS, *overfit_controls_b.CHECKS, *overfit_controls_c.CHECKS)
