"""Parity and leak checks for wave 1 item 3: purged k-fold and combinatorial purged CV."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest
from shared_fixtures import SEED

from alpha_afml_worker.contract import ContractError
from alpha_afml_worker.cv import groups, leaks, purged_splits, reference_train


def dense(n: int, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    starts = np.arange(n)
    return starts, np.minimum(starts + horizon, n - 1)


def sparse(seed: int = SEED) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    starts = np.sort(rng.choice(600, 120, replace=False))
    return starts, starts + rng.integers(0, 15, starts.size)


def test_leak_checker_catches_a_plain_unpurged_kfold() -> None:
    starts, ends = dense(60, 5)
    test = np.arange(20, 30)
    plain_train = np.setdiff1d(np.arange(60), test)  # sklearn KFold: no purge, no embargo
    found = leaks(starts, ends, plain_train, test, embargo=2)
    assert any("overlaps" in f for f in found) and any("embargo" in f for f in found)
    assert leaks(starts, ends, reference_train(starts, ends, test, 2), test, 2) == []


def test_mlfinlab_issue_295_training_events_ending_inside_the_test_window_are_purged() -> None:
    # Training events start before the test block and end inside it: they must all go.
    starts = np.arange(0, 40)
    ends = starts.copy()
    ends[15:20] = 22  # rows 15..19 end inside the test block that starts at row 20
    result = purged_splits(starts, ends, n_groups=4, n_test_groups=1)
    train, test = result.splits[2]
    assert test.tolist() == list(range(20, 30))
    assert not set(range(15, 20)) & set(train.tolist())


@pytest.mark.parametrize(("n", "horizon", "embargo"), [(120, 4, 3), (240, 9, 0), (120, 0, 2)])
@pytest.mark.parametrize("k", [1, 2, 3])
def test_dense_labels_all_three_agree_exactly(n: int, horizon: int, embargo: int, k: int) -> None:
    starts, ends = dense(n, horizon)
    result = purged_splits(starts, ends, n_groups=6, n_test_groups=k, embargo=embargo)
    assert result.extra_dropped_risklabai == 0 and result.extra_dropped_quantowl == 0
    assert len(result.splits) == math.comb(6, k)
    for (train, test), combo in zip(result.splits, result.test_groups, strict=True):
        assert np.array_equal(train, reference_train(starts, ends, test, embargo)), combo


def test_sparse_events_libraries_only_ever_drop_more() -> None:
    starts, ends = sparse()
    result = purged_splits(starts, ends, n_groups=5, n_test_groups=2, embargo=2)
    # Each split already passed the leak checker and the subset rule inside purged_splits.
    assert result.extra_dropped_risklabai > 0 and result.extra_dropped_quantowl is not None
    assert result.extra_dropped_quantowl > 0


@pytest.mark.parametrize(("n_groups", "k"), [(6, 2), (8, 3), (5, 1), (10, 2)])
def test_split_and_path_counts(n_groups: int, k: int) -> None:
    starts, ends = dense(n_groups * 20, 3)
    result = purged_splits(starts, ends, n_groups=n_groups, n_test_groups=k)
    assert len(result.splits) == math.comb(n_groups, k)
    assert result.n_paths == math.comb(n_groups, k) * k // n_groups
    combos = list(itertools.combinations(range(n_groups), k))
    for p in range(result.n_paths):  # every path tests each group exactly once
        assert all(g in combos[result.path_folds[g, p]] for g in range(n_groups))


def test_one_day_labels_equal_alpha_cpcv_rule() -> None:
    # ALPHA's cpcv.py, restated: groups by array_split; train = not test, minus `embargo`
    # rows after each test group. With one-day labels purge removes nothing more.
    n, n_groups, k, embargo = 103, 5, 2, 2
    starts = np.arange(n)
    result = purged_splits(starts, starts.copy(), n_groups=n_groups, n_test_groups=k,
                           embargo=embargo)  # fmt: skip
    parts = groups(n, n_groups)
    for (train, test), combo in zip(result.splits, result.test_groups, strict=True):
        dropped = set(test.tolist())
        for g in combo:
            end = int(parts[g][-1]) + 1
            dropped.update(range(end, min(end + embargo, n)))
        assert train.tolist() == [i for i in range(n) if i not in dropped]
    assert result.extra_dropped_quantowl is None  # 103 % 5 != 0: quantowl groups differently


def test_bad_input_fails_loud() -> None:
    with pytest.raises(ContractError):
        purged_splits(np.array([0, 0, 1]), np.array([0, 1, 2]), n_groups=2)
    with pytest.raises(ContractError):
        purged_splits(np.array([0, 1, 2]), np.array([0, 0, 2]), n_groups=2)
    with pytest.raises(ContractError):
        purged_splits(*dense(20, 1), n_groups=4, n_test_groups=4)


def test_kfold_with_labels_of_varying_length_does_not_leak() -> None:
    """Review finding: RiskLabAI's PurgedKFold ends the test window at the LAST test label."""
    result = purged_splits(np.arange(8), np.array([0, 1, 5, 3, 4, 5, 6, 7]), 2, 1, 0)
    for train, test in result.splits:
        assert leaks(np.arange(8), np.array([0, 1, 5, 3, 4, 5, 6, 7]), train, test, 0) == []
    rng = np.random.default_rng(SEED)
    starts = np.arange(500)
    ends = starts + rng.integers(1, 10, 500)
    for k in (1, 2):
        purged_splits(starts, ends, n_groups=5, n_test_groups=k, embargo=2)


def test_empty_training_set_is_refused() -> None:
    with pytest.raises(ContractError, match="training rows"):
        purged_splits(np.arange(9), np.full(9, 8), n_groups=4, n_test_groups=2)


@pytest.mark.parametrize(
    ("starts", "ends"),
    [
        (np.array([0, 1, 2]), np.array([0.9, 1.9, 2.9])),
        (np.array([0.0, 1.0, 2.0]), np.array([0, 1, 2])),
    ],
)
def test_non_integer_spans_are_refused(starts: np.ndarray, ends: np.ndarray) -> None:
    with pytest.raises(ContractError, match="integer"):
        purged_splits(starts, ends, n_groups=2)


def test_embargo_as_long_as_the_sample_is_refused() -> None:
    with pytest.raises(ContractError, match="embargo"):
        purged_splits(*dense(20, 1), n_groups=4, embargo=20)
