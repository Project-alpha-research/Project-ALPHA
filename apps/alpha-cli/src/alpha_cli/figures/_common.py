"""Shared builder plumbing: number formats, the build context and indicator unit labels."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpha_research.figures import FigureSpec, Panel, figure_definition
from alpha_research.figures.spec import XKind

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# --------------------------------------------------------------------------- formatting
def pct(value: float, places: int = 1) -> str:
    return f"{value * 100:.{places}f}%"


def mult(value: float) -> str:
    return f"{value:.2f}x"


def money(value: float) -> str:
    return f"{value:,.0f}"


def _day(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%d")


class BuildContext:
    """Everything a builder is allowed to read."""

    def __init__(self, *, run_id: str, rdir: Path, manifest: dict[str, Any], data_dir: Path):
        self.run_id = run_id
        self.rdir = rdir
        self.manifest = manifest
        self.data_dir = data_dir

    def field(self, *names: str) -> object:
        """Read a manifest field from the top level or the metadata block.

        Run kinds disagree about where identity lives: a backtest puts `symbol` at the
        top level, a validate run nests it under `metadata`. Callers should not care.
        """
        metadata = self.manifest.get("metadata")
        nested = metadata if isinstance(metadata, dict) else {}
        for name in names:
            for source in (self.manifest, nested):
                value = source.get(name)
                if value not in (None, "", []):
                    return value
        return None

    @property
    def command(self) -> str:
        value = self.manifest.get("command")
        return value if isinstance(value, str) else "unknown"

    @property
    def symbol(self) -> str:
        value = self.field("symbol", "label")
        if isinstance(value, str):
            return value
        symbols = self.field("symbols")
        if isinstance(symbols, list) and symbols:
            return ", ".join(str(item) for item in symbols[:4])
        return "-"

    @property
    def strategy(self) -> str:
        value = self.field("strategy", "strategy_name")
        return value if isinstance(value, str) else self.command

    def subtitle(self, extra: str = "") -> str:
        parts = [self.symbol, self.strategy]
        window = self._window()
        if window:
            parts.append(window)
        if extra:
            parts.append(extra)
        return "  ·  ".join(parts)

    def _window(self) -> str:
        start = self.field("start", "first_ts")
        end = self.field("end", "last_ts")
        if isinstance(start, str) and isinstance(end, str):
            return f"{start[:10]} to {end[:10]}"
        return ""

    def caption(self, *artifacts: str) -> str:
        snapshot = self.field("snapshot_hash")
        short = snapshot[:8] if isinstance(snapshot, str) and snapshot else "no snapshot"
        version = self.manifest.get("artifact_contract_version", "-")
        sources = " ".join(sorted(artifacts))
        return f"run {self.run_id} · snapshot {short} · contract v{version} · UTC · {sources}"

    def spec(
        self,
        figure_id: str,
        *,
        panels: tuple[Panel, ...],
        x_label: str,
        x_kind: XKind = "time",
        answer: str,
        artifacts: tuple[str, ...],
        truncation: str | None = None,
        x_categories: tuple[str, ...] = (),
    ) -> FigureSpec:
        definition = figure_definition(figure_id)
        return FigureSpec(
            figure_id=figure_id,
            title=definition.title,
            subtitle=self.subtitle(),
            x_label=x_label,
            x_kind=x_kind,
            x_categories=x_categories,
            panels=panels,
            question=definition.question,
            plain_language_answer=answer,
            uncertainty=definition.uncertainty,
            caveat=definition.caveat,
            caption=self.caption(*artifacts),
            source_artifacts=artifacts,
            truncation_note=truncation,
        )


def _truncation(original: int, returned: int, noun: str) -> str | None:
    """A figure must never lie by omission about how much it is showing."""
    if returned >= original:
        return None
    return f"showing {returned:,} of {original:,} {noun}"


_INDICATOR_UNITS = {
    "price",
    "ratio",
    "percent",
    "count",
    "days",
    "sharpe",
    "weight",
    "correlation",
    "probability",
    "z_score",
    "index",
    "seconds",
    "multiple",
    "account_currency",
}

#: An axis label must carry a unit a reader recognises, not the vocabulary token -- and it
#: must fit: these are budgeted for a short stacked panel, so every one stays under about
#: 22 characters rather than eliding into a shrug.
_UNIT_LABELS = {
    "account_currency": "Amount (account ccy)",
    "correlation": "Correlation (-1 to 1)",
    "count": "Count (n)",
    "days": "Duration (days)",
    "index": "Level (index points)",
    "multiple": "Multiple (x)",
    "percent": "Percent (%)",
    "price": "Price (native quote)",
    "probability": "Probability (0-1)",
    "ratio": "Ratio (unitless)",
    "seconds": "Duration (seconds)",
    "sharpe": "Sharpe (annualised)",
    "weight": "Weight (fraction)",
    "z_score": "Z-score (sigma)",
}


def _indicator_unit(raw: str) -> str:
    """Map a strategy-declared indicator unit onto the closed panel vocabulary.

    Strategies author their own unit strings; anything unrecognised is shown as a plain
    ratio rather than silently claiming to be a price.
    """
    return raw if raw in _INDICATOR_UNITS else "ratio"
