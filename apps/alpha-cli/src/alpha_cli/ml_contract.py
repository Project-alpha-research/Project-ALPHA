"""Portable JSON/Parquet contract for the isolated Qlib worker.

This module deliberately depends only on the ALPHA CLI's normal lightweight stack.  It never
imports Qlib, LightGBM, or the worker package and it never deserializes executable model objects.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

import polars as pl

CONTRACT_SCHEMA_VERSION = 1
SUPPORTED_CONTRACT_SCHEMA_VERSIONS = frozenset({1, 2, 3})
INPUT_ANCHOR_FILENAME = "input_anchor.json"
# The hold-back record an exported bundle carries; prepare copies it so the replay run records it.
RESERVE_FILENAME = "reserve.json"
MIN_SYMBOLS = 20
MIN_ALIGNED_SESSIONS = 756
MIN_LABEL_BOUNDARY_GAP_SESSIONS = 1
DECISION_CLOSE_OFFSET = timedelta(hours=23)

PANEL_COLUMNS = [
    "symbol",
    "session_ts",
    "available_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
]
PREDICTION_COLUMNS = [
    "symbol",
    "origin_ts",
    "available_at",
    "target_ts",
    "score",
    "fold",
    "split",
    "model_hash",
    "config_hash",
    "worker_lock_hash",
    "seed",
]
ENSEMBLE_DIAGNOSTIC_COLUMNS = [
    "symbol",
    "origin_ts",
    "available_at",
    "target_ts",
    "fold",
    "split",
    "lightgbm_score",
    "ridge_score",
    "lightgbm_rank",
    "ridge_rank",
    "ensemble_score",
    "disagreement",
    "lightgbm_model_hash",
    "ridge_model_hash",
    "ensemble_model_hash",
    "config_hash",
    "worker_lock_hash",
    "seed",
]

_PANEL_SORT = ["session_ts", "symbol"]
_HASH = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,31}$")
_SAFE_SUFFIXES = {".json", ".parquet"}
_MODEL_PARAMETER_RULES: dict[str, tuple[float, float, bool]] = {
    "bagging_fraction": (0.01, 1.0, False),
    "early_stopping_rounds": (1.0, 1000.0, True),
    "feature_fraction": (0.01, 1.0, False),
    "lambda_l1": (0.0, 1_000_000.0, False),
    "lambda_l2": (0.0, 1_000_000.0, False),
    "learning_rate": (0.0001, 1.0, False),
    "max_depth": (-1.0, 64.0, True),
    "min_data_in_leaf": (1.0, 1_000_000.0, True),
    "num_boost_round": (1.0, 5000.0, True),
    "num_leaves": (2.0, 4096.0, True),
    "num_threads": (1.0, 8.0, True),
}

_TABULAR_PARAMETER_RULES: dict[str, dict[str, tuple[float, float, bool]]] = {
    "lightgbm": _MODEL_PARAMETER_RULES,
    "linear": {"alpha": (0.0, 1_000_000.0, False)},
    "catboost": {
        "num_boost_round": (1.0, 5000.0, True),
        "early_stopping_rounds": (1.0, 1000.0, True),
        "depth": (1.0, 10.0, True),
        "learning_rate": (0.0001, 1.0, False),
        "l2_leaf_reg": (0.0, 1_000_000.0, False),
        "num_threads": (1.0, 8.0, True),
    },
    "xgboost": {
        "num_boost_round": (1.0, 5000.0, True),
        "early_stopping_rounds": (1.0, 1000.0, True),
        "max_depth": (1.0, 16.0, True),
        "learning_rate": (0.0001, 1.0, False),
        "subsample": (0.01, 1.0, False),
        "colsample_bytree": (0.01, 1.0, False),
        "reg_alpha": (0.0, 1_000_000.0, False),
        "reg_lambda": (0.0, 1_000_000.0, False),
        "num_threads": (1.0, 8.0, True),
    },
    "double_ensemble": {**_MODEL_PARAMETER_RULES, "num_models": (2.0, 6.0, True)},
}

_REQUEST_FIELDS = {
    "schema_version",
    "snapshot_hash",
    "universe",
    "universe_membership",
    "survivorship_warning",
    "feature_recipe",
    "label_recipe",
    "model",
    "portfolio",
    "costs",
    "folds",
    "purge_sessions",
    "embargo_sessions",
    "seed",
    "worker_lock_hash",
    "panel",
    "config_hash",
}
_DRAFT_FIELDS = _REQUEST_FIELDS - {"panel", "config_hash"}
_FOLD_FIELDS = {
    "fold",
    "train_start",
    "train_end",
    "validation_start",
    "validation_end",
    "test_start",
    "test_end",
}
_INPUT_ANCHOR_FIELDS = {"schema_version", "request_sha256", "panel_sha256"}


def tabular_model_names() -> tuple[str, ...]:
    """Names accepted by the exchange contract, without runtime availability claims."""
    return tuple(_TABULAR_PARAMETER_RULES)


class MLContractError(ValueError):
    """An exchange bundle is unsafe, corrupt, non-canonical, or semantically invalid."""


@dataclass(frozen=True)
class ValidatedRequest:
    request: dict[str, Any]
    panel: pl.DataFrame
    universe: tuple[str, ...]
    sessions: tuple[datetime, ...]

    @property
    def membership_status(self) -> str:
        """Describe the request's membership claim without upgrading its evidence."""
        if self.request["universe_membership"] == "point_in_time":
            return "declared_unverified"
        return "current_membership_warning"


@dataclass(frozen=True)
class ValidatedResult:
    request: ValidatedRequest
    result: dict[str, Any]
    predictions: pl.DataFrame
    ensemble_diagnostics: pl.DataFrame | None


@dataclass(frozen=True)
class InputAnchor:
    """ALPHA-owned hashes of the exact request bytes handed to the isolated worker."""

    request_sha256: str
    panel_sha256: str
    schema_version: int = CONTRACT_SCHEMA_VERSION


def _reject_constant(value: str) -> NoReturn:
    raise MLContractError(f"JSON contains forbidden non-finite constant {value}")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MLContractError(f"JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _load_json(path: Path, *, canonical: bool) -> dict[str, Any]:
    if not path.is_file():
        raise MLContractError(f"missing required {path.name}")
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw,
            parse_constant=_reject_constant,
            object_pairs_hook=_pairs_no_duplicates,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MLContractError(f"invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise MLContractError(f"{path.name} must contain a JSON object")
    if canonical and raw != canonical_json_bytes(value):
        raise MLContractError(
            f"{path.name} is not canonical JSON (sorted keys, compact separators, trailing newline)"
        )
    return value


def canonical_json_bytes(value: object) -> bytes:
    """RFC-8259-safe, byte-stable JSON used for every exchange control record."""
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MLContractError(f"value is not canonical-JSON encodable: {exc}") from exc
    return (encoded + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise MLContractError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def compute_config_hash(request: dict[str, Any]) -> str:
    """Hash every immutable request field except the hash itself."""
    payload = copy.deepcopy(request)
    payload.pop("config_hash", None)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _require_exact_keys(value: object, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MLContractError(f"{label} must be a JSON object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise MLContractError(f"{label} fields mismatch: missing={missing}, extra={extra}")
    return value


def _require_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MLContractError(f"{label} must be an integer >= {minimum}")
    return value


def _require_number(value: object, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MLContractError(f"{label} must be a finite number >= {minimum}")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise MLContractError(f"{label} must be a finite number >= {minimum}")
    return result


def _as_finite_float(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MLContractError(f"{label} is unavailable")
    result = float(value)
    if not math.isfinite(result):
        raise MLContractError(f"{label} is not finite")
    return result


def _require_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise MLContractError(f"{label} must be a lowercase 64-character SHA-256 hex digest")
    return value


def _parse_ts(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise MLContractError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MLContractError(f"{label} must be an ISO-8601 timestamp") from exc
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None:
        raise MLContractError(f"{label} must be timezone-aware")
    if offset.total_seconds() != 0:
        raise MLContractError(f"{label} must use UTC")
    return parsed


def _validate_portable_files(exchange_dir: Path) -> None:
    if not exchange_dir.is_dir():
        raise MLContractError(f"exchange directory does not exist: {exchange_dir}")
    for path in exchange_dir.rglob("*"):
        if path.is_symlink():
            raise MLContractError(f"exchange bundle may not contain symlinks: {path.name}")
        if path.is_file() and path.suffix.lower() not in _SAFE_SUFFIXES:
            raise MLContractError(
                f"exchange files must be portable JSON and Parquet only; found {path.name}"
            )


def _input_anchor_payload(exchange_dir: Path) -> dict[str, object]:
    request = _load_json(exchange_dir / "request.json", canonical=True)
    schema_version = _require_int(
        request.get("schema_version"), "request schema_version", minimum=1
    )
    if schema_version not in SUPPORTED_CONTRACT_SCHEMA_VERSIONS:
        raise MLContractError(f"unsupported request schema_version {schema_version}")
    return {
        "schema_version": schema_version,
        "request_sha256": sha256_file(exchange_dir / "request.json"),
        "panel_sha256": sha256_file(exchange_dir / "panel.parquet"),
    }


def _write_input_anchor(exchange_dir: Path) -> InputAnchor:
    payload = _input_anchor_payload(exchange_dir)
    (exchange_dir / INPUT_ANCHOR_FILENAME).write_bytes(canonical_json_bytes(payload))
    return InputAnchor(
        request_sha256=str(payload["request_sha256"]),
        panel_sha256=str(payload["panel_sha256"]),
        schema_version=_require_int(
            payload["schema_version"], "input anchor schema_version", minimum=1
        ),
    )


def validate_input_anchor(exchange_dir: Path) -> InputAnchor:
    """Verify the persisted ALPHA input anchor against the current request and panel bytes."""
    exchange_dir = Path(exchange_dir)
    payload = _require_exact_keys(
        _load_json(exchange_dir / INPUT_ANCHOR_FILENAME, canonical=True),
        _INPUT_ANCHOR_FIELDS,
        "input anchor",
    )
    if payload["schema_version"] not in SUPPORTED_CONTRACT_SCHEMA_VERSIONS:
        raise MLContractError("input anchor schema_version is unsupported")
    anchor = InputAnchor(
        request_sha256=_require_hash(payload["request_sha256"], "input anchor request_sha256"),
        panel_sha256=_require_hash(payload["panel_sha256"], "input anchor panel_sha256"),
        schema_version=_require_int(
            payload["schema_version"], "input anchor schema_version", minimum=1
        ),
    )
    actual = _input_anchor_payload(exchange_dir)
    if anchor.request_sha256 != actual["request_sha256"]:
        raise MLContractError("request.json no longer matches the ALPHA input anchor")
    if anchor.panel_sha256 != actual["panel_sha256"]:
        raise MLContractError("panel.parquet no longer matches the ALPHA input anchor")
    return anchor


def _expected_panel_schema() -> dict[str, Any]:
    utc = pl.Datetime("us", "UTC")
    return {
        "symbol": pl.String,
        "session_ts": utc,
        "available_at": utc,
        "open": pl.Float64,
        "high": pl.Float64,
        "low": pl.Float64,
        "close": pl.Float64,
        "volume": pl.Float64,
    }


def _read_parquet(path: Path, label: str) -> pl.DataFrame:
    if not path.is_file():
        raise MLContractError(f"missing required {label}: {path.name}")
    try:
        return pl.read_parquet(path)
    except Exception as exc:
        raise MLContractError(f"cannot read {label} {path.name}: {exc}") from exc


def _validate_panel(panel: pl.DataFrame, universe: tuple[str, ...]) -> tuple[datetime, ...]:
    if panel.columns != PANEL_COLUMNS:
        raise MLContractError(
            f"panel.parquet must have exact columns {PANEL_COLUMNS}, got {panel.columns}"
        )
    expected_schema = _expected_panel_schema()
    if panel.schema != expected_schema:
        raise MLContractError(
            f"panel.parquet schema mismatch: expected {expected_schema}, got {panel.schema}"
        )
    if any(count > 0 for count in panel.null_count().row(0)):
        raise MLContractError("panel.parquet canonical columns may not contain nulls")
    if not panel.equals(panel.sort(_PANEL_SORT)):
        raise MLContractError(f"panel.parquet must be sorted by {_PANEL_SORT}")
    if panel.select(["session_ts", "symbol"]).is_duplicated().any():
        raise MLContractError("panel.parquet contains duplicate (session_ts, symbol) keys")

    panel_symbols = tuple(panel.get_column("symbol").unique().sort().to_list())
    if panel_symbols != universe:
        raise MLContractError("panel.parquet symbols must exactly match the frozen universe")
    sessions = tuple(panel.get_column("session_ts").unique(maintain_order=True).to_list())
    if len(sessions) < MIN_ALIGNED_SESSIONS:
        raise MLContractError(
            f"starter experiment requires at least {MIN_ALIGNED_SESSIONS} aligned sessions; "
            f"got {len(sessions)}"
        )
    expected_rows = len(universe) * len(sessions)
    if panel.height != expected_rows:
        raise MLContractError(
            "panel.parquet is not a fully aligned symbol/session rectangle: "
            f"expected {expected_rows} rows, got {panel.height}"
        )

    finite = panel.select(
        [
            pl.col(name).is_finite().all().alias(name)
            for name in ("open", "high", "low", "close", "volume")
        ]
    ).row(0)
    if not all(finite):
        raise MLContractError("panel OHLCV values must all be finite")
    if panel.filter(
        (pl.col("open") <= 0)
        | (pl.col("high") <= 0)
        | (pl.col("low") <= 0)
        | (pl.col("close") <= 0)
        | (pl.col("volume") < 0)
        | (pl.col("low") > pl.min_horizontal("open", "close"))
        | (pl.col("high") < pl.max_horizontal("open", "close"))
        | (pl.col("low") > pl.col("high"))
    ).height:
        raise MLContractError("panel.parquet contains invalid OHLCV geometry")
    if panel.filter(pl.col("available_at") != pl.col("session_ts") + pl.duration(hours=23)).height:
        raise MLContractError(
            "panel available_at must equal the canonical session close (session_ts + 23h)"
        )
    return sessions


def _validate_recipe_objects(request: dict[str, Any]) -> None:
    feature = _require_exact_keys(
        request["feature_recipe"], {"name", "version", "parameters"}, "feature_recipe"
    )
    if (
        feature["name"] != "alpha158"
        or type(feature["version"]) is not int
        or feature["version"] not in (1, 2, 3)
    ):
        raise MLContractError("feature_recipe must be alpha158 with integer version 1, 2 or 3")
    if feature["parameters"] != {}:
        raise MLContractError(
            "alpha158 has a fixed versioned recipe; feature_recipe.parameters must be empty"
        )

    label = _require_exact_keys(
        request["label_recipe"],
        {"name", "decision", "fill", "horizon_sessions"},
        "label_recipe",
    )
    expected_label = {
        "name": "next_session_open_to_open",
        "decision": "close_t",
        "fill": "open_t_plus_1",
        "horizon_sessions": 1,
    }
    if label != expected_label:
        raise MLContractError(
            "starter label_recipe must be next-session open-to-open for a "
            "close-t decision/open-t+1 fill"
        )

    model = _require_exact_keys(request["model"], {"name", "parameters"}, "model")
    if request["schema_version"] == 1 and (
        model["name"] != "lightgbm" or not isinstance(model["parameters"], dict)
    ):
        raise MLContractError("starter model must be lightgbm with a parameters object")
    if request["schema_version"] == 2 and (
        model["name"] != "rank_ensemble_v1" or not isinstance(model["parameters"], dict)
    ):
        raise MLContractError("schema v2 model must be rank_ensemble_v1 with a parameters object")
    rules = _MODEL_PARAMETER_RULES
    if request["schema_version"] == 3:
        if (
            not isinstance(model["name"], str)
            or model["name"] not in _TABULAR_PARAMETER_RULES
            or not isinstance(model["parameters"], dict)
        ):
            raise MLContractError("unsupported tabular model recipe")
        rules = _TABULAR_PARAMETER_RULES[model["name"]]
    allowed = set(rules)
    if request["schema_version"] == 3 and model["name"] == "linear":
        allowed.add("estimator")
        estimator = model["parameters"].get("estimator", "ridge")
        if not isinstance(estimator, str) or estimator not in {"ols", "ridge", "lasso", "nnls"}:
            raise MLContractError("linear estimator must be ols, ridge, lasso or nnls")
        if estimator in {"ols", "nnls"} and model["parameters"].get("alpha", 0) != 0:
            raise MLContractError("linear alpha is only supported for ridge or lasso")
    unknown_parameters = sorted(set(model["parameters"]) - allowed)
    if unknown_parameters:
        raise MLContractError(f"unsupported LightGBM parameters: {unknown_parameters}")
    for name, value in model["parameters"].items():
        if request["schema_version"] == 3 and model["name"] == "linear" and name == "estimator":
            continue
        minimum, maximum, integer = rules[name]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise MLContractError(f"model.parameters.{name} must be a finite number")
        number = float(value)
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise MLContractError(
                f"model.parameters.{name} must be between {minimum} and {maximum}"
            )
        if integer and not number.is_integer():
            raise MLContractError(f"model.parameters.{name} must be an integer")
    portfolio = _require_exact_keys(
        request["portfolio"], {"selection", "weighting", "long_only"}, "portfolio"
    )
    if portfolio != {
        "selection": "top_quintile",
        "weighting": "equal",
        "long_only": True,
    }:
        raise MLContractError("starter portfolio must be long-only, equal-weight, top-quintile")
    costs = _require_exact_keys(request["costs"], {"fee_bps", "slippage_bps"}, "costs")
    _require_number(costs["fee_bps"], "costs.fee_bps")
    _require_number(costs["slippage_bps"], "costs.slippage_bps")


def _validate_folds(
    request: dict[str, Any], sessions: tuple[datetime, ...]
) -> dict[int, dict[str, Any]]:
    raw_folds = request["folds"]
    if not isinstance(raw_folds, list) or not raw_folds:
        raise MLContractError("folds must be a non-empty array")
    purge = max(
        _require_int(request["purge_sessions"], "purge_sessions"),
        MIN_LABEL_BOUNDARY_GAP_SESSIONS,
    )
    embargo = max(
        _require_int(request["embargo_sessions"], "embargo_sessions"),
        MIN_LABEL_BOUNDARY_GAP_SESSIONS,
    )
    positions = {session: index for index, session in enumerate(sessions)}
    resolved: dict[int, dict[str, Any]] = {}
    previous_test_end = -1
    for expected_fold, raw in enumerate(raw_folds):
        fold = _require_exact_keys(raw, _FOLD_FIELDS, f"folds[{expected_fold}]")
        fold_id = _require_int(fold["fold"], f"folds[{expected_fold}].fold")
        if fold_id != expected_fold:
            raise MLContractError("fold ids must be unique, sorted, and contiguous from zero")
        parsed = {
            name: _parse_ts(fold[name], f"folds[{fold_id}].{name}")
            for name in _FOLD_FIELDS - {"fold"}
        }
        try:
            indices = {name: positions[value] for name, value in parsed.items()}
        except KeyError as exc:
            raise MLContractError(
                f"fold {fold_id} boundary {exc.args[0].isoformat()} is not an aligned session"
            ) from None
        if not (
            indices["train_start"]
            <= indices["train_end"]
            < indices["validation_start"]
            <= indices["validation_end"]
            < indices["test_start"]
            <= indices["test_end"]
        ):
            raise MLContractError(
                f"fold {fold_id} must order non-empty train, validation, and test windows"
            )
        purge_gap = indices["validation_start"] - indices["train_end"] - 1
        embargo_gap = indices["test_start"] - indices["validation_end"] - 1
        if purge_gap < purge:
            raise MLContractError(
                f"fold {fold_id} provides {purge_gap} purge sessions, requires {purge}"
            )
        if embargo_gap < embargo:
            raise MLContractError(
                f"fold {fold_id} provides {embargo_gap} embargo sessions, requires {embargo}"
            )
        if indices["test_start"] <= previous_test_end:
            raise MLContractError(
                "fold test windows must be strictly increasing and non-overlapping"
            )
        if indices["test_end"] >= len(sessions) - 1:
            raise MLContractError(
                f"fold {fold_id} test_end must retain a following aligned open for every target"
            )
        previous_test_end = indices["test_end"]
        resolved[fold_id] = {**fold, **parsed}
    return resolved


def _validate_request_payload(
    request: dict[str, Any], panel: pl.DataFrame, *, verify_config_hash: bool = True
) -> ValidatedRequest:
    _require_exact_keys(request, _REQUEST_FIELDS, "request")
    if request["schema_version"] not in SUPPORTED_CONTRACT_SCHEMA_VERSIONS:
        raise MLContractError(
            f"unsupported request schema_version {request['schema_version']!r}; "
            f"expected one of {sorted(SUPPORTED_CONTRACT_SCHEMA_VERSIONS)}"
        )
    _require_hash(request["snapshot_hash"], "snapshot_hash")
    _require_hash(request["worker_lock_hash"], "worker_lock_hash")
    _require_int(request["seed"], "seed")
    universe_raw = request["universe"]
    if not isinstance(universe_raw, list) or not all(isinstance(s, str) for s in universe_raw):
        raise MLContractError("universe must be an array of symbols")
    universe = tuple(universe_raw)
    if len(universe) < MIN_SYMBOLS:
        raise MLContractError(
            f"starter experiment requires at least {MIN_SYMBOLS} symbols; got {len(universe)}"
        )
    if tuple(sorted(set(universe))) != universe or any(
        _SYMBOL.fullmatch(s) is None for s in universe
    ):
        raise MLContractError("universe symbols must be valid, sorted, and unique")
    membership = request["universe_membership"]
    warning = request["survivorship_warning"]
    if membership not in {"point_in_time", "current_membership"}:
        raise MLContractError("universe_membership must be 'point_in_time' or 'current_membership'")
    if membership == "current_membership" and (not isinstance(warning, str) or not warning.strip()):
        raise MLContractError(
            "current_membership requires a permanent non-empty survivorship_warning"
        )
    if warning is not None and not isinstance(warning, str):
        raise MLContractError("survivorship_warning must be null or a string")
    if request["schema_version"] == 3 and membership == "point_in_time":
        raise MLContractError("schema 3 point_in_time requires a verified membership schedule")
    _validate_recipe_objects(request)

    panel_meta = _require_exact_keys(request["panel"], {"path", "sha256", "rows"}, "panel")
    if panel_meta["path"] != "panel.parquet":
        raise MLContractError("panel.path must be exactly 'panel.parquet'")
    _require_hash(panel_meta["sha256"], "panel.sha256")
    if _require_int(panel_meta["rows"], "panel.rows", minimum=1) != panel.height:
        raise MLContractError("panel.rows does not match panel.parquet")
    sessions = _validate_panel(panel, universe)
    _validate_folds(request, sessions)
    expected_hash = compute_config_hash(request)
    if verify_config_hash and request["config_hash"] != expected_hash:
        raise MLContractError(
            f"config_hash mismatch: expected {expected_hash}, got {request['config_hash']!r}"
        )
    _require_hash(request["config_hash"], "config_hash")
    return ValidatedRequest(request=request, panel=panel, universe=universe, sessions=sessions)


def prepare_exchange(
    spec_path: Path,
    panel_path: Path,
    exchange_dir: Path,
    *,
    worker_lock_path: Path | None = None,
    model_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate source inputs and atomically publish an immutable worker request bundle."""
    spec_path = Path(spec_path)
    panel_path = Path(panel_path)
    exchange_dir = Path(exchange_dir)
    if exchange_dir.exists():
        raise MLContractError(f"exchange directory already exists: {exchange_dir}")
    if panel_path.is_symlink() or not panel_path.is_file():
        raise MLContractError(f"panel source must be a regular Parquet file: {panel_path}")
    draft = _load_json(spec_path, canonical=False)
    _require_exact_keys(draft, _DRAFT_FIELDS, "experiment spec")
    if draft.get("universe_membership") == "point_in_time":
        raise MLContractError(
            "point_in_time is unsupported for new requests: supported contracts do not "
            "carry a membership schedule; use current_membership only if that is the intended "
            "universe and retain its survivorship warning"
        )
    panel = _read_parquet(panel_path, "panel source")
    request = copy.deepcopy(draft)
    if model_override is not None:
        request["schema_version"] = 3
        request["model"] = copy.deepcopy(model_override)
    request["panel"] = {
        "path": "panel.parquet",
        "sha256": sha256_file(panel_path),
        "rows": panel.height,
    }
    if worker_lock_path is not None:
        worker_lock_path = Path(worker_lock_path)
        if worker_lock_path.is_symlink() or not worker_lock_path.is_file():
            raise MLContractError(f"worker lock must be a regular file: {worker_lock_path}")
        actual_lock_hash = sha256_file(worker_lock_path)
        if request["worker_lock_hash"] != actual_lock_hash:
            raise MLContractError(
                "worker_lock_hash does not match the supplied worker lock: "
                f"expected {actual_lock_hash}"
            )
    request["config_hash"] = compute_config_hash(request)
    _validate_request_payload(request, panel)

    exchange_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(
        tempfile.mkdtemp(prefix=f".{exchange_dir.name}.", suffix=".tmp", dir=exchange_dir.parent)
    )
    try:
        shutil.copyfile(panel_path, temp_dir / "panel.parquet")
        held = spec_path.parent / RESERVE_FILENAME
        if held.is_file() and not held.is_symlink():
            shutil.copyfile(held, temp_dir / RESERVE_FILENAME)
        (temp_dir / "request.json").write_bytes(canonical_json_bytes(request))
        _write_input_anchor(temp_dir)
        validate_request_bundle(temp_dir)
        os.replace(temp_dir, exchange_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return request


def validate_request_bundle(
    exchange_dir: Path,
    *,
    expected_input_anchor: InputAnchor | None = None,
    for_execution: bool = False,
) -> ValidatedRequest:
    exchange_dir = Path(exchange_dir)
    _validate_portable_files(exchange_dir)
    request_path = exchange_dir / "request.json"
    request = _load_json(request_path, canonical=True)
    panel = _read_parquet(exchange_dir / "panel.parquet", "panel")
    panel_meta = request.get("panel")
    if isinstance(panel_meta, dict) and panel_meta.get("sha256") != sha256_file(
        exchange_dir / "panel.parquet"
    ):
        raise MLContractError("panel hash does not match panel.parquet")
    validated = _validate_request_payload(request, panel)
    if for_execution and validated.membership_status == "declared_unverified":
        raise MLContractError(
            "point_in_time membership is declared but unverified; this frozen request is "
            "inspection-only and cannot be executed"
        )
    input_anchor = validate_input_anchor(exchange_dir)
    if expected_input_anchor is not None and input_anchor != expected_input_anchor:
        raise MLContractError("ALPHA input anchor changed after worker launch")
    return validated
