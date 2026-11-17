"""Wave 1 item 5: feature importance (MDI, MDA, SFI) on purged folds, as a report.

The folds are :func:`alpha_afml_worker.cv.purged_splits` (RiskLabAI's, each passed ALPHA's
brute-force leak checker); quantowl's ``mda`` and ``sfi`` run on exactly those folds. RiskLabAI's
own MDA and SFI are never used: they shuffle an unpurged KFold (its open issue #1). MDI is
in-sample by construction; RiskLabAI and quantowl must agree on its means to 1e-10.

This is a report for judging candidate factors (RD-Agent's among them). It decides nothing: no
gate reads it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from quantowl import importance as qi
from RiskLabAI.features.feature_importance.feature_importance_mdi import FeatureImportanceMDI
from sklearn.ensemble import RandomForestClassifier

from alpha_afml_worker.contract import AgreementError, ContractError
from alpha_afml_worker.cv import Split, purged_splits

TOLERANCE = 1e-10


class CheckedSplits:
    """A fixed list of leak-checked folds in the sklearn splitter shape quantowl expects."""

    def __init__(self, splits: list[Split]) -> None:
        self._splits = splits

    def split(self, x: Any = None, y: Any = None, groups: Any = None) -> Iterator[Split]:
        return iter(self._splits)

    def get_n_splits(self, x: Any = None, y: Any = None, groups: Any = None) -> int:
        return len(self._splits)


def forest(seed: int, n_trees: int = 200) -> RandomForestClassifier:
    """The book's MDI forest: one feature per split, balanced classes, fixed seed, one thread."""
    return RandomForestClassifier(
        n_estimators=n_trees,
        max_features=1,
        min_weight_fraction_leaf=0.05,
        class_weight="balanced_subsample",
        random_state=seed,
        n_jobs=1,
    )


@dataclass(frozen=True)
class Importance:
    """Per-feature tables (mean, standard error) and the out-of-sample baseline per fold."""

    mdi: pd.DataFrame
    mda: pd.DataFrame
    sfi: pd.DataFrame
    baseline: np.ndarray
    folds: int
    extra_dropped: int


def importance(
    features: pd.DataFrame,
    labels: np.ndarray,
    starts: np.ndarray,
    ends: np.ndarray,
    weights: np.ndarray | None = None,
    n_groups: int = 5,
    embargo: int = 0,
    seed: int = 0,
    n_trees: int = 200,
) -> Importance:
    """MDI, MDA and SFI of ``features`` for binary ``labels`` whose spans are ``starts..ends``."""
    x = features.reset_index(drop=True).astype(np.float64)
    y = np.asarray(labels)
    if x.shape[0] != y.size or y.size != np.asarray(starts).size or x.shape[1] < 1:
        raise ContractError("features, labels and spans must have one row per label")
    if not bool(np.all(np.isfinite(x.to_numpy()))):
        raise ContractError("features must be finite (fill or drop missing factor values first)")
    flat = [str(c) for c in x.columns if float(x[c].std(ddof=0)) == 0.0]
    if flat:
        raise ContractError(f"factors with one value carry no information: {', '.join(flat)}")
    if set(np.unique(y).tolist()) - {0, 1} or np.unique(y).size < 2:
        raise ContractError("labels must be 0/1 with both classes present")
    w = None if weights is None else np.asarray(weights, dtype=np.float64)
    folds = purged_splits(np.asarray(starts), np.asarray(ends), n_groups, 1, embargo)
    cv = CheckedSplits(folds.splits)

    strategy = FeatureImportanceMDI(forest(seed, n_trees))
    r_mdi = strategy.compute(x, pd.Series(y), sample_weight=w)
    # quantowl gets the very trees RiskLabAI fitted, so the two summaries must agree.
    trees = np.vstack([tree.feature_importances_ for tree in strategy.classifier.estimators_])
    q_mdi = qi.mdi_from_matrix(trees, names=list(x.columns))
    q_mean, r_mean = q_mdi["mean"].to_numpy(), r_mdi["Mean"].to_numpy()
    if not np.array_equal(np.isnan(q_mean), np.isnan(r_mean)):
        raise AgreementError("MDI: the libraries disagree on which factors no tree used")
    gap = float(np.nanmax(np.abs(q_mean - r_mean))) if np.isfinite(q_mean).any() else 0.0
    if gap > TOLERANCE:
        raise AgreementError(f"MDI means differ by {gap:.3e}")

    def factory() -> RandomForestClassifier:
        return forest(seed, n_trees)

    baseline, mda = qi.mda(factory, x, y, cv, sample_weight=w, seed=seed)
    _, sfi = qi.sfi(factory, x, y, cv, sample_weight=w)
    return Importance(q_mdi, mda, sfi, baseline, len(folds.splits), folds.extra_dropped_risklabai)
