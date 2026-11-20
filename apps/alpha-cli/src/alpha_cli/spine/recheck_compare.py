"""Compare a stored result with the same test computed again. Pure reads; nothing is written.

Integers, labels and words must be equal. Floats must be equal within `rel=1e-9, abs=1e-12`.
The engine is meant to be bit-deterministic; the tolerance only lets a different summation
order or platform pass, and `bit_identical` says whether every float was in fact equal.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REL_TOL = 1e-9
ABS_TOL = 1e-12
MISMATCH_EXIT = 4
MANIFEST_KEYS = (
    "oos_metrics",
    "cis",
    "dsr",
    "verdict",
    "cpcv",
    "nulls",
    "outcomes",
    "passed",
    "folds",
    "resized_entries",
    "pretrade_rejections",
    "rejected",
    "research_cutoff",
)
READING_PATHS = (("measures",), ("counts",), ("evidence", "word"), ("aim", "rows"))
DIAGNOSTIC_KEYS = ("trials", "sensitivity", "variants_evaluated", "closed_oos_trades")
ENGINE_LABELS = ("quick", "no-diagnostics")
SERIES = ("equity", "gross_return", "cost_return")


@dataclass
class Comparison:
    differences: list[dict[str, Any]] = field(default_factory=list)
    bit_identical: bool = True

    def add(self, other: Comparison) -> None:
        self.differences.extend(other.differences)
        self.bit_identical = self.bit_identical and other.bit_identical


def _float_same(left: float, right: float) -> tuple[bool, bool]:
    """(within tolerance, bit-identical); two NaN are equal."""
    if math.isnan(left) or math.isnan(right):
        both = math.isnan(left) and math.isnan(right)
        return both, both
    return math.isclose(left, right, rel_tol=REL_TOL, abs_tol=ABS_TOL), left == right


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, float | int):
        return None
    return float(value)


def _leaf(stored: object, fresh: object, name: str, out: Comparison) -> None:
    left, right = _number(stored), _number(fresh)
    if (
        left is not None
        and right is not None
        and (isinstance(stored, float) or isinstance(fresh, float))
    ):
        same, exact = _float_same(left, right)
        out.bit_identical = out.bit_identical and exact
    else:
        same = type(stored) is type(fresh) and stored == fresh
    if not same:
        out.differences.append({"field": name, "stored": stored, "recomputed": fresh})


def diff_trees(stored: object, fresh: object, prefix: str) -> Comparison:
    """Every leaf of two JSON-like trees; a missing leaf reads as None."""
    out = Comparison()
    if isinstance(stored, dict) or isinstance(fresh, dict):
        if not (isinstance(stored, dict) and isinstance(fresh, dict)):
            _leaf(stored, fresh, prefix, out)
            return out
        for key in sorted({*stored, *fresh}):
            out.add(diff_trees(stored.get(key), fresh.get(key), f"{prefix}.{key}"))
    elif isinstance(stored, list) or isinstance(fresh, list):
        if not (isinstance(stored, list) and isinstance(fresh, list)):
            _leaf(stored, fresh, prefix, out)
            return out
        for index in range(max(len(stored), len(fresh))):
            left = stored[index] if index < len(stored) else None
            right = fresh[index] if index < len(fresh) else None
            out.add(diff_trees(left, right, f"{prefix}[{index}]"))
    else:
        _leaf(stored, fresh, prefix, out)
    return out


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _pick(tree: object, path: tuple[str, ...]) -> object:
    for step in path:
        tree = tree.get(step) if isinstance(tree, dict) else None
    return tree


def _series(stored: Path, fresh: Path) -> Comparison:
    import polars as pl

    out = Comparison()
    left, right = pl.read_parquet(stored), pl.read_parquet(fresh)
    out.add(diff_trees(left.height, right.height, "equity_curve.rows"))
    if left.height and right.height:
        out.add(diff_trees(left["equity"][-1], right["equity"][-1], "equity_curve.end"))
    if left.height != right.height:
        return out
    out.add(
        diff_trees(
            left["ts"].cast(pl.String).to_list(),
            right["ts"].cast(pl.String).to_list(),
            "equity_curve.ts",
        )
    )
    for name in SERIES:
        first = diff_trees(left[name].to_list(), right[name].to_list(), f"equity_curve.{name}")
        out.add(first)
    return out


def _count(path: Path) -> int:
    import polars as pl

    return int(pl.read_parquet(path).height)


def compare_runs(stored: Path, fresh: Path) -> Comparison:
    """The facts a report and its reading use, stored against recomputed."""
    out = Comparison()
    old, new = _read(stored / "manifest.json"), _read(fresh / "manifest.json")
    for key in MANIFEST_KEYS:
        out.add(diff_trees(old.get(key), new.get(key), f"manifest.{key}"))
    for path in READING_PATHS:
        label = ".".join(path)
        out.add(
            diff_trees(
                _pick(old.get("reading", {}), path),
                _pick(new.get("reading", {}), path),
                f"reading.{label}",
            )
        )
    engine = [
        sorted(set(ENGINE_LABELS) & set(m.get("spine", {}).get("labels", []))) for m in (old, new)
    ]
    out.add(diff_trees(engine[0], engine[1], "manifest.spine.engine_labels"))
    docs = _read(stored / "diagnostics.json"), _read(fresh / "diagnostics.json")
    for key in DIAGNOSTIC_KEYS:
        out.add(diff_trees(docs[0].get(key), docs[1].get(key), f"diagnostics.{key}"))
    out.add(_series(stored / "equity_curve.parquet", fresh / "equity_curve.parquet"))
    out.add(
        diff_trees(
            _count(stored / "trades.parquet"), _count(fresh / "trades.parquet"), "trades.count"
        )
    )
    return out
