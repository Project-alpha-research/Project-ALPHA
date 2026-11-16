"""The labels picture: events with barriers and outcomes on price, label overlap underneath.

Drawn in ALPHA's flat figure style from a theme document the caller passes as data (the worker
never imports ALPHA). Nothing drawn here is a backtest or a profit figure.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

from alpha_afml_worker.labels import LabelParams, label_events
from alpha_afml_worker.uniqueness import average_uniqueness, sequential_bootstrap

SEED = 20261116
SHOWN_BARS = 260  # about one trading year on screen; every number uses the full history


def summarise(
    bars: pl.DataFrame, params: LabelParams, seed: int = SEED
) -> tuple[dict[str, Any], dict[str, Any]]:
    """All numbers for one market (both bases), plus the frames the figure needs."""
    hl = label_events(bars, params)
    close = label_events(bars, params, "close")
    finished = hl.filter(pl.col("end").is_not_null())
    uniq = average_uniqueness(bars["ts"], finished.select(start="ts", end="end"))
    boot = sequential_bootstrap(uniq.indicator, finished.height, seed)
    counts = dict(hl["outcome"].value_counts().sort("outcome").rows())
    names = {"pt": "target", "sl": "stop", "vertical": "vertical", "none": "open"}
    close_outcome = [names[b] for b in close["close_barrier_quantowl"].to_list()]
    differs = sum(
        a != b and a != "open" and b != "open"
        for a, b in zip(hl["outcome"].to_list(), close_outcome, strict=True)
    )
    numbers = {
        "bars": bars.height,
        "first_bar": str(bars["ts"][0].date()),
        "last_bar": str(bars["ts"][-1].date()),
        "events": hl.height,
        "outcomes_high_low": {str(k): int(v) for k, v in counts.items()},
        "ambiguous_bars": int(hl["ambiguous"].sum()),
        "optimistic_flips": int((hl["outcome"] != hl["outcome_optimistic"]).sum()),
        "outcome_differs_close_basis": int(differs),
        "close_basis_library_disagreements_explained": int((~close["close_libraries_agree"]).sum()),
        "mean_avg_uniqueness": float(np.mean(uniq.labels["avg_uniqueness"].to_numpy())),
        "max_library_gap_uniqueness": uniq.max_gap,
        "sequential_bootstrap_sample_uniqueness": boot.sample_avg_uniqueness,
        "plain_bootstrap_sample_uniqueness": boot.standard_avg_uniqueness,
        "params": asdict(params),
    }
    return numbers, {"hl": hl, "uniq": uniq}


def draw(
    bars: pl.DataFrame,
    numbers: dict[str, Any],
    frames: dict[str, Any],
    theme: dict[str, Any],
    out: Path,
    title: str,
) -> None:
    """One annotated PNG: events and barriers on price, labels alive, uniqueness."""
    plt.rcParams.update(
        {
            "figure.facecolor": theme["bg"],
            "savefig.facecolor": theme["bg"],
            "axes.facecolor": "none",
            "axes.edgecolor": theme["line"],
            "axes.labelcolor": theme["ink_dim"],
            "axes.grid": True,
            "grid.color": theme["grid"],
            "grid.linestyle": ":",
            "grid.linewidth": 0.6,
            "text.color": theme["ink"],
            "xtick.color": theme["muted"],
            "ytick.color": theme["muted"],
            "font.family": "sans-serif",
            "font.sans-serif": [theme["font_family"]],
            "font.size": theme["base_font_pt"],
            "legend.facecolor": theme["bg"],
            "legend.edgecolor": theme["line"],
            "legend.labelcolor": theme["ink_dim"],
        }
    )
    colour = {
        "target": theme["up"],
        "stop": theme["down"],
        "vertical": theme["faint"],
        "open": theme["substrate"],
    }
    first = max(0, bars.height - SHOWN_BARS)
    n_shown = bars.height - first
    x = np.arange(bars.height)[first:]
    o, h, lo, c = (bars[k].to_numpy()[first:] for k in ("open", "high", "low", "close"))
    hl: pl.DataFrame = frames["hl"].filter(pl.col("pos") >= first)
    fig, (ax_p, ax_c, ax_u) = plt.subplots(
        3, 1, figsize=(12, 8.2), sharex=True, gridspec_kw={"height_ratios": [3.2, 1, 1]}
    )
    ax_p.vlines(x, lo, h, color=theme["substrate"], linewidth=1.2, label="day's high-low range")
    ax_p.plot(x, c, color=theme["ink_dim"], linewidth=0.9, label="close")
    for row in hl.iter_rows(named=True):
        t, side, w = row["pos"], row["side"], row["width"]
        if t + 1 >= bars.height:
            continue
        entry = float(bars["open"][t + 1])
        stop_end = (
            row["end_pos"]
            if row["end_pos"] >= 0
            else min(t + numbers["params"]["horizon"], bars.height - 1)
        )
        span = [t + 1, stop_end]
        target = entry * (1 + side * numbers["params"]["pt"] * w)
        stop = entry * (1 - side * numbers["params"]["sl"] * w)
        ax_p.plot(span, [target, target], color=theme["up"], linewidth=0.8, alpha=0.8)
        ax_p.plot(span, [stop, stop], color=theme["down"], linewidth=0.8, alpha=0.8)
        ax_p.scatter(
            [t],
            [float(bars["close"][t])],
            marker="^" if side > 0 else "v",
            color=theme["accent"],
            s=26,
            zorder=4,
        )
        if row["end_pos"] >= 0:
            ax_p.scatter(
                [row["end_pos"]],
                [float(bars["close"][row["end_pos"]])],
                color=colour[row["outcome"]],
                s=22,
                zorder=5,
                edgecolor=theme["gold"] if row["ambiguous"] else "none",
            )
    for name in ("target", "stop", "vertical"):
        ax_p.scatter([], [], color=colour[name], s=22, label=f"label ends: {name}")
    ax_p.scatter([], [], marker="^", color=theme["accent"], s=26, label="event (arrow = side)")
    ax_p.legend(loc="upper left", ncols=3, fontsize=7.5)
    ax_p.set_ylabel("price")
    n = numbers
    o_counts = n["outcomes_high_low"]
    ax_p.set_title(
        f"{title}, {n['first_bar']} to {n['last_bar']}: {n['events']} CUSUM events, "
        f"labelled on highs and lows (last {n_shown} bars shown)",
        loc="left",
        color=theme["ink"],
    )
    note = (
        f"target {o_counts.get('target', 0)}  stop {o_counts.get('stop', 0)}  "
        f"time limit {o_counts.get('vertical', 0)}  still open {o_counts.get('open', 0)}\n"
        f"bars touching both barriers: {n['ambiguous_bars']} (scored stop first)\n"
        f"outcome changes if only closes are read: {n['outcome_differs_close_basis']} events"
    )
    ax_p.text(
        0.995,
        0.03,
        note,
        transform=ax_p.transAxes,
        ha="right",
        va="bottom",
        fontsize=7.5,
        color=theme["ink_dim"],
        bbox={"facecolor": theme["bg"], "edgecolor": theme["line"], "linewidth": 0.6},
    )

    conc = frames["uniq"].concurrency["concurrency"].to_numpy()[first:]
    ax_c.bar(x, conc, width=1.0, color=theme["categorical"][0], linewidth=0)
    ax_c.set_ylabel("labels alive")
    uniq = frames["uniq"].labels
    pos = frames["hl"].filter(pl.col("end").is_not_null())["pos"].to_numpy()
    in_view = pos >= first
    ax_u.scatter(
        pos[in_view], uniq["avg_uniqueness"].to_numpy()[in_view], s=14, color=theme["gold"]
    )
    ax_u.set_ylim(0, 1.05)
    ax_u.set_ylabel("uniqueness")
    ax_u.text(
        0.995,
        0.06,
        f"mean uniqueness {n['mean_avg_uniqueness']:.2f} (1 = no overlap);  bootstrap sample "
        f"uniqueness: sequential {n['sequential_bootstrap_sample_uniqueness']:.2f}, "
        f"plain {n['plain_bootstrap_sample_uniqueness']:.2f}",
        transform=ax_u.transAxes,
        ha="right",
        va="bottom",
        fontsize=7.5,
        color=theme["ink_dim"],
    )
    ticks = x[:: max(1, n_shown // 8)]
    ax_u.set_xticks(ticks, [str(bars["ts"][int(i)].date()) for i in ticks])
    fig.text(
        0.01,
        0.005,
        "Labels describe what happened after each event. They are not trades, "
        "costs are not included, and nothing here shows a profit.",
        fontsize=7,
        color=theme["faint"],
    )
    fig.subplots_adjust(left=0.06, right=0.99, top=0.95, bottom=0.07, hspace=0.12)
    fig.savefig(out, dpi=150)
    plt.close(fig)
