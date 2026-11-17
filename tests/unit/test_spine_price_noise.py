"""Deterministic price controls use the real engine and never count as ideas."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from alpha_cli.spine.run import assemble_run_spec
from alpha_cli.spine.spec import load_spec
from alpha_core import Bar


def bars() -> list[Bar]:
    return [
        Bar(
            symbol="SPY",
            ts=datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=i),
            open=p,
            high=p,
            low=p,
            close=p,
            volume=1000000,
        )
        for i, p in enumerate([100.0 + 3 * np.sin(i / 3) + i / 20 for i in range(100)])
    ]


def test_noise_is_deterministic_valid_independent_and_preserves_volume() -> None:
    from alpha_cli.spine.price_noise import noisy_bars

    original = bars()
    first = noisy_bars(original, "a" * 16, 0)
    assert first == noisy_bars(original, "a" * 16, 0)
    assert first != noisy_bars(original, "b" * 16, 0)
    assert first != noisy_bars(original, "a" * 16, 1)
    for old, new in zip(original, first, strict=True):
        assert new.high >= max(new.open, new.close)
        assert 0 <= new.low <= min(new.open, new.close)
        assert new.volume == old.volume and new.ts == old.ts and new.symbol == old.symbol
        assert new.open / old.open != new.close / old.close
    assert original == bars()


def test_price_noise_real_engine_leaves_ledger_byte_identical(tmp_path: Path) -> None:
    from alpha_cli.spine.ledger import append_trial
    from alpha_cli.spine.price_noise import price_noise

    append_trial(tmp_path, {"run_id": "prior", "labels": []})
    ledger = tmp_path / "ledger/trials.jsonl"
    before = ledger.read_bytes()
    idea = load_spec(None, rule="ma_cross", param=["fast=2", "slow=5"], asset=["SPY"])
    spec = assemble_run_spec(idea, "SPY", 252, 100)
    result = price_noise(bars(), [], spec, "a" * 16, 1.0)
    assert result["copies"] == 50
    assert len(result["runs"]) == 50
    assert result["p05_sharpe"] <= result["median_sharpe"] <= result["p95_sharpe"]
    assert result["median_trades"] > 0
    assert ledger.read_bytes() == before


@pytest.mark.parametrize(
    "values,expected", [([-1.0] * 10 + [1.0] * 40, True), ([0.1] * 50, False), ([0.0] * 50, True)]
)
def test_fragile_and_robust_noise(values: list[float], expected: bool) -> None:
    from alpha_cli.spine.price_noise import noise_summary

    result = noise_summary([{"sharpe": value, "trades": 4, "reasons": {}} for value in values], 1.0)
    assert ("fragile-to-price-noise" in result["labels"]) is expected
    assert result["sign_flip_share"] == sum(v < 0 for v in values) / 50
    assert result["median_trades"] == 4
    assert result["p05_sharpe"] == pytest.approx(float(np.percentile(values, 5)))
    assert "50 copies" in result["sentence"]
    assert not noise_summary([{"sharpe": v, "trades": 4, "reasons": {}} for v in values], -1.0)[
        "labels"
    ]
