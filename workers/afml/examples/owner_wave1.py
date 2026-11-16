"""Real-data pictures for wave 1 items 3 to 6 (outside git). Run from ``workers/afml``:

    uv run python examples/owner_wave1.py --bars <SPY.parquet> --name SPY --out <folder>

Reads one bar file only. Writes ``<name>-cv.png``, ``<name>-fracdiff.png``,
``<name>-importance.png``, ``<name>-stats.png`` and ``<name>-wave1.json``. Nothing here is a
strategy or a profit figure: the candidate features and the moving-average grid are deliberately
simple inputs that exercise the tools.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import polars as pl

from alpha_afml_worker.cv import purged_splits
from alpha_afml_worker.fracdiff import ffd, fit_min_d
from alpha_afml_worker.importance import importance
from alpha_afml_worker.labels import LabelParams, label_events
from alpha_afml_worker.stats import pbo, sharpe_stats
from alpha_afml_worker.uniqueness import average_uniqueness

THEME = Path(
    "../../packages/alpha-research/src/alpha_research/figures/themes/terminal_classic.json"
)
FOOT = "Tools check results; they do not create an edge. Nothing here shows a profit."


def _style(theme: dict[str, Any]) -> None:
    plt.rcParams.update({
        "figure.facecolor": theme["bg"], "savefig.facecolor": theme["bg"],
        "axes.facecolor": "none", "axes.edgecolor": theme["line"],
        "axes.labelcolor": theme["ink_dim"], "axes.grid": True, "grid.color": theme["grid"],
        "grid.linestyle": ":", "text.color": theme["ink"], "xtick.color": theme["muted"],
        "ytick.color": theme["muted"], "font.family": "sans-serif",
        "font.sans-serif": [theme["font_family"]], "font.size": theme["base_font_pt"],
        "legend.facecolor": theme["bg"], "legend.edgecolor": theme["line"],
        "legend.labelcolor": theme["ink_dim"],
    })  # fmt: skip


def _save(fig: Any, path: Path, theme: dict[str, Any]) -> None:
    fig.text(0.01, 0.005, FOOT, fontsize=7, color=theme["faint"])
    fig.savefig(path, dpi=150)
    plt.close(fig)


def cv_figure(events: pl.DataFrame, theme: dict[str, Any], name: str, out: Path) -> dict[str, Any]:
    done = events.filter(pl.col("end_pos") >= 0)
    starts, ends = done["pos"].to_numpy(), done["end_pos"].to_numpy()
    result = purged_splits(starts, ends, n_groups=6, n_test_groups=2, embargo=5)
    grid = np.zeros((len(result.splits), starts.size))  # 0 dropped, 1 train, 2 test
    for row, (train, test) in enumerate(result.splits):
        grid[row, train], grid[row, test] = 1, 2
    from matplotlib.colors import ListedColormap

    fig, ax = plt.subplots(figsize=(12, 5))
    cmap = ListedColormap([theme["down"], theme["substrate"], theme["accent"]])
    ax.imshow(grid, aspect="auto", interpolation="nearest", cmap=cmap, vmin=0, vmax=2)
    ax.set_xlabel("label (in time order)")
    ax.set_ylabel("fold (2 of 6 groups tested)")
    dropped = int((grid == 0).sum())
    ax.set_title(
        f"{name}: 15 purged combinatorial folds over {starts.size} labels, {result.n_paths} "
        f"backtest paths. Blue test, grey train, red removed (overlap or 5-label embargo): "
        f"{dropped} cells", loc="left", fontsize=8.5,
    )  # fmt: skip
    _save(fig, out, theme)
    return {"labels": int(starts.size), "folds": len(result.splits), "paths": result.n_paths,
            "removed_cells": dropped, "extra_dropped_risklabai": result.extra_dropped_risklabai,
            "extra_dropped_quantowl": result.extra_dropped_quantowl}  # fmt: skip


def fracdiff_figure(
    bars: pl.DataFrame, theme: dict[str, Any], name: str, out: Path
) -> dict[str, Any]:
    index = pd.DatetimeIndex(bars["ts"].to_numpy()).tz_localize("UTC")
    close = pd.Series(bars["close"].to_numpy(), index=index)
    split = int(close.size * 0.6)
    fitted = fit_min_d(close.iloc[:split])
    values = ffd(np.log(close.to_numpy()), fitted.d or 1.0, 0.01)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6.5), sharex=True)
    ax1.plot(index, np.log(close.to_numpy()), color=theme["ink_dim"], lw=0.8)
    ax1.axvline(index[split - 1], color=theme["gold"], lw=0.8)
    ax1.set_ylabel("log price")
    ax1.set_title(
        f"{name}: d = {fitted.d} chosen on the first {split} bars only (gold line), then frozen; "
        f"ADF p = {fitted.pvalue:.3f}, memory kept (correlation) = {fitted.corr:.2f}",
        loc="left", fontsize=8.5,
    )  # fmt: skip
    ax2.plot(index, values, color=theme["categorical"][0], lw=0.7)
    ax2.axvline(index[split - 1], color=theme["gold"], lw=0.8)
    ax2.set_ylabel(f"fractionally differenced (d={fitted.d})")
    _save(fig, out, theme)
    return {"d": fitted.d, "pvalue": fitted.pvalue, "corr": fitted.corr, "train_bars": split,
            "table": fitted.table}  # fmt: skip


def _features(bars: pl.DataFrame, pos: np.ndarray) -> pd.DataFrame:
    c = np.log(bars["close"].to_numpy())
    r = np.r_[np.nan, np.diff(c)]
    cols: dict[str, np.ndarray] = {}
    for k in (5, 20, 60):
        cols[f"mom_{k}"] = c[pos] - c[pos - k]
    cols["vol_20"] = np.array([np.std(r[p - 19 : p + 1]) for p in pos])
    rng = np.random.default_rng(7)
    for i in range(3):
        cols[f"noise_{i}"] = rng.normal(size=pos.size)
    return pd.DataFrame(cols)


def importance_figure(bars: pl.DataFrame, events: pl.DataFrame, theme: dict[str, Any], name: str,
                      out: Path) -> dict[str, Any]:  # fmt: skip
    done = events.filter((pl.col("end_pos") >= 0) & (pl.col("pos") >= 61))
    pos, ends = done["pos"].to_numpy(), done["end_pos"].to_numpy()
    x = _features(bars, pos)
    spans = done.select(start="ts", end="end")
    w = average_uniqueness(bars["ts"], spans).labels["avg_uniqueness"].to_numpy()
    y = done["meta_label"].to_numpy().astype(int)
    result = importance(x, y, pos, ends, w, n_groups=5, embargo=5, seed=1, n_trees=200)
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.5), sharey=True)
    for ax, key, title in zip(axes, ("mdi", "mda", "sfi"),
                              ("MDI (in-sample)", "MDA (purged, out of sample)",
                               "SFI (purged, out of sample)"), strict=True):  # fmt: skip
        table = getattr(result, key)
        ax.barh(table.index, table["mean"], xerr=table["std"], color=theme["categorical"][0],
                ecolor=theme["muted"])  # fmt: skip
        ax.set_title(title, fontsize=8.5)
    fig.suptitle(f"{name}: which simple features the meta-label leans on ({pos.size} labels, "
                 "uniqueness-weighted; three noise columns as a yardstick)", fontsize=8.5,
                 x=0.01, ha="left")  # fmt: skip
    fig.subplots_adjust(left=0.1, right=0.99, top=0.85, bottom=0.12, wspace=0.08)
    _save(fig, out, theme)
    return {key: getattr(result, key)["mean"].round(4).to_dict() for key in ("mdi", "mda", "sfi")}


def stats_figure(bars: pl.DataFrame, theme: dict[str, Any], name: str, out: Path) -> dict[str, Any]:
    c = bars["close"].to_numpy()
    r = np.diff(np.log(c))
    columns = []
    for k in range(10, 210, 20):  # ten long/flat moving-average variants: a grid of tries
        ma = pd.Series(c).rolling(k).mean().to_numpy()
        held = np.r_[False, (c > ma)[:-1]][1:]  # decided at yesterday's close
        columns.append(np.where(held, r, 0.0))
    matrix = np.column_stack(columns)[210:]
    sharpes = matrix.mean(axis=0) / matrix.std(axis=0, ddof=1)
    best = int(np.argmax(sharpes))
    s = sharpe_stats(matrix[:, best], sharpes)
    p = pbo(matrix, 16)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
    ax1.bar(range(10), sharpes * np.sqrt(252), color=theme["categorical"][0])
    ax1.set_xticks(range(10), [str(k) for k in range(10, 210, 20)])
    ax1.set_xlabel("moving-average length (bars)")
    ax1.set_ylabel("annualised Sharpe, no costs")
    ax1.set_title(
        f"best of 10: PSR {s['quantowl']['psr']:.2f}, DSR {s['quantowl']['dsr']:.2f} "
        f"(RiskLabAI {s['risklabai']['dsr']:.2f}), min track record "
        f"{s['quantowl'].get('min_track_record_length', float('nan')):.0f} bars", fontsize=8.5,
        loc="left",
    )  # fmt: skip
    ax2.hist(p["quantowl"]["logits"], bins=30, color=theme["categorical"][0])
    ax2.axvline(0, color=theme["down"], lw=0.8)
    ax2.set_title(f"PBO = {p['quantowl']['pbo']:.2f} (both libraries): share of splits with the "
                  "in-sample best below median", fontsize=8.5, loc="left")  # fmt: skip
    ax2.set_xlabel("logit of the in-sample best's out-of-sample rank")
    fig.subplots_adjust(left=0.07, right=0.99, top=0.88, bottom=0.14, wspace=0.25)
    _save(fig, out, theme)
    s.pop("trial_sharpe_variance", None)
    return {"sharpe": s, "pbo": {k: p[k]["pbo"] for k in ("quantowl", "risklabai")}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    theme = json.loads(THEME.read_text("utf-8"))
    _style(theme)
    bars = pl.read_parquet(args.bars).select("ts", "open", "high", "low", "close")
    events = label_events(bars, LabelParams())
    stem = args.out / args.name.lower().replace("/", "-")
    summary = {
        "cv": cv_figure(events, theme, args.name, Path(f"{stem}-cv.png")),
        "fracdiff": fracdiff_figure(bars, theme, args.name, Path(f"{stem}-fracdiff.png")),
        "importance": importance_figure(bars, events, theme, args.name,
                                        Path(f"{stem}-importance.png")),
        "stats": stats_figure(bars, theme, args.name, Path(f"{stem}-stats.png")),
    }  # fmt: skip
    Path(f"{stem}-wave1.json").write_text(json.dumps(summary, indent=2, default=str), "utf-8")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
