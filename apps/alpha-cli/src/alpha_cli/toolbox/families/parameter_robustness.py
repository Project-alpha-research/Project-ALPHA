"""Parameter and specification robustness: checks that re-run the engine with other settings.

Every re-run is a try in the one trial ledger, counted before its result is shown.
"""

from alpha_cli.toolbox.families.parameter_robustness_a import CHECKS as SETTINGS
from alpha_cli.toolbox.families.parameter_robustness_b import CHECKS as LADDERS
from alpha_cli.toolbox.families.parameter_robustness_c import CHECKS as RANDOM

CHECKS = (*SETTINGS, *LADDERS, *RANDOM)
