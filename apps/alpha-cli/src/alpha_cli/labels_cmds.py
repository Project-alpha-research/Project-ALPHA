"""`alpha labels`: textbook triple-barrier labels and overlap weights from the isolated AFML worker.

ALPHA reads the bars point in time, hands them to ``workers/afml`` as Parquet across a process
boundary, and writes one immutable result folder per input: the bars it used, the worker's files,
the picture, and ``result.json`` with facts in the spine's shape (value, basis, reason) and labels
for sample size and weights scope. The worker computes; nothing it returns is a verdict.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import typer

from alpha_cli import _runner
from alpha_cli._cli_json import emit
from alpha_cli.spine import reserve
from alpha_cli.spine.errors import SpineError, fail
from alpha_cli.spine.stores import _stores, resolve_asset
from alpha_core import DataError
from alpha_core.config import AlphaSettings

labels_app = typer.Typer(
    help="Triple-barrier labels and overlap weights (López de Prado), from the AFML worker.",
    no_args_is_help=True,
)

SETUP_STEP = "uv sync --locked --project workers/afml"
SMALL_SAMPLE = 30
BASES = {
    "high_low": "high/low touches, entry at the next open, a bar touching both scored stop-first",
    "close": "closes only, entry at the event close (the libraries' convention, kept for parity)",
}


def _default_worker() -> Path:
    return Path(__file__).resolve().parents[4] / "workers" / "afml"


def _worker(project: Path | None) -> Path:
    """The worker project, or a plain-English refusal naming the one setup step."""
    root = _default_worker() if project is None else Path(project)
    if not (root / "pyproject.toml").is_file() or not (root / "uv.lock").is_file():
        raise SpineError(
            "WORKER_MISSING",
            f"The AFML worker project is not at {root}; labels need it.",
            "Run alpha labels from a checkout of the repository that contains workers/afml.",
        )
    if not (root / ".venv" / "bin" / "python").is_file():
        raise SpineError(
            "WORKER_NOT_INSTALLED",
            "The AFML worker is not installed on this computer, so labels cannot be computed.",
            f"Run once from the repository folder: {SETUP_STEP}",
        )
    return root


def _call_worker(project: Path, argv: list[str], *, timeout: int = 900) -> dict[str, Any]:
    """Run the worker in its own locked environment with a minimal, credential-free env."""
    uv = shutil.which("uv")
    if uv is None:
        raise SpineError("UV_MISSING", "uv is not on PATH; it starts the AFML worker.", SETUP_STEP)
    with tempfile.TemporaryDirectory(prefix="alpha-afml-uv-cache-") as cache:
        env = {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": os.defpath,
            "UV_NO_CONFIG": "1",
            "UV_OFFLINE": "1",
            "UV_CACHE_DIR": cache,
            "MPLBACKEND": "Agg",
        }
        command = [uv, "run", "--locked", "--no-sync", "--project", str(project)]
        completed = subprocess.run(
            [*command, "python", "-P", "-m", "alpha_afml_worker", *argv],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
            start_new_session=True,
        )
    if completed.returncode != 0:
        message = completed.stderr.strip().splitlines()[-1:] or ["no message"]
        raise SpineError(
            "WORKER_FAILED",
            f"The AFML worker refused or failed: {message[0]}",
            "Read the message; fix the input it names, or re-run the setup step: " + SETUP_STEP,
        )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise SpineError("WORKER_FAILED", "The AFML worker printed no summary.", SETUP_STEP)
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _worker_fingerprint(project: Path) -> str:
    """The lock and every adapter source file: a code change gives a new result id."""
    digest = hashlib.sha256(_sha256(project / "uv.lock").encode())
    for path in sorted((project / "src").rglob("*.py")):
        digest.update(path.relative_to(project).as_posix().encode())
        digest.update(_sha256(path).encode())
    return digest.hexdigest()


def _identity(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _labels_root(home: Path) -> Path:
    return home / "labels"


def _publish(staging: Path, final: Path) -> bool:
    """Move a finished folder into place; an existing folder with the same id is kept as is."""
    if (final / "result.json").is_file():
        shutil.rmtree(staging)
        return False
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, final)
    return True


def _fact(
    metric: str, value: Any, result_id: str, basis: str, labels: list[str], meaning: str
) -> dict[str, Any]:
    return {
        "metric": metric,
        "value": value,
        "run_id": result_id,
        "basis": basis,
        "source": f"summary.json:{metric}",
        "labels": labels,
        "meaning": meaning,
        "reason": None if value is not None else f"summary.json:{metric} is unavailable",
    }


@dataclass(frozen=True)
class _BarsInput:
    frame: pl.DataFrame
    meta: dict[str, Any]
    labels: list[str]


def _read_bars(asset: str, home: Path) -> _BarsInput:
    resolved = resolve_asset(asset, data_dir=home)
    held = reserve.hold(resolved.symbol, data_dir=resolved.data_dir)
    bars, snapshot_id = _runner.load_bars(
        resolved.symbol, data_dir=resolved.data_dir, as_of=held.as_of
    )
    if len(bars) < 60:
        raise DataError(f"{resolved.symbol}: labels need at least 60 bars, got {len(bars)}")
    frame = pl.DataFrame(
        {
            "ts": [bar.ts for bar in bars],
            "open": [bar.open for bar in bars],
            "high": [bar.high for bar in bars],
            "low": [bar.low for bar in bars],
            "close": [bar.close for bar in bars],
        }
    ).with_columns(pl.col("ts").dt.convert_time_zone("UTC").dt.cast_time_unit("us"))
    labels = held.label(["source-defaulted"] if resolved.defaulted else [])
    if (bars[-1].ts - bars[0].ts).total_seconds() < 3 * 365.25 * 86400:
        labels.append("short-history")
    meta = {
        "symbol": resolved.symbol,
        "store": resolved.store_name,
        "source": resolved.source,
        "snapshot_id": snapshot_id,
        "n_bars": len(bars),
        "first_ts": bars[0].ts.isoformat(),
        "last_ts": bars[-1].ts.isoformat(),
        "source_fingerprint": _runner.source_fingerprint(bars),
        **held.record_fields(),
    }
    return _BarsInput(frame, meta, labels)


def _theme_file(folder: Path) -> Path:
    from alpha_research.figures.theme import load_theme, theme_document

    path = folder / "theme.json"
    path.write_text(json.dumps(theme_document(load_theme()), sort_keys=True), "utf-8")
    return path


def _barrier_facts(summary: dict[str, Any], basis: str, rid: str, labels: list[str]) -> list[Any]:
    text = BASES[basis]
    facts = [
        _fact("events", summary["events"], rid, text, labels, "CUSUM events found."),
        _fact("decided", summary["decided"], rid, text, labels, "Events whose label is decided."),
    ]
    if basis == "high_low":
        outcomes = summary["outcomes"]
        for name, meaning in (
            ("target", "Labels that reached the profit target first."),
            ("stop", "Labels that reached the stop first (ambiguous bars included)."),
            ("vertical", "Labels that reached neither within the time limit."),
            ("open", "Events without enough later bars; no label is guessed."),
        ):
            facts.append(_fact(name, outcomes[name], rid, text, labels, meaning))
        facts.append(
            _fact(
                "ambiguous",
                summary["ambiguous"],
                rid,
                text,
                labels,
                "Bars that reached both barriers; scored stop-first, target-first beside it.",
            )
        )
    else:
        facts.append(
            _fact(
                "libraries_disagree_explained",
                summary["libraries_disagree_explained"],
                rid,
                text,
                labels,
                "Events where the two libraries differ only by log versus simple returns.",
            )
        )
    return facts


@labels_app.command("barrier")
def barrier(
    asset: str = typer.Option(..., help="Symbol or symbol@store, e.g. SPY@alpaca."),
    target: float = typer.Option(2.0, help="Profit target, in units of prior daily volatility."),
    stop: float = typer.Option(2.0, help="Stop, in units of prior daily volatility."),
    horizon: int = typer.Option(10, help="Time limit, in bars after the event bar."),
    cusum_mult: float = typer.Option(2.0, help="Event filter size, in units of volatility."),
    vol_span: int = typer.Option(50, help="Volatility span (bars), closes before the event."),
    momentum_bars: int = typer.Option(20, help="Side = sign of the return over these bars."),
    basis: str = typer.Option("high_low", help="high_low (ALPHA's) | close (library parity)."),
    worker_project: Path | None = typer.Option(None, help="Worker project (default workers/afml)."),  # noqa: B008
    json_out: bool = typer.Option(False, "--json", help="Emit one JSON result object."),
) -> None:
    """Label what happened after each event: target, stop or time limit first."""
    home = AlphaSettings().data_dir
    try:
        if basis not in BASES:
            raise SpineError(
                "UNKNOWN_BASIS", f"Unknown basis {basis!r}.", "Use --basis high_low or close.",
                list(BASES),
            )  # fmt: skip
        project = _worker(worker_project)
        with redirect_stdout(sys.stderr if json_out else sys.stdout):
            data = _read_bars(asset, home)
        params = {
            "pt": target, "sl": stop, "horizon": horizon, "cusum_mult": cusum_mult,
            "vol_span": vol_span, "momentum_bars": momentum_bars,
        }  # fmt: skip
        lock = _worker_fingerprint(project)
        rid = _identity(
            {"kind": "barrier", "bars": data.meta, "params": params, "basis": basis, "lock": lock}
        )
        final = _labels_root(home) / rid
        if not (final / "result.json").is_file():
            _labels_root(home).mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{rid}-", dir=_labels_root(home)))
            data.frame.write_parquet(staging / "bars.parquet")
            argv = [
                "labels", str(staging / "bars.parquet"), "--out", str(staging / "events.parquet"),
                "--basis", basis, "--horizon", str(horizon), "--pt", str(target),
                "--sl", str(stop), "--cusum-mult", str(cusum_mult), "--vol-span", str(vol_span),
                "--momentum-bars", str(momentum_bars),
            ]  # fmt: skip
            if basis == "high_low":
                argv += ["--figure", str(staging / "labels.png"), "--theme"]
                argv += [str(_theme_file(staging)), "--title", f"{data.meta['symbol']} daily"]
            summary = _call_worker(project, argv)
            (staging / "summary.json").write_text(json.dumps(summary, sort_keys=True), "utf-8")
            labels = [*data.labels]
            if summary["decided"] < SMALL_SAMPLE:
                labels.append("small-sample")
            if basis == "close":
                labels.append("parity-basis")
            if basis == "high_low" and summary["ambiguous"]:
                labels.append("ambiguous-bars")
            result = {
                "result_id": rid,
                "kind": "barrier",
                "asset": data.meta,
                "params": params,
                "basis": basis,
                "basis_text": BASES[basis],
                "worker": {"fingerprint": lock},
                "summary": summary,
                "labels": labels,
                "facts": _barrier_facts(summary, basis, rid, labels),
                **({"reserve": data.meta["reserve"]} if "reserve" in data.meta else {}),
                "created_at": datetime.now(UTC).isoformat(),
            }
            (staging / "result.json").write_text(
                json.dumps(result, sort_keys=True, indent=2, allow_nan=False), "utf-8"
            )
            _publish(staging, final)
            repeat = False
        else:
            repeat = True
        output = json.loads((final / "result.json").read_text("utf-8"))
        output["result_dir"] = str(final)
        output["repeat"] = repeat
    except SpineError as exc:
        fail(exc, json_out)
    except (ValueError, OSError, DataError, subprocess.TimeoutExpired) as exc:
        known = list(_stores(home)) if "not found" in str(exc) or "store" in str(exc) else None
        fail(
            SpineError("LABELS_FAILED", str(exc), "Correct the input named above.", known), json_out
        )
    lines = [f"Labels {rid} — {data.meta['symbol']} ({BASES[basis]})", f"Folder: {final}"]
    lines += [f"{f['metric']}: {f['value']}" for f in output["facts"]]
    lines.append("Labels: " + (", ".join(output["labels"]) or "none"))
    if "reserve" in output:
        lines.append(reserve.sentence(output["reserve"]["held_back_bars"]))
    emit(output, json_out=json_out, fallback="\n".join(lines))


def _parse_train_end(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        if len(value) != 10:
            raise ValueError("--train-end must be a date (YYYY-MM-DD) or a time with its zone")
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


@labels_app.command("weights")
def weights(
    result_id: str = typer.Argument(..., help="A high_low result id from alpha labels barrier."),
    train_end: str | None = typer.Option(
        None, help="Weight only labels that ended by this date (daily bars are stamped 00:00 UTC)."
    ),
    last_weight: float = typer.Option(0.5, help="Time decay: weight of the oldest label, 0..1."),
    seed: int = typer.Option(0, help="Seed for the sequential bootstrap."),
    worker_project: Path | None = typer.Option(None, help="Worker project (default workers/afml)."),  # noqa: B008
    json_out: bool = typer.Option(False, "--json", help="Emit one JSON result object."),
) -> None:
    """Weight labels by how much they overlap (uniqueness), with time decay."""
    home = AlphaSettings().data_dir
    try:
        parent = _labels_root(home) / result_id
        if not (parent / "result.json").is_file() or "/" in result_id:
            raise SpineError(
                "UNKNOWN_RESULT", f"No labels result {result_id!r}.",
                "Run alpha labels barrier first and pass the result id it prints.",
            )  # fmt: skip
        parent_result = json.loads((parent / "result.json").read_text("utf-8"))
        if parent_result["basis"] != "high_low":
            raise SpineError(
                "WRONG_BASIS", "Weights are built on high_low labels only.",
                "Run alpha labels barrier with --basis high_low.",
            )  # fmt: skip
        cut = _parse_train_end(train_end)
        project = _worker(worker_project)
        params = {"train_end": cut.isoformat() if cut else None, "last_weight": last_weight,
                  "seed": seed}  # fmt: skip
        lock = _worker_fingerprint(project)
        rid = _identity({"kind": "weights", "parent": result_id, "params": params, "lock": lock})
        final = _labels_root(home) / rid
        if not (final / "result.json").is_file():
            staging = Path(tempfile.mkdtemp(prefix=f".{rid}-", dir=_labels_root(home)))
            argv = [
                "uniqueness", str(parent / "events.parquet"), "--bars",
                str(parent / "bars.parquet"), "--out", str(staging / "weights.parquet"),
                "--last-weight", str(last_weight), "--seed", str(seed),
            ]  # fmt: skip
            if cut is not None:
                argv += ["--train-end", cut.isoformat()]
            summary = _call_worker(project, argv)
            (staging / "summary.json").write_text(json.dumps(summary, sort_keys=True), "utf-8")
            labels = ["weights-train-only" if cut else "weights-whole-sample"]
            if summary["labels"] < SMALL_SAMPLE:
                labels.append("small-sample")
            basis = summary["weights_scope"]
            facts = [
                _fact("labels", summary["labels"], rid, basis, labels, "Labels weighted."),
                _fact("labels_left_out", summary["labels_left_out"], rid, basis, labels,
                      "Labels not weighted: still open, or ended after the cut-off."),
                _fact("mean_avg_uniqueness", summary["mean_avg_uniqueness"], rid, basis, labels,
                      "Average share of its days each label has to itself (1 = no overlap)."),
                _fact("bootstrap_sample_uniqueness", summary["bootstrap_sample_uniqueness"], rid,
                      basis, labels, "Uniqueness of a sequential-bootstrap sample."),
                _fact("plain_bootstrap_sample_uniqueness",
                      summary["plain_bootstrap_sample_uniqueness"], rid, basis, labels,
                      "Uniqueness of a plain bootstrap sample, same seed, for contrast."),
                _fact("max_library_gap", summary["max_library_gap"], rid, basis, labels,
                      "Largest difference between RiskLabAI and quantowl (must be <= 1e-10)."),
            ]  # fmt: skip
            result = {
                "result_id": rid, "kind": "weights", "parent": result_id,
                "asset": parent_result["asset"], "params": params, "worker": {"fingerprint": lock},
                "summary": summary, "labels": labels, "facts": facts,
                "created_at": datetime.now(UTC).isoformat(),
            }  # fmt: skip
            (staging / "result.json").write_text(
                json.dumps(result, sort_keys=True, indent=2, allow_nan=False), "utf-8"
            )
            _publish(staging, final)
        output = json.loads((final / "result.json").read_text("utf-8"))
        output["result_dir"] = str(final)
    except SpineError as exc:
        fail(exc, json_out)
    except (ValueError, OSError, DataError, subprocess.TimeoutExpired) as exc:
        fail(SpineError("LABELS_FAILED", str(exc), "Correct the input named above."), json_out)
    lines = [f"Weights {rid} for labels {result_id}", f"Folder: {final}"]
    lines += [f"{f['metric']}: {f['value']}" for f in output["facts"]]
    lines.append("Labels: " + ", ".join(output["labels"]))
    emit(output, json_out=json_out, fallback="\n".join(lines))


def _factor_table(parent: Path, factors_path: Path, staging: Path) -> tuple[Path, list[str]]:
    """Join factor values (as of each event bar's close) to the decided labels, with weights."""
    events = pl.read_parquet(parent / "events.parquet").filter(pl.col("end_pos") >= 0)
    weights = pl.read_parquet(staging / "weights.parquet").select(
        pl.col("start").alias("ts"), pl.col("avg_uniqueness").alias("weight")
    )
    factors = pl.read_parquet(factors_path)
    schema = factors.schema
    if "ts" not in factors.columns or not isinstance(schema["ts"], pl.Datetime):
        raise ValueError("the factor file needs a 'ts' column of timestamps")
    names = [c for c in factors.columns if c != "ts" and schema[c].is_numeric()]
    if not names:
        raise ValueError("the factor file has no numeric factor columns")
    factors = factors.select(
        pl.col("ts").dt.replace_time_zone("UTC")
        if schema["ts"].time_zone is None
        else pl.col("ts").dt.convert_time_zone("UTC"),
        *names,
    ).with_columns(pl.col("ts").dt.cast_time_unit("us"))
    joined = (
        events.select(
            "ts",
            pl.col("pos").alias("start"),
            pl.col("end_pos").alias("end"),
            pl.col("meta_label").cast(pl.Int64).alias("label"),
        )
        .join(weights, on="ts", how="inner")
        .join(factors, on="ts", how="inner")
        .drop_nulls()
    )
    if joined.height != events.height:
        # A dropped row is not random (warm-up, coverage gaps, a shifted clock): refuse it.
        raise ValueError(
            f"{joined.height} of {events.height} events matched a complete factor row at the "
            "event bar's timestamp; the factor file must cover every labelled bar (UTC, no gaps)"
        )
    table = joined.sort("start").drop("ts")
    path = staging / "importance-input.parquet"
    table.write_parquet(path)
    return path, names


@labels_app.command("importance")
def importance_report(
    result_id: str = typer.Argument(..., help="A high_low result id from alpha labels barrier."),
    factors: Path = typer.Option(  # noqa: B008
        ..., help="Parquet: ts plus one numeric column per factor, each known at that bar's close."
    ),
    n_groups: int = typer.Option(5, help="Purged k-fold groups."),
    embargo: int = typer.Option(5, help="Labels embargoed after each test block."),
    seed: int = typer.Option(0, help="Seed for the forest and the permutations."),
    worker_project: Path | None = typer.Option(None, help="Worker project (default workers/afml)."),  # noqa: B008
    json_out: bool = typer.Option(False, "--json", help="Emit one JSON result object."),
) -> None:
    """Report which factors the labels lean on (MDI, purged MDA and SFI). A report, not a gate."""
    home = AlphaSettings().data_dir
    try:
        parent = _labels_root(home) / result_id
        if "/" in result_id or not (parent / "result.json").is_file():
            raise SpineError(
                "UNKNOWN_RESULT",
                f"No labels result {result_id!r}.",
                "Run alpha labels barrier first and pass the result id it prints.",
            )
        project = _worker(worker_project)
        params = {"factors_sha256": _sha256(factors), "n_groups": n_groups, "embargo": embargo,
                  "seed": seed}  # fmt: skip
        lock = _worker_fingerprint(project)
        rid = _identity({"kind": "importance", "parent": result_id, "params": params, "lock": lock})
        final = _labels_root(home) / rid
        if not (final / "result.json").is_file():
            staging = Path(tempfile.mkdtemp(prefix=f".{rid}-", dir=_labels_root(home)))
            _call_worker(project, ["uniqueness", str(parent / "events.parquet"), "--bars",
                                   str(parent / "bars.parquet"), "--out",
                                   str(staging / "weights.parquet")])  # fmt: skip
            table, names = _factor_table(parent, factors, staging)
            summary = _call_worker(project, [
                "importance", str(table), "--out", str(staging / "importance.json"),
                "--n-groups", str(n_groups), "--embargo", str(embargo), "--seed", str(seed),
            ])  # fmt: skip
            report = json.loads((staging / "importance.json").read_text("utf-8"))
            labels = ["report-only", "factor-timing-unchecked", "weights-whole-sample"]
            if summary["rows"] < SMALL_SAMPLE:
                labels.append("small-sample")
            basis = "purged k-fold on label end times, uniqueness-weighted; MDI in-sample"
            facts = [
                _fact(f"{kind}:{name}", report[kind][name]["mean"], rid, basis, labels,
                      f"{kind.upper()} mean importance of {name}.")
                for kind in ("mdi", "mda", "sfi") for name in names
            ]  # fmt: skip
            result = {
                "result_id": rid, "kind": "importance", "parent": result_id, "params": params,
                "factors": names, "worker": {"fingerprint": lock}, "summary": summary,
                "labels": labels, "facts": facts, "created_at": datetime.now(UTC).isoformat(),
            }  # fmt: skip
            (staging / "result.json").write_text(
                json.dumps(result, sort_keys=True, indent=2, allow_nan=False), "utf-8"
            )
            _publish(staging, final)
        output = json.loads((final / "result.json").read_text("utf-8"))
        output["result_dir"] = str(final)
    except SpineError as exc:
        fail(exc, json_out)
    except (ValueError, OSError, DataError, subprocess.TimeoutExpired) as exc:
        fail(SpineError("LABELS_FAILED", str(exc), "Correct the input named above."), json_out)
    lines = [f"Importance {rid} for labels {result_id} (a report; nothing is decided)"]
    lines += [f"{f['metric']}: {f['value']:.4f}" for f in output["facts"]]
    lines.append("Labels: " + ", ".join(output["labels"]))
    emit(output, json_out=json_out, fallback="\n".join(lines))
