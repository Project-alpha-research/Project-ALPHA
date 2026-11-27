"""Diagnostics and the replay-signal handoff built on a validated Qlib worker result bundle."""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path
from typing import Any

import polars as pl

from alpha_cli.ml_contract import (
    MLContractError,
    _as_finite_float,
    sha256_file,
)
from alpha_cli.ml_result_validation import validate_result_bundle


def evaluate_result_bundle(exchange_dir: Path) -> dict[str, Any]:
    """Return portable diagnostics only; canonical ALPHA replay remains a later explicit step."""
    validated = validate_result_bundle(exchange_dir)
    scores = validated.predictions.get_column("score")
    score_min = _as_finite_float(scores.min(), "prediction score minimum")
    score_max = _as_finite_float(scores.max(), "prediction score maximum")
    score_mean = _as_finite_float(scores.mean(), "prediction score mean")
    score_std = _as_finite_float(scores.std(ddof=0), "prediction score standard deviation")
    legacy_membership = validated.request.membership_status == "declared_unverified"
    return {
        "schema_version": validated.request.request["schema_version"],
        "authority": "diagnostic_only",
        "membership_status": validated.request.membership_status,
        "rows": validated.predictions.height,
        "symbols": validated.predictions.get_column("symbol").n_unique(),
        "targets": validated.predictions.get_column("target_ts").n_unique(),
        "folds": sorted(validated.predictions.get_column("fold").unique().to_list()),
        "score": {
            "min": score_min,
            "max": score_max,
            "mean": score_mean,
            "std": score_std,
        },
        "config_hash": validated.request.request["config_hash"],
        "worker_lock_hash": validated.request.request["worker_lock_hash"],
        "counterfactual_refit": False,
        "label": (
            "OOS predictions validated; point_in_time membership is declared but unverified"
            if legacy_membership
            else "OOS prediction contract validated — canonical ALPHA replay pending"
        ),
        "diagnostics": validated.result["diagnostics"],
        "next_required_step": (
            "Frozen result is inspection-only because point_in_time membership is unverified; "
            "training and replay are disabled"
            if legacy_membership
            else "canonical ALPHA replay: run `alpha ml replay EXCHANGE`; counterfactual refit "
            "remains required for null verdicts"
        ),
    }


def replay_signal_frame(exchange_dir: Path) -> pl.DataFrame:
    """Build the deterministic top-quintile/equal-weight handoff for the ALPHA composer.

    This is a causal signal contract, not a returns-level substitute for canonical engine replay.
    The current engine seam is single-instrument; the handoff keeps that remaining integration gap
    explicit while making every intended position inspectable and hashable.
    """
    validated = validate_result_bundle(exchange_dir)
    if validated.request.membership_status == "declared_unverified":
        raise MLContractError(
            "point_in_time membership is declared but unverified; replay-signal generation is "
            "disabled for this frozen result"
        )
    rows: list[dict[str, Any]] = []
    predictions = validated.predictions.filter(pl.col("split") == "test")
    for key, cross_section in predictions.group_by(
        ["fold", "split", "target_ts"], maintain_order=True
    ):
        fold, split, target_ts = key
        ranked = cross_section.sort(
            ["score", "symbol"], descending=[True, False], maintain_order=True
        )
        selected_count = max(1, math.ceil(ranked.height * 0.2))
        weight = 1.0 / selected_count
        for rank, row in enumerate(ranked.iter_rows(named=True), start=1):
            selected = rank <= selected_count
            rows.append(
                {
                    "symbol": row["symbol"],
                    "origin_ts": row["origin_ts"],
                    "decision_ts": row["available_at"],
                    "available_at": row["available_at"],
                    "entry_ts": row["target_ts"],
                    "score": row["score"],
                    "cross_section_rank": rank,
                    "selected": selected,
                    "target_weight": weight if selected else 0.0,
                    "fold": int(fold),
                    "split": str(split),
                    "model_hash": row["model_hash"],
                    "config_hash": row["config_hash"],
                }
            )
    return pl.DataFrame(
        rows,
        schema={
            "symbol": pl.String,
            "origin_ts": pl.Datetime("us", "UTC"),
            "decision_ts": pl.Datetime("us", "UTC"),
            "available_at": pl.Datetime("us", "UTC"),
            "entry_ts": pl.Datetime("us", "UTC"),
            "score": pl.Float64,
            "cross_section_rank": pl.Int64,
            "selected": pl.Boolean,
            "target_weight": pl.Float64,
            "fold": pl.Int64,
            "split": pl.String,
            "model_hash": pl.String,
            "config_hash": pl.String,
        },
    ).sort(["fold", "split", "entry_ts", "cross_section_rank", "symbol"])


def publish_replay_signal_frame(exchange_dir: Path, output_path: Path) -> pl.DataFrame:
    """Atomically publish or verify an immutable portable replay-signal handoff."""
    frame = replay_signal_frame(exchange_dir)
    output_path = Path(output_path)
    if output_path.suffix.lower() != ".parquet":
        raise MLContractError("replay handoff output must use a .parquet suffix")
    if output_path.is_symlink():
        raise MLContractError("replay handoff output may not be a symlink")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
    )
    os.close(fd)
    temp = Path(raw_temp)
    try:
        frame.write_parquet(temp)
        if output_path.exists():
            if sha256_file(output_path) == sha256_file(temp):
                return frame
            raise MLContractError(
                f"immutable replay handoff {output_path} already exists with different bytes"
            )
        try:
            os.link(temp, output_path)
        except FileExistsError:
            if sha256_file(output_path) != sha256_file(temp):
                raise MLContractError(
                    f"replay handoff {output_path} was concurrently published differently"
                ) from None
    finally:
        temp.unlink(missing_ok=True)
    return frame
