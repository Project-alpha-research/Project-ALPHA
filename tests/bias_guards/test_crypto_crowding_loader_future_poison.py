"""Future-poison guards for the crypto crowding composition and the hedged-basis read.

Ported off the strategy-candidate runtime (`strategy_candidate_runtime.py`, deleted with
`alpha strategy-candidate`):

- The crowding composition (`research_crypto_data`, kept: `crypto_data_cmds` reads it) is the
  first test, unchanged.
- The candidate's admission cut (`_admit`: only events whose outcome is public by the cut-off) is
  gone with the candidate. On the kept path the cut is the held-back boundary inside the loader's
  scan (`load_crypto_crowding_observations`), so the second test poisons a bundle that crosses
  that boundary and reads it through the real loader.
- The candidate's regime labels (`_causal_return_regimes`) are gone with the candidate. The kept
  regime Monte Carlo labels states with `monte_carlo_cmds._causal_regime_states`, which has its own
  guard: `tests/bias_guards/test_monte_carlo_causality.py`. Nothing is ported for it here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from alpha_cli.research_crypto_data import (
    compose_crypto_crowding_observations,
    load_crypto_crowding_observations,
)
from alpha_core.reserve import RESERVED_INSTANT
from tests.unit.test_reserve_crypto_research import _frames as crossing_frames
from tests.unit.test_reserve_crypto_research import _snapshot

START = datetime(2025, 1, 1, tzinfo=UTC)
EVENTS = 370
CUTOFF_INDEX = 367


def _frames(*, poison_after: datetime | None) -> dict[str, pl.DataFrame]:
    """Compose the registered family bundle, optionally absurd strictly after ``poison_after``."""
    funding_times = [START + timedelta(hours=8 * index) for index in range(EVENTS)]
    hourly = [
        START - timedelta(hours=25) + timedelta(hours=index)
        for index in range(25 + 8 * (EVENTS - 1) + 1)
    ]

    def poisoned(timestamps: list[datetime], values: list[float], absurd: float) -> list[float]:
        if poison_after is None:
            return values
        return [
            absurd if timestamp > poison_after else value
            for timestamp, value in zip(timestamps, values, strict=True)
        ]

    def bars(family: str) -> pl.DataFrame:
        if family == "trade":
            closes = [100.0 + 0.01 * index for index in range(len(hourly))]
        elif family == "premium":
            closes = [0.001 + 0.0001 * (index % 5) for index in range(len(hourly))]
        else:
            closes = [100.0 + 0.02 * (index % 7) for index in range(len(hourly))]
        absurd = 9.0 if family == "premium" else 900_000.0
        return pl.DataFrame(
            {
                "timestamp": hourly,
                "category": ["linear"] * len(hourly),
                "symbol": ["BTCUSDT"] * len(hourly),
                "family": [family] * len(hourly),
                "close": poisoned(hourly, closes, absurd),
            }
        )

    def hourly_frame(column: str, values: list[float], absurd: float) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "timestamp": hourly,
                "category": ["linear"] * len(hourly),
                "symbol": ["BTCUSDT"] * len(hourly),
                column: poisoned(hourly, values, absurd),
            }
        )

    return {
        "funding": pl.DataFrame(
            {
                "timestamp": funding_times,
                "category": ["linear"] * EVENTS,
                "symbol": ["BTCUSDT"] * EVENTS,
                "funding_rate": poisoned(
                    funding_times,
                    [0.001 + 0.000_001 * index for index in range(EVENTS)],
                    5.0,
                ),
            }
        ),
        "open_interest": hourly_frame(
            "open_interest", [1_000.0 + index for index in range(len(hourly))], 9e9
        ),
        "long_short_ratio": hourly_frame("long_short_ratio", [1.25] * len(hourly), 900.0),
        "premium_bars": bars("premium"),
        "mark_bars": bars("mark"),
        "index_bars": bars("index"),
        "derivative_bars": bars("trade"),
        "instrument_catalog": pl.DataFrame(
            {
                "symbol": ["BTCUSDT"],
                "category": ["linear"],
                "status": ["Trading"],
                "base_coin": ["BTC"],
                "quote_coin": ["USDT"],
                "funding_interval_minutes": [480],
            }
        ),
    }


@pytest.mark.bias_guard
def test_crowding_observations_never_read_a_bar_after_their_own_funding_event() -> None:
    """Rewriting every input strictly after event ``k`` may not move observations ``0..k``."""
    clean = compose_crypto_crowding_observations(_frames(poison_after=None), correction_lineage=())
    cutoff = clean[CUTOFF_INDEX].funding_time
    poisoned = compose_crypto_crowding_observations(
        _frames(poison_after=cutoff), correction_lineage=()
    )

    assert len(poisoned) == len(clean)
    # Observations strictly before the cutoff resolve every mark, including their outcome.
    assert poisoned[:CUTOFF_INDEX] == clean[:CUTOFF_INDEX]
    decision = clean[CUTOFF_INDEX]
    observed = poisoned[CUTOFF_INDEX]
    for field in (
        "regime",
        "recent_trend",
        "recent_volatility",
        "premium",
        "entry_mark",
        "entry_index",
        "funding_rate",
        "open_interest",
        "long_short_ratio",
    ):
        assert getattr(observed, field) == getattr(decision, field), field
    assert decision.regime != "warmup"
    # The poison is potent: the events that legitimately read past the cutoff do move.
    assert poisoned[CUTOFF_INDEX + 1 :] != clean[CUTOFF_INDEX + 1 :]


@pytest.mark.bias_guard
def test_hedged_basis_inputs_admit_no_event_whose_outcome_is_held_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every row from the reserved instant on is poisoned (x1000). Through the real loader the
    observations do not move, and each admitted event's outcome is public by the cut."""
    clean_snapshot, clean_reports = _snapshot(
        tmp_path / "clean", monkeypatch, poisoned=False, cut=False
    )
    snapshot, reports = _snapshot(tmp_path / "poisoned", monkeypatch, poisoned=True, cut=False)
    clean = load_crypto_crowding_observations(
        clean_snapshot, clean_reports, bulk_root=tmp_path / "clean"
    )
    poisoned = load_crypto_crowding_observations(snapshot, reports, bulk_root=tmp_path / "poisoned")

    assert clean and poisoned == clean
    assert all(item.exit_available_at <= RESERVED_INSTANT for item in poisoned)
    # The bundle crosses the cut: events exist whose outcome is not public by it.
    uncut = load_crypto_crowding_observations(
        snapshot, reports, bulk_root=tmp_path / "poisoned", before_reserved=False
    )
    assert any(item.exit_available_at > RESERVED_INSTANT for item in uncut)
    # The poison is potent: without the cut the poisoned rows do reach the caller.
    assert compose_crypto_crowding_observations(
        crossing_frames(poisoned=True, cut=False), correction_lineage=()
    ) != compose_crypto_crowding_observations(
        crossing_frames(poisoned=False, cut=False), correction_lineage=()
    )
