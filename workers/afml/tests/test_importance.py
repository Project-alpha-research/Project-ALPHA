"""Checks for wave 1 item 5: MDI, MDA and SFI on leak-checked purged folds."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from shared_fixtures import SEED
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
    # shuffle=False keeps the column order; the rows still come grouped by class, so shuffle them
    # (fixed seed) or every fold tests one class only (review finding).
    order = np.random.default_rng(SEED).permutation(600)
    x, y = x[order], y[order]
    starts = np.arange(600)
    return pd.DataFrame(x, columns=INFORMATIVE + NOISE), y, starts, np.minimum(starts + 3, 599)


@pytest.fixture(scope="module")
def result(synthetic: tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]) -> object:
    x, y, starts, ends = synthetic
    return importance(x, y, starts, ends, n_groups=5, embargo=5, seed=1, n_trees=100)


def test_informative_columns_outrank_noise(result: object) -> None:
    mdi, mda, sfi = (getattr(result, name)["mean"] for name in ("mdi", "mda", "sfi"))
    assert mdi[INFORMATIVE].min() > mdi[NOISE].max()  # MDI separates them column by column
    assert mda[INFORMATIVE].mean() > mda[NOISE].mean() + 0.01  # out of sample, with a margin
    assert sfi[INFORMATIVE].mean() > sfi[NOISE].mean() + 0.05
    assert abs(sfi[NOISE].mean() - 0.5) < 0.05  # noise alone scores about chance
    assert result.baseline.min() > 0.6  # every fold sees both classes
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


def test_a_constant_factor_is_refused_by_name(
    synthetic: tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    x, y, starts, ends = synthetic
    with pytest.raises(ContractError, match="flat"):
        importance(x.assign(flat=1.0), y, starts, ends, n_trees=20)
