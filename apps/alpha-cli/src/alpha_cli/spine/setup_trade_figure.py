"""Pure deterministic trade figure and plain-language command presentation."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from alpha_research.figures.theme import Theme


def _style(theme: Theme) -> dict[Any, Any]:
    import matplotlib

    return {
        **dict(matplotlib.rcParamsDefault.items()),
        "font.family": theme.font_family,
        "figure.facecolor": theme.bg,
        "axes.facecolor": theme.panel,
        "axes.edgecolor": theme.grid,
        "text.color": theme.ink,
        "axes.labelcolor": theme.ink,
        "xtick.color": theme.ink,
        "ytick.color": theme.ink,
    }


def draw_trades(
    *, rows: list[dict[str, Any]], primary: dict[str, Any], title: str, theme: Theme
) -> bytes:
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import font_manager, rc_context
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.patches import Patch
    from matplotlib.ticker import PercentFormatter

    font_manager.findfont(theme.font_family, fallback_to_default=False)
    palette = {
        name: theme.series_colour(i)
        for i, name in enumerate(("stop", "target", "time", "opposite"))
    }
    with rc_context(_style(theme)):
        figure = Figure(figsize=(16, 9), dpi=100)
        FigureCanvasAgg(figure)
        top, bottom = figure.subplots(2, 1, height_ratios=[3, 2])
        done = sorted(
            (r for r in rows if r["net_return"] is not None),
            key=lambda r: (r["entry_ts"], r["asset"], r["candidate_id"]),
        )
        reasons = {"stop-gap": "stop", "max-hold": "time"}
        if any(r["reason"] == "open-at-end" for r in done):
            palette["open-at-end"] = theme.faint
        top.bar(
            range(len(done)),
            [r["net_return"] for r in done],
            color=[palette[reasons.get(r["reason"], r["reason"])] for r in done],
        )
        top.legend(
            handles=[
                Patch(
                    color=c,
                    label="Open at end (marked only)"
                    if k == "open-at-end"
                    else f"{k.title()} exit",
                )
                for k, c in palette.items()
            ],
            loc="upper left",
            facecolor=theme.panel,
            labelcolor=theme.ink,
        )
        top.set_xlabel("Trades in entry-date order (open-at-end bars are marked only)")
        top.set_ylabel("Trade return after costs")
        if primary["random_date_5"] is not None:
            bottom.axhspan(
                primary["random_date_5"],
                primary["random_date_95"],
                color=theme.ink_dim,
                alpha=0.25,
                label="Random dates: middle 90% of their average returns",
            )
        if primary["drift_mean"] is not None:
            bottom.axhline(
                primary["drift_mean"],
                color=theme.ink,
                linestyle="--",
                label="Same exits started on any day",
            )
        if primary["mean"] is not None:
            bottom.plot(
                [0],
                [primary["mean"]],
                "o",
                color=theme.accent,
                markersize=10,
                label="Average completed trade after this setup",
            )
            bottom.annotate(
                f"{primary['trades']} trades; {primary['hit_rate']:.1%} hit rate",
                (0, primary["mean"]),
                xytext=(20, 12),
                textcoords="offset points",
            )
            bottom.legend(loc="upper left", facecolor=theme.panel, labelcolor=theme.ink)
        else:
            bottom.text(
                0.5,
                0.5,
                "No completed trades; controls unavailable",
                ha="center",
                transform=bottom.transAxes,
            )
        bottom.set_xlim(-1, 1)
        bottom.set_xticks([])
        bottom.set_ylabel("Average net return per trade")
        for axes in (top, bottom):
            axes.axhline(0, color=theme.faint, linewidth=0.8)
            axes.yaxis.set_major_formatter(PercentFormatter(1))
            axes.grid(color=theme.grid, linewidth=0.4)
            axes.set_axisbelow(True)
        figure.subplots_adjust(left=0.09, right=0.97, top=0.88, bottom=0.12, hspace=0.35)
        figure.text(0.05, 0.96, title, fontsize=16, va="top")
        figure.text(
            0.05,
            0.04,
            "Long trades after costs. Open-at-end trades excluded from the mean. "
            "One counted exploratory test; not confirmed on reserved data.",
            fontsize=11,
        )
        buffer = BytesIO()
        figure.savefig(buffer, format="png", dpi=100, metadata={"Software": None})
        figure.clear()
        return buffer.getvalue()


def trade_text(output: dict[str, Any]) -> str:
    row = output["pooled"]
    lines = [output["reading"], "measure\tvalue"]
    for title, field, percent in (
        ("trades", "trades", False),
        ("mean", "mean", True),
        ("median", "median", True),
        ("hit rate", "hit_rate", True),
        ("bars held", "mean_bars_held", False),
        ("drift", "drift_mean", True),
        ("excess", "excess", True),
        ("random-date p", "random_date_p", True),
    ):
        value = row[field]
        text = "unavailable" if value is None else f"{value:.2%}" if percent else str(value)
        lines.append(f"{title}\t{text}")
    lines.extend(
        [
            "by reason\t" + ", ".join(f"{k}: {v}" for k, v in row["by_reason"].items()),
            "Labels: " + ", ".join(label.replace("-", " ") for label in output["labels"]),
            output["folder"],
            f"Next: alpha results cite {output['trade_id']} setup_trade_mean_net_return",
        ]
    )
    return "\n".join(lines)


def study_text(output: dict[str, Any]) -> str:
    lines = [output["reading"]]
    primary = str(output["primary_horizon"])
    for group, keys in (
        ("Primary horizon", [primary]),
        ("Also looked at, not tested", [k for k in output["horizons"] if k != primary]),
    ):
        if not keys:
            continue
        lines.extend([group.lower(), "bars\toccurrences\tmean\tmedian\thit rate\tdrift\texcess"])
        for key in keys:
            row = output["horizons"][key]["pooled"]
            values = [
                "unavailable" if row[k] is None else f"{row[k]:.2%}"
                for k in ("mean", "median", "hit_rate", "drift_mean", "excess")
            ]
            lines.append(
                "\t".join(
                    [
                        key + (" (primary)" if key == primary else ""),
                        str(row["occurrences"]),
                        *values,
                    ]
                )
            )
    lines.extend(
        [
            "Labels: " + ", ".join(label.replace("-", " ") for label in output["labels"]),
            output["folder"],
            f"Next: alpha results cite {output['study_id']} setup_mean_net_return",
        ]
    )
    return "\n".join(lines)
