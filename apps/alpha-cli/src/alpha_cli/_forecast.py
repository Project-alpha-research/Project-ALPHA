"""Forecast-run glue: PIT slice -> Forecaster -> summary + byte-stable artifacts.

The DAG's sanctioned composition point for alpha_forecast + the CLI store. The model
consumes only the trailing ``context`` bars at/<= the as-of instant; the ``pretrain`` block
records whether that window overlaps Kronos's assumed pretraining period (ADR-0009 leakage
policy: warn + flag, never block). Artifacts: ``manifest.json`` (byte-stable) +
``paths.parquet`` (per-sample OHLCV, long) + ``quantiles.parquet`` (per-step close bands)
+ ``history.parquet`` (as-of-filtered OHLCV tail for evidence-closed chart replay).
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import typer

from alpha_cli._artifacts import publish_artifact, write_manifest
from alpha_core import Bar, DataError
from alpha_forecast import Forecaster, ForecastResult, close_quantiles

FORECAST_SEED_NS = 0x464F5243  # "FORC": forecast children of the master seed (spec §11.4)
_HISTORY_TAIL = 180  # complete candles stored for the workstation's historical segment


def _forecaster_factory(
    *,
    model: str,
    model_revision: str,
    tokenizer: str,
    tokenizer_revision: str,
    device: str,
    hub_cache: Path | None = None,
    local_files_only: bool = False,
) -> Forecaster:
    """``fake`` -> the offline double; anything else -> a HF id / local checkpoint path."""
    if model == "fake":
        from alpha_forecast import FakeForecaster

        return FakeForecaster()
    from alpha_forecast import KronosForecaster

    return KronosForecaster(
        model_id=model,
        model_revision=model_revision,
        tokenizer_id=tokenizer,
        tokenizer_revision=tokenizer_revision,
        device=device,
        cache_dir=hub_cache,
        local_files_only=local_files_only,
    )


def _provenance(forecaster: Forecaster, *, model: str) -> dict[str, Any]:
    """The forecaster's manifest block (a stub for doubles without ``provenance()``)."""
    prov = getattr(forecaster, "provenance", None)
    if callable(prov):
        result: dict[str, Any] = dict(prov())
        return result
    return {
        "model_id": model,
        "model_revision": None,
        "tokenizer_id": None,
        "tokenizer_revision": None,
        "device": None,
        "torch_version": None,
        "vendor_sha": None,
        "determinism": "exact",
    }


# Kronos has no step cache: every new step re-reads the whole window (at most 512 bars) for every
# path. Measured on a 6-core desktop CPU (2026-11-23): about this many seconds per bar read.
SECONDS_PER_BAR_READ = 2.3e-4
MAX_WINDOW = 512


def _reads(context: int, horizon: int) -> int:
    return sum(min(context + step, MAX_WINDOW) for step in range(horizon))


def estimate_seconds(
    *, context: int, horizon: int, rows: int, per_read: float = SECONDS_PER_BAR_READ
) -> float:
    """A rough CPU time for ``rows`` paths of ``horizon`` steps from a ``context``-bar window."""
    return _reads(context, horizon) * rows * per_read


WARMUP_STEPS = 2
WARMUP_TRIES = 2


def calibrated_seconds(
    forecaster: Forecaster,
    bars: Sequence[Bar],
    *,
    context: int,
    horizon: int,
    rows: int,
    model: str,
    scale: int = 1,
) -> float:
    """The time for the run, from a short timed warm-up on this machine, rounded up.

    The first warm-up call loads the model and its time is added once. The slower of two short
    timed forecasts sets the seconds per bar read, so a busy CPU lengthens the estimate. The
    offline double is never timed. ``scale`` repeats the run (one per scored origin).
    """
    if model == "fake" or len(bars) < 2:
        return estimate_seconds(context=context, horizon=horizon, rows=rows) * scale
    window = list(bars[-context:])
    typer.echo("Timing a short warm-up step on this computer first.", err=True)

    def timed() -> float:
        started = time.monotonic()
        forecaster.forecast(window, horizon=WARMUP_STEPS, sample_count=1, seed=0)
        return time.monotonic() - started

    load = timed()  # includes loading the model
    step = max(timed() for _ in range(WARMUP_TRIES))
    per_read = step / _reads(len(window), WARMUP_STEPS)
    run = estimate_seconds(context=len(window), horizon=horizon, rows=rows, per_read=per_read)
    return float(math.ceil(max(load, step) + run * scale))


def say_time(seconds: float) -> str:
    if seconds < 90:
        return f"about {max(1, round(seconds))} seconds"
    if seconds < 5400:
        return f"about {math.ceil(seconds / 60)} minutes"
    return f"about {seconds / 3600:.1f} hours"


def expected_time_line(model: str, seconds: float) -> str | None:
    """The line printed before a Kronos run starts; the offline double needs none."""
    if model == "fake":
        return None
    return f"Expected time: {say_time(seconds)} on a desktop CPU (a rough guide)."


def fit_context(
    requested: int | None, *, default: int, available: int, what: str
) -> tuple[int, str | None]:
    """The context to use, and a line to print when a default was lowered to fit the data.

    An explicit value that does not fit fails and names the largest value that works.
    """
    if available < 2:
        raise DataError(f"Only {available} {what} are available. Kronos needs at least 2.")
    if requested is None:
        if default <= available:
            return default, None
        return available, (
            f"Context lowered from {default} to {available}: only {available} {what} are available."
        )
    if requested > available:
        raise DataError(
            f"Context {requested} is longer than the {available} {what} available. "
            f"The largest that works is {available}: use --context {available}."
        )
    return requested, None


def trading_day_line(as_of: datetime | None, last_bar: datetime) -> str | None:
    """Say so when the as-of date has no bar and the last bar before it is used."""
    if as_of is None or as_of.date() == last_bar.date():
        return None
    return (
        f"{as_of.date().isoformat()} is not a trading day in the data; "
        f"using the last trading day at or before it: {last_bar.date().isoformat()}."
    )


def forecast_seed(master: int) -> int:
    """Derive the forecast-sampling child seed from the master seed (independent stream)."""
    return int(np.random.SeedSequence([master, FORECAST_SEED_NS]).generate_state(1)[0])


def pretrain_overlap(bars: Sequence[Bar], cutoff: date) -> dict[str, Any]:
    """The leakage block for a model input window: which bars fall inside pretraining."""
    inside = [b for b in bars if b.ts.date() <= cutoff]
    return {
        "cutoff": cutoff.isoformat(),
        "overlap": bool(inside),
        "overlap_start": inside[0].ts.date().isoformat() if inside else None,
        "overlap_end": inside[-1].ts.date().isoformat() if inside else None,
    }


@dataclass(frozen=True)
class ForecastRunOutput:
    """One completed forecast: sampled paths + derived bands + leakage + summary scalars."""

    result: ForecastResult
    quantiles: dict[float, tuple[float, ...]]
    pretrain: dict[str, Any]
    n_context: int
    context_first_ts: datetime
    context_last_ts: datetime
    prob_up: float
    median_end_return: float
    p05_end_return: float
    p95_end_return: float


def run_forecast(
    bars: Sequence[Bar],
    *,
    forecaster: Forecaster,
    context: int,
    horizon: int,
    sample_count: int,
    temperature: float,
    top_p: float,
    top_k: int,
    seed: int,
    as_of: datetime | None,
    cutoff: date,
) -> ForecastRunOutput:
    """Slice the PIT window, sample the forecaster, summarize. Fails loud on thin data."""
    if as_of is not None:
        bars = [b for b in bars if b.ts <= as_of]
        if not bars:
            raise DataError(f"no bars at or before as-of {as_of.isoformat()}")
    if len(bars) < context:
        raise DataError(
            f"Context {context} is longer than the {len(bars)} bars available. "
            f"The largest that works is {len(bars)}: use --context {len(bars)}."
        )
    window = list(bars[-context:])

    result = forecaster.forecast(
        window,
        horizon=horizon,
        sample_count=sample_count,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        seed=seed,
    )
    quantiles = close_quantiles(result)
    origin_close = window[-1].close
    end_closes = np.array([p.close[-1] for p in result.samples], dtype=np.float64)
    return ForecastRunOutput(
        result=result,
        quantiles=quantiles,
        pretrain=pretrain_overlap(window, cutoff),
        n_context=len(window),
        context_first_ts=window[0].ts,
        context_last_ts=window[-1].ts,
        prob_up=float(np.mean(end_closes > origin_close)),
        median_end_return=quantiles[0.5][-1] / origin_close - 1.0,
        p05_end_return=quantiles[0.05][-1] / origin_close - 1.0,
        p95_end_return=quantiles[0.95][-1] / origin_close - 1.0,
    )


def write_forecast_run(
    rdir: Path, *, manifest: dict[str, Any], out: ForecastRunOutput, history: Sequence[Bar]
) -> None:
    """Write the run's artifacts. ``history`` must already be as-of-filtered (PIT)."""
    rdir.mkdir(parents=True, exist_ok=True)
    r = out.result
    paths = pl.DataFrame(
        [
            {
                "sample": s,
                "step": i + 1,
                "ts": r.step_ts[i],
                "open": p.open[i],
                "high": p.high[i],
                "low": p.low[i],
                "close": p.close[i],
                "volume": p.volume[i],
            }
            for s, p in enumerate(r.samples)
            for i in range(r.horizon)
        ]
    )
    publish_artifact(rdir / "paths.parquet", paths.write_parquet)

    q = out.quantiles
    means = np.array([p.close for p in r.samples], dtype=np.float64).mean(axis=0)
    quantiles = pl.DataFrame(
        [
            {
                "step": i + 1,
                "ts": r.step_ts[i],
                "q05": q[0.05][i],
                "q25": q[0.25][i],
                "q50": q[0.5][i],
                "q75": q[0.75][i],
                "q95": q[0.95][i],
                "mean": float(means[i]),
            }
            for i in range(r.horizon)
        ]
    )
    publish_artifact(rdir / "quantiles.parquet", quantiles.write_parquet)

    tail = list(history)[-_HISTORY_TAIL:]
    # Store complete observed candles.  Re-fetching these bars from the mutable market-data store
    # would let a provider correction change the visual story of an already immutable forecast.
    history_frame = pl.DataFrame(
        {
            "ts": [b.ts for b in tail],
            "open": [b.open for b in tail],
            "high": [b.high for b in tail],
            "low": [b.low for b in tail],
            "close": [b.close for b in tail],
            "volume": [b.volume for b in tail],
        }
    )
    publish_artifact(rdir / "history.parquet", history_frame.write_parquet)
    write_manifest(rdir, manifest)
