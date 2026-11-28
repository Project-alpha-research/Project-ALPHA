"""Result-bundle validation for the isolated Qlib worker exchange.

Checks result.json, predictions.parquet and the optional ensemble diagnostics against the
validated request. Like ml_contract, it never imports Qlib, LightGBM or the worker package.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from alpha_cli.ml_contract import (
    _HASH,
    DECISION_CLOSE_OFFSET,
    ENSEMBLE_DIAGNOSTIC_COLUMNS,
    PREDICTION_COLUMNS,
    InputAnchor,
    MLContractError,
    ValidatedRequest,
    ValidatedResult,
    _load_json,
    _read_parquet,
    _require_exact_keys,
    _validate_folds,
    _validate_portable_files,
    sha256_file,
    validate_request_bundle,
)

_PREDICTION_SORT = ["fold", "split", "target_ts", "symbol", "origin_ts"]
_RESULT_FIELDS = {
    "schema_version",
    "status",
    "request_sha256",
    "snapshot_hash",
    "config_hash",
    "worker_lock_hash",
    "seed",
    "worker",
    "predictions",
    "diagnostics",
    "diagnostic_only",
    "counterfactual_refit",
}
_RESULT_V2_FIELDS = _RESULT_FIELDS | {"ensemble_diagnostics"}


def _expected_prediction_schema() -> dict[str, Any]:
    utc = pl.Datetime("us", "UTC")
    return {
        "symbol": pl.String,
        "origin_ts": utc,
        "available_at": utc,
        "target_ts": utc,
        "score": pl.Float64,
        "fold": pl.Int64,
        "split": pl.String,
        "model_hash": pl.String,
        "config_hash": pl.String,
        "worker_lock_hash": pl.String,
        "seed": pl.Int64,
    }


def _validate_result_payload(
    validated_request: ValidatedRequest,
    result: dict[str, Any],
    predictions: pl.DataFrame,
    *,
    exchange_dir: Path,
) -> None:
    request_schema = int(validated_request.request["schema_version"])
    expected_fields = _RESULT_V2_FIELDS if request_schema == 2 else _RESULT_FIELDS
    _require_exact_keys(result, expected_fields, "result")
    if result["schema_version"] != request_schema:
        raise MLContractError("result schema_version is unsupported")
    if result["status"] != "succeeded":
        raise MLContractError("result status must be 'succeeded'")
    request = validated_request.request
    expected_scalars = {
        "request_sha256": sha256_file(exchange_dir / "request.json"),
        "snapshot_hash": request["snapshot_hash"],
        "config_hash": request["config_hash"],
        "worker_lock_hash": request["worker_lock_hash"],
        "seed": request["seed"],
    }
    for name, expected in expected_scalars.items():
        if result[name] != expected:
            raise MLContractError(f"result {name} mismatch: expected {expected!r}")
    worker = _require_exact_keys(
        result["worker"], {"kind", "implementation_version"}, "result.worker"
    )
    if worker["kind"] not in {"fake", "qlib"} or not isinstance(
        worker["implementation_version"], str
    ):
        raise MLContractError("result.worker must identify fake or qlib and a version string")
    prediction_meta = _require_exact_keys(
        result["predictions"], {"path", "sha256", "rows"}, "result.predictions"
    )
    if prediction_meta["path"] != "predictions.parquet":
        raise MLContractError("result.predictions.path must be exactly 'predictions.parquet'")
    if prediction_meta["sha256"] != sha256_file(exchange_dir / "predictions.parquet"):
        raise MLContractError("prediction hash does not match predictions.parquet")
    if prediction_meta["rows"] != predictions.height:
        raise MLContractError("result.predictions.rows does not match predictions.parquet")
    if not isinstance(result["diagnostics"], dict):
        raise MLContractError("result.diagnostics must be a portable JSON object")
    if result["diagnostic_only"] is not True or result["counterfactual_refit"] is not False:
        raise MLContractError(
            "worker results must remain diagnostic_only with counterfactual_refit=false"
        )


def _expected_ensemble_diagnostic_schema() -> dict[str, Any]:
    utc = pl.Datetime("us", "UTC")
    return {
        "symbol": pl.String,
        "origin_ts": utc,
        "available_at": utc,
        "target_ts": utc,
        "fold": pl.Int64,
        "split": pl.String,
        "lightgbm_score": pl.Float64,
        "ridge_score": pl.Float64,
        "lightgbm_rank": pl.Float64,
        "ridge_rank": pl.Float64,
        "ensemble_score": pl.Float64,
        "disagreement": pl.Float64,
        "lightgbm_model_hash": pl.String,
        "ridge_model_hash": pl.String,
        "ensemble_model_hash": pl.String,
        "config_hash": pl.String,
        "worker_lock_hash": pl.String,
        "seed": pl.Int64,
    }


def _validate_ensemble_diagnostics(
    validated: ValidatedRequest,
    result: dict[str, Any],
    predictions: pl.DataFrame,
    diagnostics: pl.DataFrame,
    *,
    exchange_dir: Path,
) -> None:
    metadata = _require_exact_keys(
        result["ensemble_diagnostics"],
        {"schema", "schema_version", "path", "sha256", "rows"},
        "result.ensemble_diagnostics",
    )
    if metadata["schema"] != "QlibRankEnsembleDiagnosticsV1" or metadata["schema_version"] != 1:
        raise MLContractError("unsupported ensemble diagnostic schema")
    if metadata["path"] != "ensemble_diagnostics.parquet":
        raise MLContractError("ensemble diagnostic path must be ensemble_diagnostics.parquet")
    path = exchange_dir / "ensemble_diagnostics.parquet"
    if metadata["sha256"] != sha256_file(path) or metadata["rows"] != diagnostics.height:
        raise MLContractError("ensemble diagnostic hash or row count mismatch")
    if diagnostics.columns != ENSEMBLE_DIAGNOSTIC_COLUMNS:
        raise MLContractError("ensemble diagnostics columns do not match v1")
    if diagnostics.schema != _expected_ensemble_diagnostic_schema():
        raise MLContractError("ensemble diagnostics schema does not match v1")
    if diagnostics.height != predictions.height or any(
        count > 0 for count in diagnostics.null_count().row(0)
    ):
        raise MLContractError("ensemble diagnostics must align one-for-one without nulls")
    numeric = [
        "lightgbm_score",
        "ridge_score",
        "lightgbm_rank",
        "ridge_rank",
        "ensemble_score",
        "disagreement",
    ]
    if not all(diagnostics.get_column(name).is_finite().all() for name in numeric):
        raise MLContractError("ensemble diagnostic scores must be finite")
    if diagnostics.filter(
        (pl.col("lightgbm_rank") < 0)
        | (pl.col("lightgbm_rank") > 1)
        | (pl.col("ridge_rank") < 0)
        | (pl.col("ridge_rank") > 1)
        | (pl.col("disagreement") < 0)
        | (pl.col("disagreement") > 1)
    ).height:
        raise MLContractError("ensemble ranks and disagreement must lie in [0, 1]")
    keys = ["symbol", "origin_ts", "available_at", "target_ts", "fold", "split"]
    if not diagnostics.select(keys).equals(predictions.select(keys)):
        raise MLContractError("ensemble diagnostic keys must match canonical predictions")
    if not diagnostics.get_column("ensemble_score").equals(predictions.get_column("score")):
        raise MLContractError("ensemble_score must equal canonical prediction score")
    if not diagnostics.get_column("ensemble_model_hash").equals(
        predictions.get_column("model_hash")
    ):
        raise MLContractError("ensemble model hash must equal canonical prediction model_hash")
    if diagnostics.get_column("config_hash").unique().to_list() != [
        validated.request["config_hash"]
    ]:
        raise MLContractError("ensemble diagnostic config_hash mismatch")


def _validate_predictions(validated: ValidatedRequest, predictions: pl.DataFrame) -> None:
    if predictions.columns != PREDICTION_COLUMNS:
        raise MLContractError(
            f"predictions.parquet must have exact columns {PREDICTION_COLUMNS}, "
            f"got {predictions.columns}"
        )
    expected_schema = _expected_prediction_schema()
    if predictions.schema != expected_schema:
        raise MLContractError(
            "predictions.parquet schema mismatch: "
            f"expected {expected_schema}, got {predictions.schema}"
        )
    if any(count > 0 for count in predictions.null_count().row(0)):
        raise MLContractError("predictions.parquet canonical columns may not contain nulls")
    if predictions.is_empty():
        raise MLContractError("predictions.parquet may not be empty")
    duplicate_keys = ["symbol", "origin_ts", "target_ts", "fold", "split"]
    if predictions.select(duplicate_keys).is_duplicated().any():
        raise MLContractError("predictions.parquet contains a duplicate prediction key")
    if not predictions.get_column("score").is_finite().all():
        raise MLContractError("prediction scores must all be finite")

    request = validated.request
    fold_defs = _validate_folds(request, validated.sessions)
    declared_folds = set(fold_defs)
    actual_folds = set(predictions.get_column("fold").unique().to_list())
    if actual_folds != declared_folds:
        raise MLContractError("predictions must cover every declared fold exactly")
    splits = set(predictions.get_column("split").unique().to_list())
    if splits != {"test"}:
        raise MLContractError(
            "prediction split set must contain exactly the starter OOS 'test' split"
        )
    for name in ("model_hash", "config_hash", "worker_lock_hash"):
        values = predictions.get_column(name).unique().to_list()
        if any(not isinstance(value, str) or _HASH.fullmatch(value) is None for value in values):
            raise MLContractError(f"prediction {name} values must be SHA-256 hex digests")
    model_counts = predictions.group_by("fold").agg(pl.col("model_hash").n_unique())
    if model_counts.filter(pl.col("model_hash") != 1).height:
        raise MLContractError("each prediction fold must carry exactly one model_hash")
    if predictions.get_column("config_hash").unique().to_list() != [request["config_hash"]]:
        raise MLContractError("prediction config_hash does not match the request")
    if predictions.get_column("worker_lock_hash").unique().to_list() != [
        request["worker_lock_hash"]
    ]:
        raise MLContractError("prediction worker_lock_hash does not match the request")
    if predictions.get_column("seed").unique().to_list() != [request["seed"]]:
        raise MLContractError("prediction seed does not match the request")

    if predictions.select(["symbol", "target_ts"]).is_duplicated().any():
        raise MLContractError("prediction target overlap: a symbol/target appears more than once")
    session_position = {session: index for index, session in enumerate(validated.sessions)}
    panel_availability = {
        (row[0], row[1]): row[2]
        for row in validated.panel.select("symbol", "session_ts", "available_at").iter_rows()
    }
    universe_set = set(validated.universe)
    grouped_symbols: dict[tuple[int, str, datetime], set[str]] = {}
    for row in predictions.iter_rows(named=True):
        symbol = row["symbol"]
        origin = row["origin_ts"]
        available = row["available_at"]
        target = row["target_ts"]
        fold_id = row["fold"]
        split = row["split"]
        if symbol not in universe_set:
            raise MLContractError(f"prediction symbol {symbol!r} is outside the frozen universe")
        if available > origin + DECISION_CLOSE_OFFSET:
            raise MLContractError("prediction available_at may not be later than decision close")
        expected_available = panel_availability.get((symbol, origin))
        if expected_available is None or expected_available != available:
            raise MLContractError(
                "prediction available_at must equal the source panel availability at origin_ts"
            )
        target_index = session_position.get(target)
        origin_index = session_position.get(origin)
        if target_index is None or origin_index is None or target_index != origin_index + 1:
            raise MLContractError(
                "prediction target_ts must be the aligned session immediately after origin_ts"
            )
        if target_index + 1 >= len(validated.sessions):
            raise MLContractError(
                "prediction target_ts must have a following aligned open for its open-to-open label"
            )
        fold = fold_defs[fold_id]
        window_start = fold[f"{split}_start"]
        window_end = fold[f"{split}_end"]
        if not window_start <= target <= window_end:
            raise MLContractError(
                f"prediction target_ts is outside declared fold {fold_id} {split} window"
            )
        key = (fold_id, split, target)
        grouped_symbols.setdefault(key, set()).add(symbol)
    for key, symbols in grouped_symbols.items():
        if symbols != universe_set:
            raise MLContractError(
                f"prediction cross-section {key} must contain the complete frozen universe"
            )
    expected_cross_sections = {
        (fold_id, "test", session)
        for fold_id, fold in fold_defs.items()
        for session in validated.sessions
        if fold["test_start"] <= session <= fold["test_end"]
    }
    actual_cross_sections = set(grouped_symbols)
    if actual_cross_sections != expected_cross_sections:
        missing = len(expected_cross_sections - actual_cross_sections)
        unexpected = len(actual_cross_sections - expected_cross_sections)
        raise MLContractError(
            "predictions must contain the exact declared OOS target grid "
            f"(missing={missing}, unexpected={unexpected})"
        )
    if not predictions.equals(predictions.sort(_PREDICTION_SORT)):
        raise MLContractError(f"predictions.parquet must be sorted by {_PREDICTION_SORT}")


def validate_result_bundle(
    exchange_dir: Path, *, expected_input_anchor: InputAnchor | None = None
) -> ValidatedResult:
    exchange_dir = Path(exchange_dir)
    validated_request = validate_request_bundle(
        exchange_dir, expected_input_anchor=expected_input_anchor
    )
    _validate_portable_files(exchange_dir)
    result = _load_json(exchange_dir / "result.json", canonical=True)
    predictions = _read_parquet(exchange_dir / "predictions.parquet", "predictions")
    _validate_result_payload(validated_request, result, predictions, exchange_dir=exchange_dir)
    _validate_predictions(validated_request, predictions)
    ensemble_diagnostics: pl.DataFrame | None = None
    if validated_request.request["schema_version"] == 2:
        ensemble_diagnostics = _read_parquet(
            exchange_dir / "ensemble_diagnostics.parquet", "ensemble diagnostics"
        )
        _validate_ensemble_diagnostics(
            validated_request,
            result,
            predictions,
            ensemble_diagnostics,
            exchange_dir=exchange_dir,
        )
    return ValidatedResult(
        request=validated_request,
        result=result,
        predictions=predictions,
        ensemble_diagnostics=ensemble_diagnostics,
    )
