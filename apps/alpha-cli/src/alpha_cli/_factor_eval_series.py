"""Trial series files for the RD-Agent factor screen: evidence only, never a verdict."""

from __future__ import annotations

import io
import math
from collections.abc import Iterator
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from alpha_cli import _rdagent_membership as membership
from alpha_cli._rdagent_clocks import CLOCKS
from alpha_cli._rdagent_judge import TOP_FRACTION, canonical, exclusive, sha
from alpha_core import DataError


def _bucket_frames(
    signal: np.ndarray, outcome: np.ndarray, days: list[date], symbols: list[str], direction: int
) -> tuple[pl.DataFrame, pl.DataFrame]:
    observations: dict[int, list[float]] = {bucket: [] for bucket in (1, 2, 3)}
    masses: dict[int, list[float]] = {bucket: [] for bucket in (1, 2, 3)}
    daily = []
    for day, scores, returns in zip(days, signal, outcome, strict=True):
        top = membership.third_weights(scores, direction, TOP_FRACTION)
        bottom = membership.third_weights(scores, -direction, TOP_FRACTION)
        if np.isfinite(scores).sum() == 1:
            bottom[:] = 0.0  # One name: both thirds are that name; the top bucket keeps it.
        middle = np.maximum(0.0, np.isfinite(scores).astype(float) - top - bottom)
        for bucket, weights in ((1, bottom), (2, middle), (3, top)):
            held = (weights > 0) & np.isfinite(returns)
            outcomes = (returns[held] * weights[held]).tolist()
            mass = weights[held].tolist()
            observations[bucket].extend(outcomes)
            masses[bucket].extend(mass)
            daily.append(
                {
                    "clock": "daily",
                    "date": day,
                    "bucket": bucket,
                    "mean_outcome": math.fsum(outcomes) / math.fsum(mass) if mass else None,
                }
            )
    # Explicit ordered sums avoid floating-point reductions depending on worker scheduling.
    buckets = [
        {
            "clock": "daily",
            "bucket": bucket,
            "mean_outcome": math.fsum(outcomes) / math.fsum(masses[bucket]) if outcomes else None,
            "observations": (
                int(count) if (count := math.fsum(masses[bucket])).is_integer() else count
            ),
        }
        for bucket, outcomes in observations.items()
    ]
    return (
        pl.DataFrame(buckets).with_columns(pl.col("mean_outcome").cast(pl.Float64)),
        pl.DataFrame(daily).with_columns(pl.col("mean_outcome").cast(pl.Float64)),
    )


def _clock_series_frames(
    row: dict[str, Any],
    data: dict[str, Any],
    signal: np.ndarray,
    outcome: np.ndarray,
    days: list[date],
    symbols: list[str],
) -> Iterator[tuple[str, pl.DataFrame]]:
    if "daily_ic" in data:
        yield (
            "screen",
            pl.DataFrame(
                {
                    "clock": ["daily"] * len(days),
                    "date": days,
                    "rank_ic": pl.Series(data["daily_ic"], dtype=pl.Float64),
                    "names": data["names"],
                }
            ),
        )
    if row["screen"].get("status") == "OK":
        buckets, daily = _bucket_frames(signal, outcome, days, symbols, row["screen"]["direction"])
        yield "buckets", buckets
        yield "buckets_daily", daily
    if "periods" in data:
        periods = [
            {"clock": "daily", **{k: v for k, v in asdict(p).items() if k != "fold"}}
            for p in data["periods"]
        ]
        yield "replay", pl.DataFrame(periods).sort(["clock", "target_ts", "exit_ts"])
        yield (
            "holdings",
            pl.DataFrame(
                [
                    {
                        "clock": "daily",
                        "date": t.origin_ts.date(),
                        "instrument": t.symbol,
                        "target_weight": t.target_weight,
                        "score": t.score,
                    }
                    for t in data["targets"]
                ]
            ).sort(["clock", "date", "instrument"]),
        )

    if data.get("events"):
        yield "events", pl.DataFrame(data["events"]).with_columns(pl.lit("daily").alias("clock"))
    if data.get("positions"):
        yield (
            "positions",
            pl.DataFrame(
                [
                    {
                        "clock": "daily",
                        "date": snapshot["date"],
                        "instrument": name,
                        "quantity": snapshot["quantities"][j],
                        "cash": snapshot["cash"],
                        "equity": snapshot["equity"],
                    }
                    for snapshot in data["positions"]
                    for j, name in enumerate(symbols)
                ]
            ),
        )


def _series_frames(
    row: dict[str, Any],
    data: dict[str, Any],
    signal: np.ndarray,
    outcome: np.ndarray,
    days: list[date],
    symbols: list[str],
) -> Iterator[tuple[str, pl.DataFrame]]:
    frames: dict[str, list[pl.DataFrame]] = {}
    for clock in CLOCKS:
        if clock not in data:
            continue
        block = data[clock]
        if "days" not in block:
            continue
        for kind, frame in _clock_series_frames(
            row["clocks"][clock], block, block["signal"], block["outcome"], block["days"], symbols
        ):
            frames.setdefault(kind, []).append(frame.with_columns(pl.lit(clock).alias("clock")))
    for kind, blocks in frames.items():
        yield kind, pl.concat(blocks)


def _series_file(path: Path, payload: bytes) -> None:
    try:
        exclusive(path, payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise DataError(f"conflicting series file: {path.name}") from None


def _write_series(
    run: Path,
    iteration: int,
    rows: list[dict[str, Any]],
    series: dict[str, dict[str, Any]],
    signals: dict[str, np.ndarray],
    outcome: np.ndarray,
    days: list[date],
    symbols: list[str],
) -> tuple[str, str, set[str]]:
    relative = f"evaluations/iter-{iteration}/series/series.json"
    folder = (run / relative).parent
    folder.mkdir(parents=True, exist_ok=True)
    factors = []
    written = set()
    for row in rows:
        digest = row["code_sha256"]
        if digest not in series or row["stage"] == "none":
            continue
        files = []
        try:
            for kind, frame in _series_frames(
                row, series[digest], signals[digest], outcome, days, symbols
            ):
                name = f"{digest}.{kind}.parquet"
                buffer = io.BytesIO()
                frame.write_parquet(buffer)
                payload = buffer.getvalue()
                _series_file(folder / name, payload)
                files.append({"name": name, "sha256": sha(payload)})
        except Exception as error:  # Series must not change evaluation outcomes.
            row["series_note"] = f"{type(error).__name__}: {error}"
        if files:
            factors.append({"code_sha256": digest, "files": files})
            written.add(digest)
    payload = canonical({"schema": "AlphaRdagentTrialSeriesV1", "factors": factors})
    _series_file(run / relative, payload)
    return relative, sha(payload), written


def _record_series(
    run: Path,
    iteration: int,
    rows: list[dict[str, Any]],
    series: dict[str, dict[str, Any]],
    signals: dict[str, np.ndarray],
    outcome: np.ndarray,
    days: list[date],
    symbols: list[str],
    inputs: dict[str, Any],
) -> str | None:
    try:
        relative, digest, written = _write_series(
            run, iteration, rows, series, signals, outcome, days, symbols
        )
    except Exception as error:  # Evidence failures are recorded, never scoring failures.
        return f"{type(error).__name__}: {error}"
    inputs["series_sha256"] = digest
    for row in rows:
        if row["code_sha256"] in written and row["stage"] != "none":
            row["evidence"] = {"series_manifest": relative, "sha256": digest}
    return None
