"""Known-answer and fixed-seed calibration checks for setup controls."""

from typing import Any

import numpy as np
import pytest

from alpha_cli.spine.setup_controls import (
    RANDOM_DRAWS,
    control_summary,
    eligible_returns,
    sample_dates,
)
from alpha_cli.spine.setup_find import CLUSTER_GAP_BARS


def test_drift_uses_next_open_and_bar_positions() -> None:
    opened = [100.0 * 1.01**i for i in range(40)]
    closed = [p * 1.005 for p in opened]
    positions, returns = eligible_returns(opened, closed, 3, 5, 0.0006)
    assert positions.tolist() == list(range(3, 35))
    assert returns == pytest.approx([1.005 * 1.01**4 - 1 - 0.0006] * 32)


def test_random_dates_spacing_determinism_and_impossible() -> None:
    eligible = np.arange(100)
    left, right = np.random.default_rng(123), np.random.default_rng(123)
    for _ in range(100):
        selected = sample_dates(eligible, 4, left)
        assert selected.tolist() == sample_dates(eligible, 4, right).tolist()
        assert len(set(selected)) == 4
        assert np.all(np.diff(np.sort(selected)) > CLUSTER_GAP_BARS)
    with pytest.raises(ValueError, match="spacing"):
        sample_dates(np.arange(11), 2, left)


def controls(values: Any, chosen: list[float], study_id: str) -> dict[str, Any]:
    result: dict[str, Any] = control_summary(
        {"X": (np.arange(len(values)), np.asarray(values))},
        {"X": chosen},
        study_id,
        tested=True,
    )["pooled"]
    return result


def test_fixed_seed_null_calibration_and_planted_effect() -> None:
    rng = np.random.default_rng(19)
    values = rng.normal(0, 0.01, 300)
    ps = [
        controls(values, [float(values[rng.integers(len(values))])], f"null-{i}")["random_date_p"]
        for i in range(80)
    ]
    # Uniform null p-values: SE(mean) = sqrt(1/12/80) ~= .0323; broad fixed 4-SE band.
    assert 0.37 < float(np.mean(ps)) < 0.63
    assert sum(p <= 0.05 for p in ps) < 13
    chosen = list(range(20, 270, 50))
    values[chosen] = 0.2
    first = controls(values, [0.2] * len(chosen), "planted")
    assert first == controls(values, [0.2] * len(chosen), "planted")
    assert first["random_date_p"] <= 0.01
    assert RANDOM_DRAWS == 2000
    assert first["random_date_p"] >= 1 / (RANDOM_DRAWS + 1)


def test_pool_weights_and_primary_only_probability() -> None:
    eligible = {"A": (np.arange(100), np.ones(100)), "B": (np.arange(100), np.zeros(100))}
    out = control_summary(eligible, {"A": [1.0], "B": [0.0, 0.0]}, "weights", tested=False)
    assert out["pooled"]["drift_mean"] == pytest.approx(1 / 3)
    assert out["pooled"]["random_date_50"] == pytest.approx(1 / 3)
    assert out["pooled"]["random_date_p"] is None
    assert out["pooled"]["reasons"]["random_date_p"]
    assert all(a["random_date_p"] is None for a in out["assets"].values())


@pytest.mark.parametrize(
    "count,p,excess,labels,outcome,prefix",
    [
        (29, 0.001, 0.02, [], "inconclusive", "Too few"),
        (30, 0.05, 0.02, [], "supported (exploratory, not confirmed)", "After this"),
        (30, 0.05, 0.02, ["halves-disagree"], "not supported", "After this"),
        (30, 0.2, 0.02, [], "not supported", "After this"),
        (30, 0.01, -0.01, [], "not supported", "After this"),
    ],
)
def test_reading_order(
    count: int, p: float, excess: float, labels: list[str], outcome: str, prefix: str
) -> None:
    from alpha_cli.spine.setup_controls import reading

    sentence, status = reading(
        dict(occurrences=count, mean=0.03, drift_mean=0.01, random_date_p=p, excess=excess),
        5,
        labels,
    )
    assert status == outcome and sentence.startswith(prefix)
    assert not any(word in sentence for word in ("edge", "profitable", "works", "signal"))
    if outcome.startswith("supported"):
        assert "not checked on reserved data" in sentence
    if outcome == "not supported":
        assert "No evidence the setup adds anything here." in sentence


def test_labels_and_chronological_halves() -> None:
    from types import SimpleNamespace

    from alpha_cli.spine.setup_controls import horizon_summary, study_labels

    rows = [
        dict(asset="X", entry_ts=i, candidate_id=i, net_return=v, complete=v is not None)
        for i, v in [(60, -0.2), (1, 0.1), (5, 0.1), (80, None)]
    ]
    report = horizon_summary(
        rows,
        {"X": (np.arange(100), np.linspace(-0.2, 0.2, 100))},
        {"X": list(range(1, 101))},
        "halves",
        tested=True,
    )
    primary = report["pooled"]
    assert primary["stability"]["first"]["mean"] == pytest.approx(0.1)
    assert primary["stability"]["second"]["mean"] == pytest.approx(-0.2)
    assert primary["stability"]["second"]["incomplete"] == 1
    assert primary["stability"]["first"]["random_date_p"] is None
    labels = study_labels(
        {
            "labels": [
                "daily-only",
                "dev-machine-data",
                "source-defaulted",
                "short-history",
                "outcomes-not-viewed",
            ]
        },
        primary,
        rows,
        {"X": [SimpleNamespace(ts=i) for i in range(100)]},
        20,
    )
    assert set(labels) == {
        "exploratory",
        "daily-only",
        "dev-machine-data",
        "source-defaulted",
        "short-history",
        "too-few-occurrences",
        "single-asset",
        "halves-disagree",
        "overlapping-outcomes",
    }


def test_dense_spaced_dates_are_exact_uniform_and_never_rejected() -> None:
    # 100 spaced dates in 2,000 bars: rejection sampling almost never accepts such a set.
    rng = np.random.default_rng(5)
    selected = sample_dates(np.arange(500, 2500), 100, rng)
    assert len(selected) == 100 and selected.min() >= 500 and selected.max() < 2500
    assert np.all(np.diff(selected) > CLUSTER_GAP_BARS)
    # Every spaced pair in 0..24 must be equally likely (uniform over spaced subsets).
    pairs = [(a, b) for a in range(25) for b in range(25) if b - a > CLUSTER_GAP_BARS]
    counts = dict.fromkeys(pairs, 0)
    for _ in range(len(pairs) * 400):
        a, b = sample_dates(np.arange(25), 2, rng).tolist()
        counts[(a, b)] += 1
    expected = 400
    assert all(abs(c - expected) < 5 * expected**0.5 for c in counts.values())
    with pytest.raises(ValueError, match="contiguous"):
        sample_dates(np.array([0, 1, 5]), 1, rng)


def test_halves_compare_with_controls_from_their_own_half() -> None:
    from alpha_cli.spine.setup_controls import horizon_summary

    # Drift is 0 before entry 50 and 0.1 from it; history is cut at the second half's entry.
    returns = np.where(np.arange(100) < 50, 0.0, 0.1)
    rows = [
        dict(asset="X", entry_ts=t, candidate_id=t, net_return=0.05, complete=True)
        for t in (20, 50)
    ]
    times = {"X": list(range(100))}
    report = horizon_summary(rows, {"X": (np.arange(100), returns)}, times, "h", tested=True)
    halves = report["pooled"]["stability"]
    assert halves["first"]["drift_mean"] == pytest.approx(0.0)
    assert halves["second"]["drift_mean"] == pytest.approx(0.1)
    assert halves["first"]["random_date_95"] == pytest.approx(0.0)
    assert report["pooled"]["drift_mean"] == pytest.approx(0.05)


def test_supported_reading_says_unusual_dates_not_tradable() -> None:
    from alpha_cli.spine.setup_controls import reading

    sentence, _ = reading(
        dict(occurrences=40, mean=0.03, drift_mean=0.01, random_date_p=0.01, excess=0.02), 20, []
    )
    assert "unusual, not that the setup can be traded" in sentence
