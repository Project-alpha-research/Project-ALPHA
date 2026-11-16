"""Holm adjustment for one immutable, preregistered secondary hypothesis family.

The adjusted p-values are computed by ``statsmodels.stats.multitest.multipletests`` with
``method="holm"``. They are bit-for-bit the values the earlier hand-written loop gave, which
``tests/unit/test_stats_library_parity.py`` keeps frozen. The rejection rule stays ALPHA's:
adjusted p-value ``<=`` the family's alpha. This module keeps the frozen family, its contract
hash and the fail-loud input checks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from alpha_core import DataError
from alpha_research._canonical import canonical_sha256


@dataclass(frozen=True, slots=True)
class SecondaryHypothesis:
    hypothesis_id: str
    p_value: float

    def __post_init__(self) -> None:
        if not isinstance(self.hypothesis_id, str) or not self.hypothesis_id.strip():
            raise DataError("SecondaryHypothesis.hypothesis_id must be non-empty")
        if not math.isfinite(self.p_value) or not 0.0 <= self.p_value <= 1.0:
            raise DataError("SecondaryHypothesis.p_value must be finite in [0, 1]")

    def to_dict(self) -> dict[str, float | str]:
        return {"hypothesis_id": self.hypothesis_id, "p_value": self.p_value}


@dataclass(frozen=True, slots=True)
class FrozenSecondaryFamily:
    family_id: str
    hypotheses: tuple[SecondaryHypothesis, ...]
    alpha: float = 0.05

    def __post_init__(self) -> None:
        if not isinstance(self.family_id, str) or not self.family_id.strip():
            raise DataError("FrozenSecondaryFamily.family_id must be non-empty")
        if not isinstance(self.hypotheses, tuple) or not self.hypotheses:
            raise DataError("FrozenSecondaryFamily.hypotheses must be a non-empty tuple")
        ids = [item.hypothesis_id for item in self.hypotheses]
        if len(ids) != len(set(ids)):
            raise DataError("secondary hypothesis IDs must be unique within the frozen family")
        if not math.isfinite(self.alpha) or not 0.0 < self.alpha < 0.5:
            raise DataError("FrozenSecondaryFamily.alpha must be finite in (0, 0.5)")

    def to_dict(self) -> dict[str, object]:
        return {
            "alpha": self.alpha,
            "family_id": self.family_id,
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "method": "holm",
            "schema_version": 1,
        }

    @property
    def contract_hash(self) -> str:
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class HolmAdjustedHypothesis:
    hypothesis_id: str
    p_value: float
    adjusted_p_value: float
    rejected: bool


def holm_adjust_secondary_family(
    family: FrozenSecondaryFamily,
) -> tuple[HolmAdjustedHypothesis, ...]:
    """Return Holm-adjusted p-values in the family's original registered order."""
    # Imported here so that importing alpha_research does not load statsmodels.
    from statsmodels.stats.multitest import multipletests

    raw = np.array([item.p_value for item in family.hypotheses], dtype=np.float64)
    adjusted = multipletests(raw, alpha=family.alpha, method="holm")[1]
    return tuple(
        HolmAdjustedHypothesis(
            hypothesis_id=item.hypothesis_id,
            p_value=item.p_value,
            adjusted_p_value=float(value),
            rejected=float(value) <= family.alpha,
        )
        for item, value in zip(family.hypotheses, adjusted, strict=True)
    )
