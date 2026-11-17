"""Deterministic price-feed sensitivity controls; no publication or trial-ledger writes."""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from alpha_cli import _runner
from alpha_cli.spine.diagnostics import performance
from alpha_core import Bar, CorporateAction, DataError

NOISE_SEEDS = 50
NOISE_SIGMA = 0.001
BASIS = (
    "full-sample net engine re-runs; independent lognormal OHLC noise, "
    "sigma 0.001; controls, not trials"
)


def noisy_bars(bars: list[Bar], run_id: str, copy: int) -> list[Bar]:
    seed = int.from_bytes(hashlib.sha256(f"price-noise:{run_id}:{copy}".encode()).digest(), "big")
    rng = np.random.default_rng(seed)
    changed = []
    for bar in bars:
        values = np.asarray([bar.open, bar.high, bar.low, bar.close], dtype=float)
        values *= np.exp(rng.normal(0.0, NOISE_SIGMA, 4))
        opened, high, low, close = map(float, values)
        changed.append(
            Bar(
                symbol=bar.symbol,
                ts=bar.ts,
                open=opened,
                high=max(high, opened, close),
                low=max(0.0, min(low, opened, close)),
                close=close,
                volume=bar.volume,
            )
        )
    return changed


def noise_summary(runs: list[dict[str, Any]], original: float | None) -> dict[str, Any]:
    if len(runs) != NOISE_SEEDS:
        raise DataError(f"price noise requires {NOISE_SEEDS} copies")
    values = [row["sharpe"] for row in runs if row["sharpe"] is not None]
    if any(not np.isfinite(value) for value in values):
        raise DataError("price-noise Sharpe values must be finite")
    if original is not None and not np.isfinite(original):
        raise DataError("original Sharpe must be finite or unavailable")
    # Never silently drop a flat copy: percentiles over a selected subset could hide fragility.
    missing = NOISE_SEEDS - len(values)
    reason = f"{missing} of {NOISE_SEEDS} copies have no defined net Sharpe" if missing else None
    median, low, high = (
        (None, None, None) if missing else map(float, np.percentile(values, [50, 5, 95]))
    )
    flips = (
        None if missing or original is None else sum(v * original < 0 for v in values) / NOISE_SEEDS
    )
    # A positive rule whose 5th percentile is not positive, or that has no defined Sharpe at all
    # on some slightly different feed (it went flat), is fragile.
    labels = (
        ["fragile-to-price-noise"]
        if original is not None and original > 0 and (missing or (low is not None and low <= 0))
        else []
    )
    reasons = dict.fromkeys(("median_sharpe", "p05_sharpe", "p95_sharpe"), reason) if reason else {}
    if flips is None:
        reasons["sign_flip_share"] = reason or "original net Sharpe is unavailable"
    shown = "unavailable" if original is None else f"{original:.2f}"
    sentence = (
        f"With every price nudged at random by about a tenth of a percent, the Sharpe ranged "
        f"from {low:.2f} to {high:.2f} across the middle 90% of 50 copies (original {shown}); "
        f"the sign flipped in {flips:.0%} of 50 copies."
        if low is not None and high is not None and flips is not None
        else (
            f"Price-noise comparison is unavailable: {reason or reasons.get('sign_flip_share')}; "
            f"original Sharpe {shown}."
        )
    )
    return {
        "basis": BASIS,
        "copies": NOISE_SEEDS,
        "undefined_copies": missing,
        "sigma": NOISE_SIGMA,
        "original_sharpe": original,
        "median_sharpe": median,
        "p05_sharpe": low,
        "p95_sharpe": high,
        "sign_flip_share": flips,
        "median_trades": float(np.median([row["trades"] for row in runs])),
        "labels": labels,
        "sentence": sentence,
        "reasons": reasons,
        "runs": runs,
    }


def price_noise(
    bars: list[Bar],
    dividends: list[CorporateAction],
    spec: _runner.RunSpec,
    run_id: str,
    original: float | None,
) -> dict[str, Any]:
    runs = []
    for copy in range(NOISE_SEEDS):
        result = _runner.run_full_backtest(
            noisy_bars(bars, run_id, copy), spec, dividends=dividends
        )
        summary = performance(
            [value for _, value in result.equity_curve], spec.periods_per_year, BASIS
        )
        runs.append(
            {
                "copy": copy,
                "sharpe": summary["sharpe"],
                "trades": len(result.trades),
                "reasons": summary["reasons"],
            }
        )
    return noise_summary(runs, original)
