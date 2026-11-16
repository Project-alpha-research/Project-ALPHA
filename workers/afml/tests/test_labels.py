"""Parity and causality for wave 1 item 2: CUSUM events, triple-barrier labels, meta-labels.

The hand-built path has known first touches on both bases. The truncation tests (labels decided
by bar k must not move when later bars are corrupted) live here, in the worker's own tests; a
copy under ``tests/bias_guards`` is a follow-up if the repository's rules want one there.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl
import pytest
from quantowl import bars as qbars
from RiskLabAI.data.labeling import labeling as rl
from shared_fixtures import SEED, daily_ts, make_bars

from alpha_afml_worker.contract import ContractError
from alpha_afml_worker.labels import (
    LabelParams,
    barrier_labels,
    cusum_events,
    cusum_events_fixed,
    find_events,
    label_events,
    prior_volatility,
)

# Twelve bars. Event at bar 0, width 1%, barriers at +-2%.
CLOSES = [100, 100.5, 101, 100.8, 101.5, 101.2, 103.0, 102.5, 102, 101, 100.5, 100]
OPENS = [100, 100.2, 100.6, 101, 100.9, 101.4, 101.5, 103, 102.4, 101.9, 101, 100.4]
HIGHS = [max(o, c) + 0.3 for o, c in zip(OPENS, CLOSES, strict=True)]
HIGHS[4] = 102.3  # the only high to reach entry 100.2 x 1.02 = 102.204 before bar 6
LOWS = [min(o, c) - 0.3 for o, c in zip(OPENS, CLOSES, strict=True)]
PARAMS = LabelParams(pt=2.0, sl=2.0, horizon=10)


def one_event(side: int, pos: int = 0, width: float = 0.01) -> pl.DataFrame:
    return pl.DataFrame({"pos": [pos], "side": [side], "width": [width]})


def hand_path() -> pl.DataFrame:
    return make_bars(OPENS, HIGHS, LOWS, CLOSES)


def test_hand_path_long_first_touch_both_bases() -> None:
    hl = barrier_labels(hand_path(), one_event(+1), PARAMS).row(0, named=True)
    # ALPHA: enter at bar 1's open (100.2); bar 4's high 102.3 reaches the target 102.204.
    assert (hl["end_pos"], hl["outcome"], hl["ambiguous"]) == (4, "target", False)
    assert hl["ret"] == pytest.approx(0.02, abs=1e-12)
    assert hl["meta_label"] == 1.0
    close = barrier_labels(hand_path(), one_event(+1), PARAMS, "close").row(0, named=True)
    # Libraries: enter at bar 0's close (100); the first close above 102 is bar 6 (103).
    assert close["close_end_pos"] == 6 and close["close_end_pos_quantowl"] == 6
    assert close["close_barrier_quantowl"] == "pt" and close["close_libraries_agree"]
    assert close["close_log_ret"] == pytest.approx(np.log(1.03))
    assert close["close_meta_label"] == 1.0


def test_hand_path_short_first_touch_both_bases() -> None:
    hl = barrier_labels(hand_path(), one_event(-1), PARAMS).row(0, named=True)
    assert (hl["end_pos"], hl["outcome"]) == (4, "stop")
    assert hl["ret"] == pytest.approx(-0.02, abs=1e-12)
    assert hl["meta_label"] == 0.0
    close = barrier_labels(hand_path(), one_event(-1), PARAMS, "close").row(0, named=True)
    assert close["close_end_pos"] == 6 and close["close_end_pos_quantowl"] == 6
    assert close["close_barrier_quantowl"] == "sl" and close["close_meta_label"] == 0.0


def test_touch_at_exactly_the_barrier_counts_on_high_low() -> None:
    target = 100.0 * (1.0 + 2.0 * 0.01)
    bars = make_bars([100, 100, 100], [100.5, target, 100.5], [99.5, 99.5, 99.5], [100] * 3)
    row = barrier_labels(bars, one_event(+1), PARAMS).row(0, named=True)
    assert (row["end_pos"], row["outcome"]) == (1, "target")


def test_one_bar_reaching_both_barriers_is_ambiguous_and_scored_stop_first() -> None:
    bars = make_bars([100, 100, 100], [100.5, 103, 100.5], [99.5, 97, 99.5], [100, 100, 100])
    row = barrier_labels(bars, one_event(+1), PARAMS).row(0, named=True)
    assert row["ambiguous"] and row["outcome"] == "stop" and row["end_pos"] == 1
    assert row["ret"] == pytest.approx(-0.02) and row["meta_label"] == 0.0
    assert row["outcome_optimistic"] == "target"
    assert row["ret_optimistic"] == pytest.approx(0.02) and row["meta_label_optimistic"] == 1.0


def test_gap_through_the_stop_exits_at_the_open_and_is_not_ambiguous() -> None:
    bars = make_bars(
        [100, 100, 97, 100], [100.5, 100.5, 103, 100.5], [99.5, 99.5, 96, 99.5], [100, 100, 99, 100]
    )
    row = barrier_labels(bars, one_event(+1), PARAMS).row(0, named=True)
    assert (row["outcome"], row["ambiguous"], row["end_pos"]) == ("stop", False, 2)
    assert row["ret"] == pytest.approx(-0.03)  # filled at the 97 open, worse than the stop


def test_vertical_barrier_and_open_label() -> None:
    flat = make_bars([100] * 6, [100.5] * 6, [99.5] * 6, [100, 100, 100, 100.4, 100, 100])
    params = LabelParams(horizon=3)
    rows = barrier_labels(
        flat, pl.DataFrame({"pos": [0, 4], "side": [1, 1], "width": [0.01, 0.01]}), params
    )
    first, last = rows.row(0, named=True), rows.row(1, named=True)
    assert (first["outcome"], first["end_pos"]) == ("vertical", 3)
    assert first["ret"] == pytest.approx(0.004)
    # Bar 4 needs bars up to 7; only bar 5 exists and touches nothing: no label, not a guess.
    assert (last["outcome"], last["end_pos"], last["ret"], last["meta_label"]) == (
        "open",
        -1,
        None,
        None,
    )


def test_meta_label_is_one_exactly_when_the_side_made_money(spy_bars: pl.DataFrame) -> None:
    rows = label_events(spy_bars, LabelParams()).filter(pl.col("ret").is_not_null())
    assert rows.height > 50
    assert (rows["meta_label"] == (rows["ret"] > 0).cast(pl.Float64)).all()


def test_volatility_uses_only_bars_strictly_before() -> None:
    rng = np.random.default_rng(SEED)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
    base = prior_volatility(close, 50, 20)
    for t in (30, 100, 299):
        moved = close.copy()
        moved[t:] *= 1.5
        bumped = prior_volatility(moved, 50, 20)
        np.testing.assert_array_equal(bumped[: t + 1], base[: t + 1])
        if t + 1 < close.size:
            assert bumped[t + 1] != base[t + 1]  # bar t's close does reach bar t + 1
    assert np.isnan(base[:21]).all() and np.isfinite(base[21:]).all()


def test_cusum_hand_path_and_libraries_agree() -> None:
    steps = [0.01, 0.01, 0.01, -0.04, 0.0, 0.02, 0.02]
    close = 100 * np.exp(np.concatenate([[0.0], np.cumsum(steps)]))
    ts = pd.DatetimeIndex(daily_ts(close.size).to_numpy()).tz_localize("UTC")
    # S+ = .01, .02, .03 > .025 fires at bar 3; then S- = -.04 fires at bar 4; S+ = .04 at bar 7.
    assert cusum_events_fixed(ts, close, 0.025).tolist() == [3, 4, 7]
    assert cusum_events(ts, close, np.full(close.size, 0.025)).tolist() == [3, 4, 7]


def test_cusum_fixed_threshold_libraries_agree_on_spy(spy_bars: pl.DataFrame) -> None:
    ts = pd.DatetimeIndex(spy_bars["ts"].to_numpy()).tz_localize("UTC")
    close = spy_bars["close"].to_numpy()
    for h in (0.01, 0.02, 0.04):
        fixed = cusum_events_fixed(ts, close, h)
        assert fixed.size > 5
        assert cusum_events(ts, close, np.full(close.size, h)).tolist() == fixed.tolist()
    log_close = pd.Series(np.log(close), index=ts)
    assert list(rl.symmetric_cusum_filter(log_close, 0.02)) == list(
        qbars.cusum_filter(log_close, 0.02)
    )


def test_close_basis_disagreements_are_all_log_versus_simple(spy_bars: pl.DataFrame) -> None:
    # barrier_labels raises AgreementError on any disagreement not explained by the return
    # convention; this pins that the real series runs clean and how many cases there are.
    rows = label_events(spy_bars, LabelParams(), "close")
    disagree = rows.filter(~pl.col("close_libraries_agree")).height
    assert rows.height > 50 and disagree <= rows.height // 20


def _corrupt_after(bars: pl.DataFrame, k: int, seed: int) -> pl.DataFrame:
    factor = np.ones(bars.height)
    factor[k + 1 :] = np.random.default_rng(seed).uniform(0.5, 1.5, bars.height - k - 1)
    return bars.with_columns(
        pl.col(c) * pl.Series(factor) for c in ("open", "high", "low", "close")
    )


@pytest.mark.parametrize("k", [120, 250, 400])
@pytest.mark.parametrize("basis", ["high_low", "close"])
def test_truncation_labels_decided_by_bar_k_do_not_move(
    spy_bars: pl.DataFrame, k: int, basis: str
) -> None:
    params = LabelParams()
    end = "end_pos" if basis == "high_low" else "close_end_pos"
    full = label_events(spy_bars, params, basis)  # type: ignore[arg-type]
    for variant in (_corrupt_after(spy_bars, k, SEED + k), spy_bars.head(k + 1)):
        other = label_events(variant, params, basis)  # type: ignore[arg-type]
        events_full = full.filter(pl.col("pos") <= k).select(
            "ts", "pos", "side", "width", "threshold"
        )
        events_other = other.filter(pl.col("pos") <= k).select(
            "ts", "pos", "side", "width", "threshold"
        )
        assert events_full.equals(events_other)
        decided_full = full.filter((pl.col(end) >= 0) & (pl.col(end) <= k))
        decided_other = other.filter((pl.col(end) >= 0) & (pl.col(end) <= k))
        assert decided_full.height > 10
        assert decided_full.equals(decided_other)


def test_find_events_use_only_the_past(spy_bars: pl.DataFrame) -> None:
    events = find_events(spy_bars, LabelParams())
    k = 300
    assert find_events(spy_bars.head(k + 1), LabelParams()).equals(
        events.filter(pl.col("pos") <= k)
    )


@pytest.mark.parametrize(
    "bad",
    [
        pl.DataFrame({"pos": [0, 0], "side": [1, 1], "width": [0.01, 0.01]}),
        pl.DataFrame({"pos": [0], "side": [0], "width": [0.01]}),
        pl.DataFrame({"pos": [0], "side": [1], "width": [0.0]}),
        pl.DataFrame({"pos": [99], "side": [1], "width": [0.01]}),
    ],
)
def test_bad_events_fail_loud(bad: pl.DataFrame) -> None:
    with pytest.raises(ContractError):
        barrier_labels(hand_path(), bad, PARAMS)


def test_bad_bars_fail_loud() -> None:
    bars = hand_path()
    with pytest.raises(ContractError):
        barrier_labels(bars.with_columns(pl.lit(float("nan")).alias("close")), one_event(1), PARAMS)
    with pytest.raises(ContractError):
        barrier_labels(bars.reverse(), one_event(1), PARAMS)
    with pytest.raises(ContractError):
        barrier_labels(
            bars.with_columns(pl.col("ts").dt.replace_time_zone(None)), one_event(1), PARAMS
        )
    with pytest.raises(ContractError):
        barrier_labels(bars.with_columns(pl.col("low") + 5), one_event(1), PARAMS)
