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
import pandas as pd
import polars as pl

from alpha_afml_worker.contract import validate_bars
from alpha_afml_worker.cv import purged_splits
from alpha_afml_worker.figure import draw, summarise
from alpha_afml_worker.fracdiff import ffd, fit_min_d
from alpha_afml_worker.importance import importance
from alpha_afml_worker.labels import LabelParams, label_events
from alpha_afml_worker.stats import pbo, sharpe_stats, strategy_risk
from alpha_afml_worker.uniqueness import average_uniqueness, sequential_bootstrap, time_decay

INTEGER = (pl.Int64, pl.Int32, pl.UInt32, pl.UInt64)


def capabilities() -> dict[str, Any]:
    """The installed library versions and the functions this worker offers."""
    return {
        "libraries": {name: version(name) for name in ("RiskLabAI", "quantowl", "numba")},
        "functions": ["labels", "uniqueness", "cv", "fracdiff", "importance", "stats"],
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


def run_cv(
    spans_path: Path, out: Path, n_groups: int, test_groups: int, embargo: int
) -> dict[str, Any]:
    """Purged splits for label spans given as integer bar positions ``start`` and ``end``."""
    spans = pl.read_parquet(spans_path)
    if not {"start", "end"} <= set(spans.columns) or spans.schema["start"] not in INTEGER:
        raise ValueError("cv needs integer columns 'start' and 'end' (bar positions)")
    result = purged_splits(
        spans["start"].to_numpy(), spans["end"].to_numpy(), n_groups, test_groups, embargo
    )
    document = {
        "splits": [
            {"train": tr.tolist(), "test": te.tolist(), "groups": list(g)}
            for (tr, te), g in zip(result.splits, result.test_groups, strict=True)
        ],
        "path_folds": result.path_folds.tolist(),
    }
    out.write_text(json.dumps(document), "utf-8")
    return {
        "splits": len(result.splits),
        "paths": result.n_paths,
        "extra_dropped_risklabai": result.extra_dropped_risklabai,
        "extra_dropped_quantowl": result.extra_dropped_quantowl,
        "leaks": 0,
    }


def run_fracdiff(bars_path: Path, out: Path, fit_end: datetime, thres: float) -> dict[str, Any]:
    """Choose d on bars up to ``fit_end`` only, freeze it, apply FFD to every bar's log close."""
    bars = validate_bars(pl.read_parquet(bars_path))
    if fit_end.tzinfo is None:
        raise ValueError("fit_end must be time-zone aware")
    ts = pd.DatetimeIndex(bars["ts"].to_numpy()).tz_localize("UTC")
    close = pd.Series(bars["close"].to_numpy(), index=ts)
    fitted = fit_min_d(close[close.index <= fit_end], thres=thres)
    summary: dict[str, Any] = {
        "d": fitted.d, "pvalue": fitted.pvalue, "corr": fitted.corr,
        "train_bars": fitted.train_bars, "fit_end": fit_end.isoformat(), "table": fitted.table,
    }  # fmt: skip
    if fitted.d is not None:
        values = ffd(np.log(close.to_numpy()), fitted.d, thres)
        bars.select("ts").with_columns(ffd=pl.Series(values).fill_nan(None)).write_parquet(out)
    return summary


def run_importance(
    table_path: Path, out: Path, n_groups: int, embargo: int, seed: int, n_trees: int
) -> dict[str, Any]:
    """MDI, MDA and SFI as a report; columns start, end, label, optional weight, then features."""
    table = pl.read_parquet(table_path)
    fixed = {"start", "end", "label", "weight"}
    names = [c for c in table.columns if c not in fixed]
    if not {"start", "end", "label"} <= set(table.columns) or not names:
        raise ValueError("importance needs columns start, end, label and at least one feature")
    weights = table["weight"].to_numpy() if "weight" in table.columns else None
    result = importance(
        pd.DataFrame({n: table[n].to_numpy() for n in names}),
        table["label"].to_numpy(), table["start"].to_numpy(), table["end"].to_numpy(),
        weights, n_groups, embargo, seed, n_trees,
    )  # fmt: skip
    report = {
        name: {
            feature: {"mean": float(row["mean"]), "std": float(row["std"])}
            for feature, row in getattr(result, name).iterrows()
        }
        for name in ("mdi", "mda", "sfi")
    }
    report["baseline_accuracy"] = {"per_fold": result.baseline.tolist()}
    out.write_text(json.dumps(report, sort_keys=True, allow_nan=False), "utf-8")
    return {"features": len(names), "rows": table.height, "folds": result.folds,
            "extra_dropped_vs_reference": result.extra_dropped}  # fmt: skip


def run_stats(inputs: Path, out: Path) -> dict[str, Any]:
    """Second opinions on Sharpe statistics; input JSON: returns, trial_sharpes, matrix, ..."""
    spec = json.loads(inputs.read_text("utf-8"))
    report: dict[str, Any] = {}
    returns = np.asarray(spec["returns"], dtype=np.float64)
    trials = spec.get("trial_sharpes")
    report["sharpe"] = sharpe_stats(returns, None if trials is None else np.asarray(trials))
    if spec.get("matrix") is not None:
        report["pbo"] = pbo(np.asarray(spec["matrix"]), int(spec.get("n_partitions", 16)))
    if spec.get("freq") is not None:
        report["strategy_risk"] = strategy_risk(
            returns, float(spec["freq"]), float(spec.get("target_sharpe", 1.0))
        )
    out.write_text(json.dumps(report, sort_keys=True, allow_nan=False), "utf-8")
    return {"sections": sorted(report)}


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
    cv = commands.add_parser("cv")
    cv.add_argument("spans", type=Path)
    cv.add_argument("--out", type=Path, required=True)
    cv.add_argument("--n-groups", type=int, required=True)
    cv.add_argument("--test-groups", type=int, default=1, help="1 = purged k-fold")
    cv.add_argument("--embargo", type=int, default=0, help="rows after each test block")
    frac = commands.add_parser("fracdiff")
    frac.add_argument("bars", type=Path)
    frac.add_argument("--out", type=Path, required=True)
    frac.add_argument("--fit-end", type=datetime.fromisoformat, required=True)
    frac.add_argument("--thres", type=float, default=0.01)
    imp = commands.add_parser("importance")
    imp.add_argument("table", type=Path)
    imp.add_argument("--out", type=Path, required=True)
    imp.add_argument("--n-groups", type=int, default=5)
    imp.add_argument("--embargo", type=int, default=0)
    imp.add_argument("--seed", type=int, default=0)
    imp.add_argument("--n-trees", type=int, default=200)
    stat = commands.add_parser("stats")
    stat.add_argument("inputs", type=Path)
    stat.add_argument("--out", type=Path, required=True)
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
        elif args.command == "fracdiff":
            summary = run_fracdiff(args.bars, args.out, args.fit_end, args.thres)
        elif args.command == "importance":
            summary = run_importance(
                args.table, args.out, args.n_groups, args.embargo, args.seed, args.n_trees
            )
        elif args.command == "stats":
            summary = run_stats(args.inputs, args.out)
        elif args.command == "cv":
            summary = run_cv(args.spans, args.out, args.n_groups, args.test_groups, args.embargo)
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
