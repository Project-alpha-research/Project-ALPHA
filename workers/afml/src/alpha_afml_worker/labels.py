"""Wave 1 item 2: CUSUM events, triple-barrier labels and meta-labels (AFML ch. 2-3).

Two bases, never mixed:

* ``basis="high_low"`` -- **ALPHA's convention, the default and the headline.** Decide at the
  close of the event bar, enter at the next bar's open, and count a barrier as touched when a
  bar's HIGH or LOW reaches it (stops trigger inside the bar). A bar that reaches both barriers,
  without its open already deciding the order, is *ambiguous*: the headline scores it stop-first,
  and the optimistic reading (target-first) is reported beside it. Written here, in the adapter,
  because neither library reads highs and lows.
* ``basis="close"`` -- **the libraries' own convention, kept for parity.** Entry at the event
  bar's close, touches judged on closes only. RiskLabAI gives the answer; quantowl is the
  independent second opinion. They differ by design on one point (RiskLabAI compares log
  returns, quantowl simple returns) and every disagreement must be explained by it.

Causality (look-ahead is the worst bug here):

* The barrier width and the CUSUM threshold for bar ``t`` use volatility from closes strictly
  before bar ``t`` (:func:`prior_volatility`). No parameter is fitted on the sample.
* The vertical barrier is a bar count. An event without ``horizon`` later bars, and with no
  barrier touched in the bars that exist, is *open*: it gets no label rather than a guessed one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
import polars as pl
from quantowl import bars as qbars
from quantowl import labeling as ql
from RiskLabAI.data.labeling import labeling as rl

from alpha_afml_worker.contract import (
    AgreementError,
    ContractError,
    require_finite_positive,
    require_int_at_least,
    validate_bars,
)

Basis = Literal["high_low", "close"]


@dataclass(frozen=True)
class LabelParams:
    """Every knob of the event and label step. Nothing here is fitted on the data."""

    vol_span: int = 50  # EWM span of one-bar log returns, in bars
    vol_min_bars: int = 20  # returns needed before a volatility exists
    cusum_mult: float = 2.0  # CUSUM threshold = cusum_mult x prior volatility
    momentum_bars: int = 20  # primary side = sign of the log return over this many bars
    pt: float = 2.0  # profit target width, in units of prior volatility
    sl: float = 2.0  # stop width, in units of prior volatility
    horizon: int = 10  # vertical barrier, in bars after the event bar

    def __post_init__(self) -> None:
        require_int_at_least(self.vol_span, "vol_span", 2)
        require_int_at_least(self.vol_min_bars, "vol_min_bars", 2)
        require_int_at_least(self.momentum_bars, "momentum_bars", 1)
        require_int_at_least(self.horizon, "horizon", 1)
        for name in ("cusum_mult", "pt", "sl"):
            require_finite_positive(getattr(self, name), name)


def prior_volatility(close: np.ndarray, span: int, min_bars: int) -> np.ndarray:
    """EWM standard deviation of one-bar log returns, using closes strictly before each bar.

    ``out[t]`` is computed from ``close[0 .. t-1]`` only (the returns ending at bar ``t - 1``),
    so the value is known before bar ``t`` trades. Leading bars without ``min_bars`` returns are
    NaN. Differs on purpose from the libraries' Snippet 3.1, whose one-calendar-day look-back
    skips a bar on daily data and whose value at ``t`` includes bar ``t``'s own close.
    """
    returns = pd.Series(np.diff(np.log(close)))
    vol = returns.ewm(span=span, min_periods=min_bars).std().to_numpy(dtype=np.float64)
    out = np.full(close.size, np.nan)
    # vol[i] ends with the return close[i] -> close[i + 1]; it is known from bar i + 2 on.
    out[2:] = vol[:-1]
    return out


def cusum_events(ts: pd.DatetimeIndex, close: np.ndarray, threshold: np.ndarray) -> np.ndarray:
    """Bar positions where RiskLabAI's symmetric CUSUM filter on log closes fires.

    ``threshold[t]`` applies to the move into bar ``t``; bars with no threshold yet (NaN) are
    left out, so the running sums start at the first bar that has one.
    """
    known = np.isfinite(threshold)
    log_close = pd.Series(np.log(close), index=ts)
    limit = pd.Series(threshold[known], index=ts[known])
    fired = rl.cusum_filter_events_dynamic_threshold(log_close, limit)
    positions = ts.get_indexer(pd.DatetimeIndex(fired))
    if bool(np.any(positions < 0)):
        raise AgreementError("CUSUM returned a time that is not a bar")
    return np.asarray(positions, dtype=np.int64)


def cusum_events_fixed(ts: pd.DatetimeIndex, close: np.ndarray, threshold: float) -> np.ndarray:
    """Fixed-threshold CUSUM on log closes; both libraries must return the same bars."""
    log_close = pd.Series(np.log(close), index=ts)
    primary = ts.get_indexer(pd.DatetimeIndex(rl.symmetric_cusum_filter(log_close, threshold)))
    second = ts.get_indexer(pd.DatetimeIndex(qbars.cusum_filter(log_close, threshold)))
    if not np.array_equal(primary, second):
        raise AgreementError("fixed-threshold CUSUM events differ between the libraries")
    return np.asarray(primary, dtype=np.int64)


@dataclass(frozen=True)
class _Outcome:
    end: int  # bar position where the label ends; -1 when open
    outcome: str  # target | stop | vertical | open
    ambiguous: bool
    ret: float  # side-adjusted simple return, entry to exit; NaN when open
    ret_optimistic: float
    outcome_optimistic: str


def _high_low_one(
    o: np.ndarray,
    h: np.ndarray,
    lo: np.ndarray,
    c: np.ndarray,
    t: int,
    side: float,
    width: float,
    params: LabelParams,
) -> _Outcome:
    n = c.size
    if t + 1 >= n:
        return _Outcome(-1, "open", False, np.nan, np.nan, "open")
    entry = o[t + 1]
    target = entry * (1.0 + side * params.pt * width)
    stop = entry * (1.0 - side * params.sl * width)
    for j in range(t + 1, min(t + params.horizon, n - 1) + 1):
        if side > 0:
            gap_stop, gap_target = o[j] <= stop, o[j] >= target
            hit_target, hit_stop = h[j] >= target, lo[j] <= stop
            stop_exit, target_exit = min(stop, o[j]), max(target, o[j])
        else:
            gap_stop, gap_target = o[j] >= stop, o[j] <= target
            hit_target, hit_stop = lo[j] <= target, h[j] >= stop
            stop_exit, target_exit = max(stop, o[j]), min(target, o[j])
        stop_ret = side * (stop_exit / entry - 1.0)
        target_ret = side * (target_exit / entry - 1.0)
        if gap_stop or (hit_stop and not hit_target):
            return _Outcome(j, "stop", False, stop_ret, stop_ret, "stop")
        if gap_target or (hit_target and not hit_stop):
            return _Outcome(j, "target", False, target_ret, target_ret, "target")
        if hit_target and hit_stop:
            return _Outcome(j, "stop", True, stop_ret, target_ret, "target")
    end = t + params.horizon
    if end > n - 1:
        return _Outcome(-1, "open", False, np.nan, np.nan, "open")
    ret = side * (c[end] / entry - 1.0)
    return _Outcome(end, "vertical", False, ret, ret, "vertical")


def _close_basis(
    ts: pd.DatetimeIndex,
    c: np.ndarray,
    events: np.ndarray,
    sides: np.ndarray,
    widths: np.ndarray,
    params: LabelParams,
) -> pl.DataFrame:
    """The libraries' close-only labels, RiskLabAI first, quantowl as the cross-check.

    RiskLabAI's barrier scan cannot take time-zone-aware times (it casts them to
    ``datetime64[ns]``), so both libraries get the same instants as naive UTC.
    """
    ts = ts.tz_convert("UTC").tz_localize(None)
    close = pd.Series(c, index=ts)
    starts = ts[events]
    vertical_pos = events + params.horizon
    vertical = pd.Series(
        [ts[p] if p < c.size else pd.NaT for p in vertical_pos.tolist()],
        index=starts,
        dtype=ts.dtype,
    )
    frame = pd.DataFrame(
        {"End Time": vertical, "Base Width": widths, "Side": sides.astype(float)}, index=starts
    )
    touched = rl.triple_barrier(close, frame, [params.pt, params.sl], list(starts))
    frame["End Time"] = touched["End Time"]
    labelled = rl.meta_labeling(frame, close)
    q_events = ql.get_events(
        close,
        starts,
        [params.pt, params.sl],
        pd.Series(widths, index=starts),
        0.0,
        vertical_barrier_times=vertical,
        side=pd.Series(sides.astype(float), index=starts),
    )
    q_bins = ql.get_bins(q_events, close, meta=True)

    end_r = ts.get_indexer(pd.DatetimeIndex(frame["End Time"]))
    end_q = ts.get_indexer(pd.DatetimeIndex(q_events["t1"].reindex(starts)))
    agree = end_r == end_q
    for i in np.flatnonzero(~agree).tolist():
        if not _explained_by_return_convention(
            c,
            int(events[i]),
            sides[i],
            widths[i],
            params,
            (
                int(end_r[i]),
                int(end_q[i]),
            ),
        ):
            raise AgreementError(
                f"close-basis labels differ at {starts[i]} for a reason other than log versus "
                "simple returns"
            )
    ret = labelled["Return"].reindex(starts).to_numpy(dtype=np.float64)
    label = labelled["Label"].reindex(starts).to_numpy(dtype=np.float64)
    q_label = q_bins["bin"].reindex(starts).to_numpy(dtype=np.float64)
    both = agree & (end_r >= 0)
    if not np.array_equal(label[both], q_label[both]):
        raise AgreementError("close-basis meta-labels differ where the end bars agree")
    return pl.DataFrame(
        {
            "close_end_pos": end_r,
            "close_log_ret": ret,
            "close_meta_label": label,
            "close_end_pos_quantowl": end_q,
            "close_barrier_quantowl": q_events["barrier"].reindex(starts).to_numpy(dtype=str),
            "close_libraries_agree": agree,
        }
    )


def _explained_by_return_convention(
    c: np.ndarray, t: int, side: float, width: float, params: LabelParams, ends: tuple[int, int]
) -> bool:
    """True when the bar that splits the two answers sits between the log and simple barrier."""
    candidates = [e for e in ends if e >= 0]
    if not candidates:
        return False
    j = min(candidates)
    simple = side * (c[j] / c[t] - 1.0)
    log = side * np.log(c[j] / c[t])
    up, down = params.pt * width, -params.sl * width
    return bool((simple > up) != (log > up) or (simple < down) != (log < down))


def _bar_index(clean: pl.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(clean["ts"].to_numpy()).tz_localize("UTC")


def find_events(bars: pl.DataFrame, params: LabelParams) -> pl.DataFrame:
    """CUSUM events with a primary side and a barrier width, all known at the event bar's close.

    Columns: ``ts``, ``pos`` (bar position), ``side`` (+1/-1, sign of the ``momentum_bars`` log
    return ending at the event bar), ``width`` (prior volatility) and ``threshold``. Events with
    no side (a flat move) or no volatility yet are left out.
    """
    clean = validate_bars(bars)
    c = clean["close"].to_numpy()
    vol = prior_volatility(c, params.vol_span, params.vol_min_bars)
    threshold = params.cusum_mult * vol
    events = cusum_events(_bar_index(clean), c, threshold)
    log_c = np.log(c)
    m = params.momentum_bars
    momentum = np.full(c.size, np.nan)
    momentum[m:] = log_c[m:] - log_c[:-m]
    sides = np.sign(momentum[events])
    keep = np.isfinite(sides) & (sides != 0.0) & np.isfinite(vol[events]) & (vol[events] > 0.0)
    events, sides = events[keep], sides[keep]
    return pl.DataFrame(
        {
            "ts": clean["ts"].gather(events),
            "pos": events,
            "side": sides.astype(np.int64),
            "width": vol[events],
            "threshold": threshold[events],
        }
    )


def barrier_labels(
    bars: pl.DataFrame, events: pl.DataFrame, params: LabelParams, basis: Basis = "high_low"
) -> pl.DataFrame:
    """Triple-barrier labels and meta-labels for given events (``pos``, ``side``, ``width``).

    ``basis="high_low"`` adds ``end``, ``end_pos``, ``outcome``, ``ambiguous``, ``ret``,
    ``meta_label`` and their ``*_optimistic`` readings; ``basis="close"`` adds the RiskLabAI
    and quantowl close-only columns. ``meta_label`` is 1 when the side's return is positive.
    """
    if basis not in ("high_low", "close"):
        raise ContractError(f"basis must be 'high_low' or 'close', got {basis!r}")
    clean = validate_bars(bars)
    o, h, lo, c = (clean[name].to_numpy() for name in ("open", "high", "low", "close"))
    pos = events["pos"].to_numpy().astype(np.int64)
    sides = events["side"].to_numpy().astype(np.float64)
    widths = events["width"].to_numpy().astype(np.float64)
    if pos.size == 0:
        raise ContractError("no events to label")
    if bool(np.any(pos < 0)) or bool(np.any(pos >= c.size)) or bool(np.any(np.diff(pos) <= 0)):
        raise ContractError("event positions must be distinct, increasing bar positions")
    if not bool(np.all(np.isin(sides, (-1.0, 1.0)))):
        raise ContractError("every event side must be +1 or -1")
    if not bool(np.all(np.isfinite(widths))) or bool(np.any(widths <= 0.0)):
        raise ContractError("every event width must be finite and > 0")
    if basis == "close":
        closed = _close_basis(_bar_index(clean), c, pos, sides, widths, params)
        return pl.concat([events, closed], how="horizontal")
    rows = [
        _high_low_one(o, h, lo, c, int(t), float(s), float(w), params)
        for t, s, w in zip(pos.tolist(), sides.tolist(), widths.tolist(), strict=True)
    ]
    ends = np.array([r.end for r in rows], dtype=np.int64)
    ret = np.array([r.ret for r in rows])
    ret_opt = np.array([r.ret_optimistic for r in rows])
    end_ts = [clean["ts"][int(e)] if e >= 0 else None for e in ends.tolist()]
    return events.with_columns(
        end=pl.Series(end_ts, dtype=clean.schema["ts"]),
        end_pos=pl.Series(ends),
        outcome=pl.Series([r.outcome for r in rows], dtype=pl.String),
        ambiguous=pl.Series([r.ambiguous for r in rows], dtype=pl.Boolean),
        ret=pl.Series(ret),
        meta_label=pl.Series(np.where(np.isfinite(ret), (ret > 0.0).astype(float), np.nan)),
        outcome_optimistic=pl.Series([r.outcome_optimistic for r in rows], dtype=pl.String),
        ret_optimistic=pl.Series(ret_opt),
        meta_label_optimistic=pl.Series(
            np.where(np.isfinite(ret_opt), (ret_opt > 0.0).astype(float), np.nan)
        ),
    ).with_columns(
        pl.col("meta_label", "ret", "ret_optimistic", "meta_label_optimistic").fill_nan(None)
    )


def label_events(
    bars: pl.DataFrame, params: LabelParams, basis: Basis = "high_low"
) -> pl.DataFrame:
    """The whole step: :func:`find_events`, then :func:`barrier_labels` on the chosen basis."""
    return barrier_labels(bars, find_events(bars, params), params, basis)
