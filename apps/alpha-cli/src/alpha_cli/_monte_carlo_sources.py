"""Find and check the stored runs a Monte Carlo run is built from."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from alpha_cli import _artifacts, _forecast, _runner
from alpha_core import DataError


def _verified_validation_source(data_dir: Path, run_id: str) -> tuple[Path, dict[str, Any]]:
    rdir = _artifacts.find_run_dir(data_dir, run_id)
    if rdir is None:
        raise DataError(f"validation source run {run_id!r} was not found")
    manifest = _artifacts.read_manifest(rdir)
    if manifest.get("command") != "validate":
        raise DataError(f"source run {run_id!r} must be a completed validate run")
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("symbol"), str):
        raise DataError(f"source run {run_id!r} has invalid validation metadata")
    return rdir, manifest


def _verified_forecast_eval(
    data_dir: Path,
    run_id: str,
    *,
    source_manifest: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    rdir = _artifacts.find_run_dir(data_dir, run_id)
    if rdir is None:
        raise DataError(f"forecast evaluation run {run_id!r} was not found")
    manifest = _artifacts.read_manifest(rdir)
    if manifest.get("command") != "forecast_eval":
        raise DataError(f"run {run_id!r} must be a completed forecast_eval run")
    source_metadata = source_manifest["metadata"]
    # The cut-off dates may differ in name only (a weekend date names the same last bar); the
    # caller then checks that the evaluation hashed exactly the source run's bars.
    for label, source_value, eval_value in (
        ("symbol", source_metadata.get("symbol"), manifest.get("symbol")),
        ("snapshot", source_metadata.get("snapshot_id"), manifest.get("snapshot_id")),
    ):
        if source_value != eval_value:
            raise DataError(
                f"forecast evaluation {label} {eval_value!r} differs from source {source_value!r}"
            )
    return rdir, manifest


def _only_fitting_eval(data_dir: Path, source_manifest: dict[str, Any]) -> str:
    """The one stored forecast-eval run for the source run's symbol and bars, or say what to do."""
    metadata = source_manifest["metadata"]
    symbol = metadata.get("symbol")
    first = (
        f"run `alpha forecast eval {symbol}` first (a few minutes); it prints the id, "
        "then pass it with --forecast-eval-run"
    )
    fitting = []
    for path in sorted((data_dir / "forecast").glob("*/manifest.json")):
        manifest = _artifacts.read_manifest(path.parent)
        if (
            manifest.get("command") == "forecast_eval"
            and manifest.get("symbol") == symbol
            and manifest.get("snapshot_id") == metadata.get("snapshot_id")
        ):
            fitting.append(path.parent.name)
    if len(fitting) == 1:
        return fitting[0]
    if not fitting:
        raise DataError(f"--forecast-eval-run is missing: {first}")
    raise DataError(
        f"--forecast-eval-run is missing and {len(fitting)} stored evaluations fit "
        f"{symbol}: pass one of {', '.join(fitting)}"
    )


def _resolve_eval(
    data_dir: Path, source_manifest: dict[str, Any], given: str | None
) -> tuple[str, Path, dict[str, Any]]:
    """The forecast-eval run id (the one stored fitting run when none is given) and its files."""
    run_id = given
    if run_id is None:
        run_id = _only_fitting_eval(data_dir, source_manifest)
        typer.echo(
            f"Using forecast evaluation {run_id}: the only stored one for this symbol and "
            "these bars."
        )
    eval_dir, eval_manifest = _verified_forecast_eval(
        data_dir, run_id, source_manifest=source_manifest
    )
    return run_id, eval_dir, eval_manifest


def _horizon_steps(horizon: int | None, spec: _runner.RunSpec, future: int) -> int:
    """Sessions per path. Kronos re-reads its window at every step, so the cost grows with the
    tail: by default it makes the first test window only, and never more than its 512-bar window."""
    if horizon is None:
        return min(spec.embargo + spec.test_size + 1, future, _forecast.MAX_WINDOW)
    if horizon > min(future, _forecast.MAX_WINDOW):
        raise DataError(
            f"--horizon {horizon} is too long: the largest that works is "
            f"{min(future, _forecast.MAX_WINDOW)} (Kronos makes at most "
            f"{_forecast.MAX_WINDOW} sessions; the run has {future} after training)."
        )
    return horizon


def _spec_from_validation(manifest: dict[str, Any]) -> _runner.RunSpec:
    metadata = manifest["metadata"]
    raw_params = metadata.get("strategy_params", ())
    if not isinstance(raw_params, list | tuple):
        raise DataError("validation strategy_params must be a sequence")
    params = tuple((str(row[0]), float(row[1])) for row in raw_params)
    return _runner.RunSpec(
        lookback=int(metadata["lookback"]),
        skip=int(metadata["skip"]),
        vol_window=int(metadata["vol_window"]),
        # an `alpha test` run sizes all-in and stores no target volatility: that field goes unused
        target_vol=float(metadata.get("target_vol", 0.15)),
        rebalance_every=int(metadata["rebalance_every"]),
        max_leverage=float(metadata["max_leverage"]),
        allow_short=bool(metadata["allow_short"]),
        periods_per_year=int(metadata["periods_per_year"]),
        fee_bps=float(metadata["fee_bps"]),
        slippage_bps=float(metadata["slippage_bps"]),
        starting_cash=float(metadata["starting_cash"]),
        account_type=str(metadata["account_type"]),
        train_size=int(metadata["train_size"]),
        test_size=int(metadata["test_size"]),
        embargo=int(metadata["embargo"]),
        anchored=bool(metadata["anchored"]),
        strategy_name=str(metadata["strategy_name"]),
        strategy_params=params,
        rules_spec=manifest.get("rules_spec"),
        sizing=str(metadata.get("sizing", "vol_target")),
    )
