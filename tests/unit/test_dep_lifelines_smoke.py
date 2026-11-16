"""lifelines smoke test: Aalen-Johansen competing-risks estimate on a hand-checkable example.

Five subjects (time, event): (1, 1) (2, 2) (3, 1) (4, censored) (5, 2).
Overall survival S falls 1 -> 0.8 (t=1) -> 0.6 (t=2) -> 0.4 (t=3), is unchanged by the
censoring at t=4, and falls to 0 at t=5. Cumulative incidence of event 1 is
0.2 at t=1, 0.2 at t=2, 0.2 + 0.6/3 = 0.4 at t=3, 0.4 after. Cumulative incidence of
event 2 is 0.2 at t=2 (0.8 * 1/4) and 0.2 + 0.4 * 1/1 = 0.6 at t=5.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from lifelines import AalenJohansenFitter  # type: ignore[import-untyped]


def _fit(event_of_interest: int) -> pd.Series:
    fitter = AalenJohansenFitter(calculate_variance=False, seed=0)
    fitter.fit(
        durations=pd.Series([1.0, 2.0, 3.0, 4.0, 5.0]),
        event_observed=pd.Series([1, 2, 1, 0, 2]),
        event_of_interest=event_of_interest,
    )
    series: pd.Series = fitter.cumulative_density_[f"CIF_{event_of_interest}"]
    return series


def test_aalen_johansen_matches_hand_computed_cumulative_incidence() -> None:
    cif1 = _fit(1)
    cif2 = _fit(2)
    assert np.allclose(cif1.loc[[1.0, 2.0, 3.0, 4.0, 5.0]].to_numpy(), [0.2, 0.2, 0.4, 0.4, 0.4])
    assert np.allclose(cif2.loc[[1.0, 2.0, 3.0, 4.0, 5.0]].to_numpy(), [0.0, 0.2, 0.2, 0.2, 0.6])
