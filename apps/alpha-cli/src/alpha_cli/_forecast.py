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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import typer

from alpha_cli._artifacts import publish_artifact, write_manifest
from alpha_core import Bar, DataError
from alpha_core.config import AlphaSettings
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

    offline = local_files_only or (
        _in_cache(model, model_revision, hub_cache)
        and _in_cache(tokenizer, tokenizer_revision, hub_cache)
    )
    return KronosForecaster(
        model_id=model,
        model_revision=model_revision,
        tokenizer_id=tokenizer,
        tokenizer_revision=tokenizer_revision,
        device=device,
        cache_dir=hub_cache,
        local_files_only=offline,
    )


def _in_cache(repo: str, revision: str, cache_dir: Path | None) -> bool:
    """True when the files are local (a checkpoint folder, or the hub cache): no request needed."""
    if Path(repo).is_dir():
        return True
    from huggingface_hub import try_to_load_from_cache

    found = try_to_load_from_cache(repo, "config.json", cache_dir=cache_dir, revision=revision)
    return isinstance(found, str)


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


BATCH = 32  # Kronos draws up to 32 paths in one batch, for about the time of one path


@dataclass(frozen=True)
class Calibration:
    """What a short timed warm-up on this machine measured; it prices any run of the same model.

    One formula serves every number printed: the expected time and the "--paths N takes about"
    tip. ``load`` is the one-off model load; a batch costs ``fixed`` plus ``per_read`` for each
    bar the model reads."""

    model: str
    context: int
    window: int  # bars in the timed window
    load: float
    fixed: float
    per_read: float
    batch: int

    def seconds(self, *, horizon: int, rows: int, scale: int = 1) -> float:
        """The time for ``rows`` paths of ``horizon`` steps, rounded up to a whole second."""
        if self.model == "fake":
            return estimate_seconds(context=self.context, horizon=horizon, rows=rows) * scale
        batches = math.ceil(rows / self.batch)
        run = batches * (self.fixed + self.per_read * _reads(self.window, horizon))
        return float(math.ceil(self.load + run * scale))


def calibrate(
    forecaster: Forecaster,
    bars: Sequence[Bar],
    *,
    context: int,
    rows: int,
    model: str,
    clock: Callable[[], float] = time.monotonic,
) -> Calibration:
    """Time the warm-up: the first call loads the model, then one full batch of one step and of
    two steps give the time per bar read and the fixed time of a batch. The offline double is
    never timed. ``clock`` is stubbed in tests."""
    if model == "fake" or len(bars) < 2:
        return Calibration("fake", context, 0, 0.0, 0.0, 0.0, BATCH)
    window = list(bars[-context:])
    typer.echo("Timing a short warm-up step on this computer first.", err=True)
    batch = min(rows, BATCH)

    def timed(paths: int, steps: int) -> float:
        started = clock()
        forecaster.forecast(window, horizon=steps, sample_count=paths, seed=0)
        return clock() - started

    load = timed(1, 1)  # includes loading the model
    one, two = timed(batch, 1), timed(batch, 2)
    first = _reads(len(window), 1)
    # The second step's own time; a noisy reading falls back to the one-step time.
    per_read = (two - one) / (_reads(len(window), 2) - first) if two > one else one / first
    fixed = max(0.0, one - per_read * first)
    return Calibration(model, context, len(window), load, fixed, per_read, BATCH)


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

    ``scale`` repeats the run (one per scored origin)."""
    found = calibrate(forecaster, bars, context=context, rows=rows, model=model)
    return found.seconds(horizon=horizon, rows=rows, scale=scale)


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


def resolved_model(
    settings: AlphaSettings,
    model: str | None,
    model_revision: str | None,
    tokenizer: str | None,
    tokenizer_revision: str | None,
) -> tuple[str, str, str, str]:
    """Model and tokenizer ids with their revisions: the option, else the setting."""
    return (
        model if model is not None else settings.forecast_model,
        model_revision if model_revision is not None else settings.forecast_model_revision,
        tokenizer if tokenizer is not None else settings.forecast_tokenizer,
        tokenizer_revision
        if tokenizer_revision is not None
        else settings.forecast_tokenizer_revision,
    )
