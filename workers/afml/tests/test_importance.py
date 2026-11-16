"""Checks for wave 1 item 5: MDI, MDA and SFI on leak-checked purged folds."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.datasets import make_classification

from alpha_afml_worker.contract import ContractError
from alpha_afml_worker.cv import leaks
from alpha_afml_worker.importance import CheckedSplits, importance

INFORMATIVE = [f"I{i}" for i in range(4)] + [f"R{i}" for i in range(4)]
NOISE = [f"N{i}" for i in range(4)]


@pytest.fixture(scope="module")
def synthetic() -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    """The book's test design (AFML 8.6): informative, redundant and noise columns."""
    x, y = make_classification(
        n_samples=600, n_features=12, n_informative=4, n_redundant=4, n_repeated=0,
        shuffle=False, random_state=0,
    )  # fmt: skip
    starts = np.arange(600)
    return pd.DataFrame(x, columns=INFORMATIVE + NOISE), y, starts, np.minimum(starts + 3, 599)


@pytest.fixture(scope="module")
def result(synthetic: tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]) -> object:
    x, y, starts, ends = synthetic
    return importance(x, y, starts, ends, n_groups=5, embargo=5, seed=1, n_trees=100)


def test_informative_columns_outrank_noise(result: object) -> None:
    mdi, mda, sfi = (getattr(result, name)["mean"] for name in ("mdi", "mda", "sfi"))
    assert mdi[INFORMATIVE].min() > mdi[NOISE].max()  # MDI separates them column by column
    assert mda[INFORMATIVE].mean() > mda[NOISE].mean()  # out of sample: on average
    assert sfi[INFORMATIVE].mean() > sfi[NOISE].mean()
    assert abs(float(mdi.sum()) - 1.0) < 1e-12


def test_folds_are_the_leak_checked_purged_ones(
    synthetic: tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray], result: object
) -> None:
    from alpha_afml_worker.cv import purged_splits

    _, _, starts, ends = synthetic
    splits = purged_splits(starts, ends, 5, 1, 5).splits
    for train, test in CheckedSplits(splits).split():
        assert leaks(starts, ends, train, test, 5) == []
    assert result.folds == 5 and result.baseline.size == 5


def test_bad_input_fails_loud(
    synthetic: tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    x, y, starts, ends = synthetic
    with pytest.raises(ContractError):
        importance(x.assign(I0=np.nan), y, starts, ends)
    with pytest.raises(ContractError):
        importance(x, np.zeros_like(y), starts, ends)
