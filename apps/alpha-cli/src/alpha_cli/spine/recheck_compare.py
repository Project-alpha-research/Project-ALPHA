"""Compare a stored result with the same test computed again. Pure reads; nothing is written.

Every field of the manifest, the diagnostics, the spec and every parquet table is compared,
except the short list in `SKIPPED` (each says why). Integers, labels and words must be equal.
Floats must be equal within `rel=1e-9, abs=1e-12`; the engine is meant to be bit-deterministic,
the tolerance only lets a different summation order or platform pass, and `bit_identical` says
whether every float was in fact equal. A field or file present on one side only is a difference.
"""

from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REL_TOL = 1e-9
ABS_TOL = 1e-12
MISMATCH_EXIT = 4
# Fields that say which code ran or which health report was read, not what was computed.
# The code identity is reported as `code_changed`; the data identity (`source_fingerprint`)
# is compared. `artifacts.*.sha256` and `size_bytes` are file bytes: the tables are compared
# value by value instead. `spine.test_id` names the command that wrote the run.
SKIPPED = {
    "manifest": {"execution_fingerprint", "strategy_fingerprint", "data_health"},
    "spine": {"test_id"},
    "artifact": {"sha256", "size_bytes"},
}
# Statements added to new runs after older runs were written: `spine.costs` and `reading.costs`
# restate the spec's costs (the fee and slippage are compared in the spec fields). An older run
# that lacks one is compared without it, so a recheck of it still matches.
ADDED_LATER = (("spine", "costs"), ("reading", "costs"))
HEALTH_LABEL = "data-health-"
MISSING = "<missing>"
UNCOMPARED_FILES = {"tearsheet.html", "manifest.json", "diagnostics.json"}


@dataclass
class Comparison:
    differences: list[dict[str, Any]] = field(default_factory=list)
    bit_identical: bool = True

    def add(self, other: Comparison) -> None:
        self.differences.extend(other.differences)
        self.bit_identical = self.bit_identical and other.bit_identical


def _float_same(left: float, right: float) -> tuple[bool, bool]:
    """(within tolerance, bit-identical); two NaN are equal (the same computation again)."""
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
    """Every leaf of two JSON-like trees. A key or item on one side only is a difference."""
    out = Comparison()
    if isinstance(stored, dict) and isinstance(fresh, dict):
        for key in sorted({*stored, *fresh}, key=str):
            name = f"{prefix}.{key}"
            if key not in stored or key not in fresh:
                left = stored.get(key, MISSING)
                out.differences.append(
                    {"field": name, "stored": left, "recomputed": fresh.get(key, MISSING)}
                )
                continue
            out.add(diff_trees(stored[key], fresh[key], name))
    elif isinstance(stored, list) and isinstance(fresh, list):
        if len(stored) != len(fresh):
            out.differences.append(
                {"field": f"{prefix}.length", "stored": len(stored), "recomputed": len(fresh)}
            )
        for index, (left, right) in enumerate(zip(stored, fresh, strict=False)):
            out.add(diff_trees(left, right, f"{prefix}[{index}]"))
    else:
        _leaf(stored, fresh, prefix, out)
    return out


def _read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {"<not an object>": value}


def without_health(labels: object) -> object:
    """Labels without the health-report labels (they describe the report, not the result)."""
    if not isinstance(labels, list):
        return labels
    return [x for x in labels if not (isinstance(x, str) and x.startswith(HEALTH_LABEL))]


def _manifest_view(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    view = {k: v for k, v in manifest.items() if k not in SKIPPED["manifest"]}
    spine = view.get("spine")
    if isinstance(spine, dict):
        spine = {k: v for k, v in spine.items() if k not in SKIPPED["spine"]}
        spine["labels"] = without_health(spine.get("labels"))
        view["spine"] = spine
    artifacts = view.get("artifacts")
    if isinstance(artifacts, dict):
        view["artifacts"] = {
            name: {k: v for k, v in entry.items() if k not in SKIPPED["artifact"]}
            if isinstance(entry, dict)
            else entry
            for name, entry in artifacts.items()
        }
    return view


def _diagnostics_view(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if document is None:
        return None
    view = dict(document)
    macro = view.get("macro_window")
    if isinstance(macro, dict) and macro.get("available") is False:
        # The detail of "no macro data" names the home folder; the reason is still compared.
        view["macro_window"] = {k: v for k, v in macro.items() if k != "detail"}
    if "labels" in view:
        view["labels"] = without_health(view["labels"])
    return view


def table(source: Path | io.BytesIO) -> dict[str, Any]:
    """A parquet table as a JSON-like tree: its schema and every column's values."""
    import polars as pl

    frame = pl.read_parquet(source)
    columns = {}
    for name, dtype in frame.schema.items():
        series = frame[name]
        if dtype.is_temporal():
            series = series.cast(pl.String)
        columns[name] = series.to_list()
    return {"schema": {n: str(t) for n, t in frame.schema.items()}, "columns": columns}


def compare_files(stored: Path, fresh: Path, names: set[str]) -> Comparison:
    """Every named file present on either side: a parquet by value, a JSON file by tree."""
    out = Comparison()
    for name in sorted(names):
        left, right = stored / name, fresh / name
        if left.exists() != right.exists():
            out.differences.append(
                {
                    "field": f"file {name}",
                    "stored": "present" if left.exists() else MISSING,
                    "recomputed": "present" if right.exists() else MISSING,
                }
            )
        elif name.endswith(".parquet"):
            out.add(diff_trees(table(left), table(right), name))
        elif name.endswith(".json"):
            out.add(diff_trees(_read(left), _read(right), name))
    return out


def _names(folder: Path) -> set[str]:
    return {p.name for p in folder.iterdir() if p.is_file()} if folder.is_dir() else set()


def _without_added_later(
    stored: dict[str, Any] | None, fresh: dict[str, Any] | None
) -> dict[str, Any] | None:
    """The fresh manifest without the statements the stored run predates."""
    if stored is None or fresh is None:
        return fresh
    fresh = dict(fresh)
    for block, key in ADDED_LATER:
        old, new = stored.get(block), fresh.get(block)
        if isinstance(old, dict) and isinstance(new, dict) and key not in old:
            fresh[block] = {k: v for k, v in new.items() if k != key}
    return fresh


def compare_runs(stored: Path, fresh: Path) -> Comparison:
    """Every stored fact of a rule-test run against the same run computed again."""
    out = Comparison()
    old = _manifest_view(_read(stored / "manifest.json"))
    out.add(
        diff_trees(
            old,
            _without_added_later(old, _manifest_view(_read(fresh / "manifest.json"))),
            "manifest",
        )
    )
    out.add(
        diff_trees(
            _diagnostics_view(_read(stored / "diagnostics.json")),
            _diagnostics_view(_read(fresh / "diagnostics.json")),
            "diagnostics",
        )
    )
    out.add(compare_files(stored, fresh, (_names(stored) | _names(fresh)) - UNCOMPARED_FILES))
    return out
