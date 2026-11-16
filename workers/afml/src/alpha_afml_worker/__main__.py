"""Command line for the isolated worker: Parquet in, Parquet out, a JSON summary on stdout.

    alpha-afml-worker capabilities
    alpha-afml-worker labels BARS.parquet --out EVENTS.parquet [--basis high_low|close]
    alpha-afml-worker uniqueness EVENTS.parquet --bars BARS.parquet --out WEIGHTS.parquet

Any failure prints one line to stderr and exits 2. Nothing here writes a verdict: ALPHA reads
the files and decides what, if anything, they mean.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from alpha_afml_worker.contract import validate_bars
from alpha_afml_worker.figure import draw, summarise
from alpha_afml_worker.labels import LabelParams, label_events
from alpha_afml_worker.uniqueness import average_uniqueness, sequential_bootstrap, time_decay


def capabilities() -> dict[str, Any]:
    """The installed library versions and the functions this worker offers."""
    return {
        "libraries": {name: version(name) for name in ("RiskLabAI", "quantowl", "numba")},
        "functions": ["labels", "uniqueness"],
        "label_bases": ["high_low", "close"],
    }


def run_labels(
    bars_path: Path,
    out: Path,
    basis: str,
    params: LabelParams,
    figure: Path | None = None,
    theme: Path | None = None,
    title: str = "Daily bars",
) -> dict[str, Any]:
    """Label the events; with ``figure`` (and a ``theme`` document) also draw the picture."""
    bars = pl.read_parquet(bars_path)
    events = label_events(bars, params, basis)  # type: ignore[arg-type]
    events.write_parquet(out)
    summary: dict[str, Any] = {"basis": basis, "events": events.height}
    if basis == "high_low":
        counts = dict(events["outcome"].value_counts().rows())
        summary["outcomes"] = {
            name: int(counts.get(name, 0)) for name in ("target", "stop", "vertical", "open")
        }
        summary["decided"] = int(events["end"].is_not_null().sum())
        summary["ambiguous"] = int(events["ambiguous"].sum())
        summary["optimistic_flips"] = int((events["outcome"] != events["outcome_optimistic"]).sum())
    else:
        summary["decided"] = int((events["close_end_pos"] >= 0).sum())
        summary["libraries_disagree_explained"] = int((~events["close_libraries_agree"]).sum())
    if figure is not None:
        if theme is None:
            raise ValueError("--figure needs --theme (ALPHA's theme document, as JSON)")
        numbers, frames = summarise(bars, params)
        draw(bars, numbers, frames, json.loads(theme.read_text("utf-8")), figure, title)
        summary["figure"] = figure.name
    return summary


def run_uniqueness(
    events_path: Path,
    bars_path: Path,
    out: Path,
    last_weight: float,
    draws: int,
    seed: int,
    train_end: datetime | None = None,
) -> dict[str, Any]:
    """Weights for the finished labels in a ``labels`` output.

    A label's span runs from its event bar to its end bar (the book's convention; the position
    itself starts at the next open, so the overlap counted is slightly conservative). Both the
    uniqueness and the decay total depend on every label used, so a later label changes an
    earlier weight. With ``train_end`` only labels that ended on or before it are used, and the
    weights depend on no later bar; without it the whole file is used and the summary says so.
    """
    bars = validate_bars(pl.read_parquet(bars_path))
    events = pl.read_parquet(events_path)
    if "end" not in events.columns:
        raise ValueError("uniqueness needs a high_low labels file (column 'end')")
    finished = events.filter(pl.col("end").is_not_null()).select(start="ts", end="end")
    scope = "every finished label in the file (whole sample: not for training weights on a split)"
    if train_end is not None:
        if train_end.tzinfo is None:
            raise ValueError("train_end must be time-zone aware")
        finished = finished.filter(pl.col("end") <= train_end)
        scope = f"labels ending on or before {train_end.isoformat()}"
    result = average_uniqueness(bars["ts"], finished)
    decay = time_decay(result.labels["avg_uniqueness"].to_numpy(), last_weight)
    boot = sequential_bootstrap(result.indicator, draws or result.labels.height, seed)
    weights = result.labels.with_columns(decay=pl.Series(decay))
    weights.write_parquet(out)
    return {
        "labels": weights.height,
        "labels_left_out": events.height - weights.height,
        "weights_scope": scope,
        "mean_avg_uniqueness": float(np.mean(result.labels["avg_uniqueness"].to_numpy())),
        "max_library_gap": result.max_gap,
        "bootstrap_sample_uniqueness": boot.sample_avg_uniqueness,
        "plain_bootstrap_sample_uniqueness": boot.standard_avg_uniqueness,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alpha-afml-worker")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("capabilities")
    labels = commands.add_parser("labels")
    labels.add_argument("bars", type=Path)
    labels.add_argument("--out", type=Path, required=True)
    labels.add_argument("--basis", choices=("high_low", "close"), default="high_low")
    labels.add_argument("--figure", type=Path, default=None, help="also write this PNG")
    labels.add_argument("--theme", type=Path, default=None, help="figure theme document (JSON)")
    labels.add_argument("--title", default="Daily bars", help="figure title prefix")
    defaults = LabelParams()
    for name in ("vol_span", "vol_min_bars", "momentum_bars", "horizon"):
        labels.add_argument(
            f"--{name.replace('_', '-')}", type=int, default=getattr(defaults, name)
        )
    for name in ("cusum_mult", "pt", "sl"):
        labels.add_argument(
            f"--{name.replace('_', '-')}", type=float, default=getattr(defaults, name)
        )
    weights = commands.add_parser("uniqueness")
    weights.add_argument("events", type=Path)
    weights.add_argument("--bars", type=Path, required=True)
    weights.add_argument("--out", type=Path, required=True)
    weights.add_argument("--last-weight", type=float, default=0.5)
    weights.add_argument("--draws", type=int, default=0, help="0 means one draw per label")
    weights.add_argument("--seed", type=int, default=0)
    weights.add_argument(
        "--train-end",
        type=datetime.fromisoformat,
        default=None,
        help="aware ISO time; weight only labels that ended by then (omit: whole file)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        if args.command == "capabilities":
            summary = capabilities()
        elif args.command == "labels":
            params = LabelParams(
                vol_span=args.vol_span,
                vol_min_bars=args.vol_min_bars,
                cusum_mult=args.cusum_mult,
                momentum_bars=args.momentum_bars,
                pt=args.pt,
                sl=args.sl,
                horizon=args.horizon,
            )
            summary = run_labels(
                args.bars, args.out, args.basis, params, args.figure, args.theme, args.title
            )
        else:
            summary = run_uniqueness(
                args.events,
                args.bars,
                args.out,
                args.last_weight,
                args.draws,
                args.seed,
                args.train_end,
            )
        print(json.dumps(summary, sort_keys=True, allow_nan=False))
    except Exception as exc:
        print(f"alpha-afml-worker: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
