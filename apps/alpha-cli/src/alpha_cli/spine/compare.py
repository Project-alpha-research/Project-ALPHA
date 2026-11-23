"""Pure comparisons of stored facts, shared by the table and citation checker."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Collection, Sequence
from typing import Any

from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.facts import METRIC_UNITS, require_metric
from alpha_cli.spine.label_meaning import label_block

Fact = dict[str, Any]
Lookup = Callable[[str, str], Fact]
DEFAULT_METRICS = (
    "oos_sharpe",
    "benchmark_sharpe",
    "full_sample_total_return",
    "full_sample_max_drawdown",
    "trades",
    "dsr",
)
COMPUTED_BASIS = "computed by alpha results compare from stored facts"


def resolve_run(prefix: str, known: Collection[str]) -> str:
    matches = (
        sorted(run for run in known if run.startswith(prefix.lower()))
        if re.fullmatch(r"[0-9a-fA-F]{8,16}", prefix)
        else []
    )
    if len(matches) != 1:
        raise SpineError(
            "AMBIGUOUS_RUN" if matches else "UNKNOWN_RUN",
            f"Run {prefix!r} matches {len(matches)} completed runs.",
            "Run alpha results --json and use an unambiguous run id of at least 8 hex digits.",
            matches or None,
        )
    return matches[0]


def numeric_fact(fact: Fact) -> Fact:
    """Keep JSON finite and explain values that cannot participate in arithmetic."""
    value = fact["value"]
    if value is None:
        return fact
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return {**fact, "value": None, "reason": "stored value is not numeric"}
    if not math.isfinite(value):
        return {**fact, "value": None, "reason": "stored value is not finite"}
    return fact


def derived_fact(base: Fact, other: Fact, operation: str) -> Fact:
    if operation not in ("diff", "ratio"):
        raise ValueError(f"Unknown comparison operation {operation!r}")
    base, other = numeric_fact(base), numeric_fact(other)
    reason = None
    value = None
    if base["value"] is None or other["value"] is None:
        reason = "; ".join(
            f"{f['run_id']}: {f['reason']}" for f in (base, other) if f["value"] is None
        )
    elif operation == "ratio" and base["value"] == 0:
        reason = "base value is zero"
    else:
        value = (
            other["value"] - base["value"]
            if operation == "diff"
            else other["value"] / base["value"]
        )
        if not math.isfinite(value):
            value, reason = None, "computed value is not finite"
    return {
        "value": value,
        "run_id": other["run_id"],
        "run_ids": [base["run_id"], other["run_id"]],
        "metric": other["metric"],
        "basis": COMPUTED_BASIS,
        "reason": reason,
    }


def compare_runs(
    run_ids: Sequence[str], lookup: Lookup, metrics: Sequence[str] = DEFAULT_METRICS
) -> Fact:
    if not 2 <= len(run_ids) <= 8:
        raise SpineError(
            "INVALID_RUN_COUNT",
            "Compare needs 2 to 8 runs.",
            "Run alpha results compare with 2 to 8 run ids.",
        )
    rows: dict[str, Any] = {}
    warnings = []
    runs: list[Fact] = []
    for metric in metrics:
        require_metric(metric)
        facts = [numeric_fact(lookup(run, metric)) for run in run_ids]
        if not runs:
            runs = [{"run_id": fact["run_id"], "labels": fact.get("labels", [])} for fact in facts]
        for i, left in enumerate(facts):
            for right in facts[i + 1 :]:
                if left["basis"] != right["basis"]:
                    warnings.append(
                        f"Mixed bases for {metric}: {left['run_id']} ({left['basis']}) "
                        f"and {right['run_id']} ({right['basis']})."
                    )
        rows[metric] = [
            {
                "value": fact,
                "diff": derived_fact(facts[0], fact, "diff"),
                "ratio": derived_fact(facts[0], fact, "ratio"),
            }
            for fact in facts
        ]
    return {"runs": runs, "metrics": rows, "warnings": warnings}


def _plain_number(metric: str, operation: str, value: Any) -> str:
    """A stored number for the screen, in the unit the metric declares (`METRIC_UNITS`)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return str(value)
    if operation == "ratio":
        return f"{value:.2f}x"
    if isinstance(value, int):
        return f"{value:,}"
    unit = METRIC_UNITS.get(metric)
    if unit == "fraction":
        return f"{value * 100:.1f} pts" if operation == "diff" else f"{value * 100:.1f}%"
    if unit == "bps":
        return f"{value:.1f} bps"
    if unit == "currency":
        return f"{value:,.2f}"
    return f"{value:.2f}"


def render_compare(result: Fact) -> str:
    """One column of values per run; each later run adds its change from, and ratio to, the first.

    The first run compared with itself (0 and 1.00x) says nothing, so its columns stay out."""
    headers = ["metric"]
    for index, run in enumerate(result["runs"]):
        headers.append(str(run["run_id"]))
        if index:
            headers.extend(("change from first", "ratio to first"))
    lines = ["\t".join(headers)]
    for metric, cells in result["metrics"].items():
        row = [metric]
        for index, cell in enumerate(cells):
            row.extend(
                _plain_number(metric, operation, f["value"])
                if f["value"] is not None
                else f"null ({f['reason']})"
                for operation, f in cell.items()
                if index or operation == "value"
            )
        lines.append("\t".join(row))
    for run in result["runs"]:
        lines.extend(
            label_block(run["labels"], f"{run['run_id']} labels:")
            or [f"{run['run_id']} labels: none"]
        )
    lines.extend(f"Warning: {warning}" for warning in result["warnings"])
    return "\n".join(lines)
