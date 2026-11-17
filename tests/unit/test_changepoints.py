"""Change points: planted shifts are found near their true position; the cap and errors hold."""

import math
from typing import Any

import numpy as np
import pytest
import ruptures

from alpha_validation import changepoints
from alpha_validation.changepoints import change_points, default_penalty, noise_variance


def _mean_shifts(seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.concatenate(
        [rng.normal(0.0, 1.0, 150), rng.normal(4.0, 1.0, 120), rng.normal(-3.0, 1.0, 130)]
    )


@pytest.mark.parametrize("model", ["rbf", "l2"])
def test_two_planted_mean_shifts_are_found(model: str) -> None:
    x = _mean_shifts()
    out = change_points(x, model=model)
    assert len(out["breaks"]) == 2
    assert abs(out["breaks"][0] - 150) <= 3
    assert abs(out["breaks"][1] - 270) <= 3
    assert out["labels"] == ["hindsight"]
    assert out["basis"] == changepoints.BASIS[model]
    assert "hindsight" in out["basis"]
    assert out["n"] == 400
    assert out["model"] == model
    assert out["min_size"] == 20
    assert out["max_points"] == 8
    assert out["penalty_raises"] == 0
    assert out["penalty"] == pytest.approx(default_penalty(x, model), rel=1e-12)
    first, second, third = out["segments"]
    assert (first["start"], first["end"]) == (0, out["breaks"][0])
    assert (second["start"], second["end"]) == (out["breaks"][0], out["breaks"][1])
    assert (third["start"], third["end"]) == (out["breaks"][1], 400)
    for segment in out["segments"]:
        part = x[segment["start"] : segment["end"]]
        assert segment["n"] == part.size == segment["end"] - segment["start"]
        assert segment["mean"] == pytest.approx(part.mean(), rel=1e-12)
        assert segment["std"] == pytest.approx(part.std(ddof=1), rel=1e-12)
    assert first["mean"] == pytest.approx(0.0, abs=0.3)
    assert second["mean"] == pytest.approx(4.0, abs=0.3)
    assert third["mean"] == pytest.approx(-3.0, abs=0.3)
    assert set(out) == {
        "breaks",
        "segments",
        "n",
        "model",
        "min_size",
        "max_points",
        "penalty",
        "penalty_raises",
        "labels",
        "basis",
    }


def test_default_model_is_rbf_and_finds_a_volatility_shift() -> None:
    rng = np.random.default_rng(7)
    x = np.concatenate([rng.normal(0.0, 0.005, 300), rng.normal(0.0, 0.04, 300)])
    out = change_points(x)
    assert out["model"] == "rbf"
    assert len(out["breaks"]) == 1
    assert abs(out["breaks"][0] - 300) <= 10
    assert out["segments"][1]["std"] > 4 * out["segments"][0]["std"]
    # a mean-shift search does not see a pure volatility change at its default penalty
    assert change_points(x, model="l2", penalty=1.0)["breaks"] == []


@pytest.mark.parametrize(("model", "cost"), [("rbf", "rbf"), ("l2", "l2")])
def test_same_breaks_as_ruptures_pelt_with_the_matching_cost(model: str, cost: str) -> None:
    x = _mean_shifts(seed=9)[40:340]
    penalty = default_penalty(x, model)
    reference = ruptures.Pelt(model=cost, min_size=20, jump=1).fit(x).predict(pen=penalty)
    out = change_points(x, model=model)
    assert [*out["breaks"], 300] == [int(v) for v in reference]
    assert all(isinstance(v, int) for v in out["breaks"])


def test_default_penalties() -> None:
    x = _mean_shifts()
    d = np.diff(x)
    robust = (1.4826 * np.median(np.abs(d - np.median(d))) / math.sqrt(2)) ** 2
    variance = max(robust, np.var(d) / 2)
    assert noise_variance(x) == pytest.approx(variance, rel=1e-12)
    # close to the true noise variance of 1 although the level shifts by 4 and 7
    assert noise_variance(x) == pytest.approx(1.0, rel=0.25)
    assert np.var(x) > 5
    assert default_penalty(x, "rbf") == pytest.approx(2 * math.log(400), rel=1e-12)
    assert default_penalty(x, "l2") == pytest.approx(2 * math.log(400) * variance, rel=1e-12)
    shifted = np.cumsum(np.ones(50)) + np.tile([0.0, 1.0], 25)
    d2 = np.diff(shifted)
    assert np.median(d2) != 0
    assert noise_variance(shifted) == pytest.approx(
        max((1.4826 * np.median(np.abs(d2 - np.median(d2)))) ** 2 / 2, np.var(d2) / 2),
        rel=1e-12,
    )


def test_explicit_penalty_is_used() -> None:
    x = _mean_shifts()
    loose = change_points(x, model="l2", penalty=1e6)
    assert loose["breaks"] == []
    assert loose["penalty"] == 1e6
    assert len(loose["segments"]) == 1
    assert loose["segments"][0] == {
        "start": 0,
        "end": 400,
        "n": 400,
        "mean": pytest.approx(x.mean()),
        "std": pytest.approx(x.std(ddof=1)),
    }
    tight = change_points(x, model="l2", penalty=0.5, max_points=1000)
    assert len(tight["breaks"]) > 2
    assert tight["penalty"] == 0.5
    assert tight["penalty_raises"] == 0


def test_cap_raises_the_penalty_until_satisfied() -> None:
    x = _mean_shifts()
    free = change_points(x, model="l2", penalty=0.5, max_points=1000)
    capped = change_points(x, model="l2", penalty=0.5, max_points=2)
    assert len(free["breaks"]) > 2
    assert len(capped["breaks"]) == 2
    assert capped["max_points"] == 2
    assert capped["penalty_raises"] >= 1
    assert capped["penalty"] == pytest.approx(0.5 * 2.0 ** capped["penalty_raises"], rel=1e-12)
    # one doubling fewer would still have left too many breaks
    previous = change_points(x, model="l2", penalty=capped["penalty"] / 2, max_points=1000)
    assert len(previous["breaks"]) > 2
    one = change_points(x, model="l2", penalty=0.5, max_points=1)
    assert len(one["breaks"]) <= 1
    exact = change_points(x, model="l2", max_points=2)
    assert exact["penalty_raises"] == 0
    assert len(exact["breaks"]) == 2


def test_cap_gives_up_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(changepoints, "MAX_RAISES", 1)
    with pytest.raises(ValueError, match="more than 1 change points remain at penalty 0.002"):
        change_points(_mean_shifts(), model="l2", penalty=0.001, max_points=1)


def test_min_size_is_respected_and_passed_on() -> None:
    x = _mean_shifts()
    out = change_points(x, model="l2", penalty=0.5, min_size=60, max_points=1000)
    assert out["min_size"] == 60
    assert min(segment["n"] for segment in out["segments"]) >= 60
    assert len(out["breaks"]) >= 2
    small = change_points(x[:6], model="l2", penalty=1e-9, min_size=2, max_points=1000)
    assert min(segment["n"] for segment in small["segments"]) >= 2
    assert len(small["breaks"]) >= 1


@pytest.mark.parametrize(
    ("series", "kwargs", "message"),
    [
        (np.arange(59.0), {}, r"at least 3 \* min_size = 60 points, got 59"),
        (np.arange(29.0), {"min_size": 10}, r"3 \* min_size = 30 points, got 29"),
        (
            np.arange(80.0),
            {"model": "normal"},
            "unknown change-point model 'normal'; known: rbf, l2",
        ),
        (np.arange(80.0), {"min_size": 1}, "min_size must be at least 2, got 1"),
        (np.arange(80.0), {"max_points": 0}, "max_points must be at least 1, got 0"),
        (np.ones(80), {}, "series does not vary"),
        (np.r_[np.nan, np.arange(79.0)], {}, "missing or infinite"),
        (np.ones((40, 2)), {}, r"one-dimensional, got shape \(40, 2\)"),
        (np.arange(80.0), {"penalty": 0.0}, "penalty must be a positive number, got 0.0"),
        (np.arange(80.0), {"penalty": float("inf")}, "penalty must be a positive number"),
        (np.arange(80.0), {"penalty": float("nan")}, "penalty must be a positive number"),
    ],
)
def test_invalid_input_fails_loud(series: np.ndarray, kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        change_points(series, **kwargs)


def test_boundary_sizes_are_accepted() -> None:
    x = _mean_shifts()[:60]
    assert change_points(x)["n"] == 60
    assert change_points(x[:30], min_size=10)["n"] == 30
    assert change_points(x[:6], min_size=2, max_points=1)["n"] == 6


def test_fat_tailed_noise_without_a_change_rarely_breaks() -> None:
    # Review finding: a Gaussian-only noise scale under-penalised fat-tailed returns, so
    # Student-t(4) noise with no change at all produced spurious mean breaks.
    spurious = 0
    # Measured over these 100 seeds: 15 series broke with the robust-only scale, 3 now.
    for seed in range(100):
        x = 0.01 * np.random.default_rng(seed).standard_t(4, 1000)
        spurious += bool(change_points(x, model="l2")["breaks"])
    assert spurious <= 5
