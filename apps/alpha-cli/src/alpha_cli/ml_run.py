"""`alpha ml run`: one plain spec to one stored run, through the existing Qlib worker path.

Steps: freeze the stored bars of the assets, export the held-back input bundle, prepare the
exchange, train in the isolated worker, replay through the engine with costs, count one try.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import shutil
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpha_cli import ml_cmds, ml_progress
from alpha_cli._ml_replay import run_ml_replay
from alpha_cli._progress import heartbeat
from alpha_cli._runner import parse_as_of
from alpha_cli.ml_contract import (
    MIN_SYMBOLS,
    MLContractError,
    canonical_json_bytes,
    prepare_exchange,
    sha256_file,
)
from alpha_cli.ml_glosses import held_back_sentence
from alpha_cli.ml_input import export_input
from alpha_cli.ml_split import split_sentence
from alpha_cli.spine.ledger import append_trial
from alpha_cli.spine.reading import old_grade_text
from alpha_core import DataError
from alpha_data.snapshot import create_snapshot, resolve_snapshot_dir
from alpha_data.store import ParquetStore
from alpha_data.timeframe import DAILY, store_dir

SETUP_STEP = "bash scripts/setup.sh"
MODELS = ("lightgbm",)
FEATURES = ("alpha158",)
# Fixed costs for a plain run, in basis points; the run records them in its manifest.
FEE_BPS = 1.0
SLIPPAGE_BPS = 2.0
_SPLIT_DEFAULTS = {"train_days": 504, "validation_days": 120, "test_days": 63}
_KEYS = {"name", "assets", "features", "horizon_days", "model", "split"}


class MlRunError(ValueError):
    """A plain-words refusal; the message says what to change or run."""


def _read(spec_path: Path) -> dict[str, Any]:
    path = Path(spec_path)
    if not path.is_file():
        raise MlRunError(f"The spec file {path.name} does not exist.")
    try:
        spec = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise MlRunError(f"The spec file {path.name} is not valid TOML: {exc}") from exc
    unknown = sorted(set(spec) - _KEYS)
    if unknown:
        raise MlRunError(
            f"The spec has unknown keys: {', '.join(unknown)}. Allowed: {sorted(_KEYS)}."
        )
    assets = spec.get("assets")
    if not isinstance(assets, list) or not assets or not all(isinstance(a, str) for a in assets):
        raise MlRunError('The spec needs `assets`: a list of symbols, such as ["SPY", "QQQ"].')
    if len(set(assets)) < MIN_SYMBOLS:
        raise MlRunError(
            f"A model needs at least {MIN_SYMBOLS} assets; the spec has {len(set(assets))}. "
            "Add more symbols to `assets`; see research/examples/ml-gbm-etfs.toml."
        )
    if spec.get("model", MODELS[0]) not in MODELS:
        raise MlRunError(f"The model must be {' or '.join(MODELS)}. The worker offers no other.")
    if spec.get("features", FEATURES[0]) not in FEATURES:
        raise MlRunError(f"The feature set must be {FEATURES[0]}. The worker has no other.")
    if spec.get("horizon_days", 1) != 1:
        raise MlRunError("The label horizon must be 1 day. The worker trains on the next day only.")
    split = spec.get("split", {})
    if not isinstance(split, dict) or set(split) - set(_SPLIT_DEFAULTS):
        raise MlRunError(f"[split] may hold only {', '.join(_SPLIT_DEFAULTS)}.")
    return spec


def _require_worker(project: Path | None) -> Path:
    root = ml_cmds._default_worker_project() if project is None else Path(project)
    if not (root / ".venv" / "bin" / "alpha-qlib-worker").is_file():
        raise MlRunError(
            "The Qlib worker is not installed on this computer, so no model can be trained. "
            f"Run once from the repository folder: {SETUP_STEP}"
        )
    return root


def _content_key(store: ParquetStore, symbols: list[str]) -> str:
    """Hash the bars, actions and pull record of each symbol; the same for a store or snapshot."""
    digest = hashlib.sha256()
    for symbol in symbols:
        bars = store._bars_path(symbol)
        if not bars.is_file():
            raise MlRunError(
                f"No stored bars for {symbol}. Pull its data first with `alpha data pull`."
            )
        for part in (bars, store._actions_path(symbol), store._provenance_path(symbol)):
            digest.update(symbol.encode() + part.name.encode())
            digest.update(hashlib.sha256(part.read_bytes()).digest() if part.is_file() else b"-")
    return f"ml-{digest.hexdigest()[:16]}"


def _freeze(data_dir: Path, assets: list[str]) -> str:
    """Freeze the stored bars of the assets into one immutable snapshot; reuse an equal one.

    The snapshot id is the hash of its own bytes: a snapshot is reused only after its files hash
    to its id, and a fresh one that does not (the store changed while copying) is removed.
    """
    symbols = sorted(assets)
    store = ParquetStore(store_dir(data_dir, DAILY))
    snapshot_id = _content_key(store, symbols)
    source: dict[str, object] | None = None
    for symbol in symbols:
        found = store.read_provenance(symbol)
        if found is None or (source is not None and found["source"] != source["source"]):
            raise MlRunError(
                f"The stored bars of {symbol} have no single pull record. Pull the assets again."
            )
        source = source or found
    root = data_dir / "snapshots"
    target = resolve_snapshot_dir(root, snapshot_id)
    created = not target.exists()
    if created:
        assert source is not None
        create_snapshot(
            store,
            root,
            snapshot_id,
            symbols,
            source=str(source["source"]),
            adapter_version=str(source["adapter_version"]),
            parser_version=str(source["parser_version"]),
            created_at=datetime.now(UTC),
        )
    if _content_key(ParquetStore(target), symbols) != snapshot_id:
        if created:
            shutil.rmtree(target)
        raise MlRunError("The stored data changed while it was frozen. Run the command again.")
    return snapshot_id


def _experiment(spec: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    split = {**_SPLIT_DEFAULTS, **spec.get("split", {})}
    return {
        "snapshot_id": snapshot_id,
        "universe": sorted(spec["assets"]),
        "split_policy": {},
        "stage_config": {
            "ml": {
                "recipe": "lightgbm",
                "train_sessions": split["train_days"],
                "validation_sessions": split["validation_days"],
                "test_sessions": split["test_days"],
            }
        },
        "costs": {"fee_bps": FEE_BPS, "slippage_bps": SLIPPAGE_BPS},
        "seeds": {"ml": 7},
    }


def _day(text: object) -> str:
    return str(text)[:10]


def _folds(base: Path) -> list[dict[str, str]]:
    folds = json.loads((base / "exchange" / "request.json").read_text(encoding="utf-8"))["folds"]
    return [
        {name: _day(fold[name]) for name in ("train_start", "train_end", "test_start", "test_end")}
        for fold in folds
    ]


def _count_try(
    data_dir: Path, spec: dict[str, Any], run_id: str, snapshot_id: str, folds: list[dict[str, str]]
) -> str:
    row = append_trial(
        data_dir,
        {
            "kind": "ml_run",
            "name": str(spec.get("name", "qlib/lightgbm")),
            "spec_sha256": hashlib.sha256(canonical_json_bytes(spec)).hexdigest(),
            "assets": sorted(spec["assets"]),
            "first_ts": folds[0]["train_start"],
            "last_ts": folds[-1]["test_end"],
            "bar_size": "1D",
            "store": snapshot_id,
            "run_id": run_id,
            "labels": [],
            "evidence": old_grade_text(None),  # a replay has no reading; do not list it as a fault
        },
    )
    if "repeat" in row["labels"]:
        return "This run counted 0 new tries in family qlib: the same run was counted before."
    return "This run counted 1 try in family qlib. A later `alpha ledger summary` shows the total."


def _train(base: Path, experiment: dict[str, Any], project: Path, data_dir: Path) -> None:
    """Train with the expected time printed first and a progress line while the worker runs."""
    folds = len(_folds(base))
    assets = len(experiment["universe"])
    expected, each = ml_progress.announce(data_dir, assets, folds)
    started = time.monotonic()
    with heartbeat(
        "Model training",
        every=ml_progress.PROGRESS_EVERY,
        expected=expected,
        detail=lambda elapsed: ml_progress.fold_phrase(elapsed, each, folds),
    ):
        ml_cmds.train_exchange(
            base / "exchange",
            mode="real",
            worker_project=project,
            no_sync=True,
            timeout_seconds=7_200,
        )
    ml_progress.record(data_dir, assets, folds, time.monotonic() - started)


def _build(base: Path, experiment: dict[str, Any], project: Path, as_of: str | None) -> None:
    """Export, prepare and train into `base` unless a finished exchange is already there."""
    data_dir = base.parents[1]
    if not (base / "done").is_file():
        shutil.rmtree(base, ignore_errors=True)
        base.mkdir(parents=True)
        try:
            (base / "experiment.json").write_bytes(canonical_json_bytes(experiment))
            export_input(
                data_dir=data_dir,
                spec_path=base / "experiment.json",
                output_dir=base / "input",
                worker_project=project,
                as_of=as_of,
            )
            prepare_exchange(
                base / "input" / "spec.json",
                base / "input" / "panel.parquet",
                base / "exchange",
                worker_lock_path=project / "uv.lock",
            )
            _train(base, experiment, project, data_dir)
            (base / "done").write_text("ok\n", encoding="utf-8")
        except (DataError, MLContractError, OSError):
            shutil.rmtree(base, ignore_errors=True)
            raise


def run_spec(
    spec_path: Path,
    *,
    data_dir: Path,
    as_of: str | None = None,
    worker_project: Path | None = None,
) -> dict[str, Any]:
    """Run the plain spec end to end and return the reading; raise `MlRunError` in plain words."""
    spec = _read(spec_path)
    project = worker_project
    project = _require_worker(project)
    snapshot_id = _freeze(data_dir, spec["assets"])
    experiment = _experiment(spec, snapshot_id)
    key = hashlib.sha256(
        canonical_json_bytes(
            {"e": experiment, "as_of": as_of, "lock": sha256_file(project / "uv.lock")}
        )
    ).hexdigest()[:16]
    base = data_dir / "ml_runs" / key
    base.parent.mkdir(parents=True, exist_ok=True)
    with base.with_suffix(".lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)  # one build per key; a second waits, then reuses
        _build(base, experiment, project, as_of)
    replayed = run_ml_replay(
        base / "exchange", data_dir=data_dir, research_cutoff=parse_as_of(as_of)
    )
    manifest = replayed.manifest
    folds = _folds(base)
    return {
        "status": "replayed",
        "run_id": replayed.run_id,
        "folds": folds,
        "split_sentence": split_sentence(folds),
        "costs": f"{FEE_BPS} bp fee and {SLIPPAGE_BPS} bp slippage per trade",
        "n_oos_periods": manifest["n_oos_periods"],
        "metrics": manifest["metrics"],
        "authority": manifest["authority"],
        "label": manifest["label"],
        "validation": manifest["validation"],
        "tries_sentence": _count_try(data_dir, spec, replayed.run_id, snapshot_id, folds),
        **(
            {"reserve_sentence": held_back_sentence(manifest["reserve"], len(manifest["universe"]))}
            if "reserve" in manifest
            else {}
        ),
    }
