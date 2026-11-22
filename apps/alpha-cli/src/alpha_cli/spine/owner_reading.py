"""What an owner-rule reading adds: the count sentence and the table of parameter variants.

Both only state numbers the diagnostics already hold. The table has no best pick and no verdict.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

OWNER_FAMILY_PREFIX = "owner:"


def count_sentence(counts: Mapping[str, Any]) -> str:
    """How many tests the deflated Sharpe counted, in the owner's words."""
    k, m, n = counts["shape_tests"], counts["asset_tests"], counts["n_used"]
    return (
        f"This rule shape: {k} tests on this data. All rules on {counts['asset']}: {m} tests. "
        f"The deflated Sharpe uses N = max({k}, {m}) = {n}."
    )


def owner_counts(
    rule_kind: str, symbol: str, shape_tests: int, asset_tests: int, n_used: int
) -> dict[str, Any] | None:
    """The three counts of an owner rule's family; None for the old rule kinds."""
    if not rule_kind.startswith(OWNER_FAMILY_PREFIX):
        return None
    return {
        "asset": symbol,
        "shape_tests": shape_tests,
        "asset_tests": asset_tests,
        "n_used": n_used,
    }


def variant_table(diagnostics: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One row of readings per variant, in the order they ran; a missing value keeps its reason."""
    variants = (diagnostics.get("sensitivity") or {}).get("variants") or []
    return [
        {
            "name": row["name"],
            "kind": row["kind"],
            "sharpe": row.get("sharpe"),
            "total_return": row.get("total_return"),
            "max_drawdown": row.get("max_drawdown"),
            "reasons": row.get("reasons") or {},
        }
        for row in variants
    ]


def reading_additions(diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    """The extra reading keys of an owner rule; nothing for any other rule."""
    counts = (diagnostics.get("trials") or {}).get("owner_counts")
    if not isinstance(counts, Mapping):
        return {}
    return {"count_sentence": count_sentence(counts), "variant_table": variant_table(diagnostics)}


def variant_lines(reading: Mapping[str, Any]) -> list[str]:
    """The variant table as text lines for the command line; empty when the reading has none."""
    rows = reading.get("variant_table") or []
    if not rows:
        return []

    def cell(value: Any) -> str:
        return "n/a" if value is None else f"{value:.3f}"

    lines = ["Variants (full-sample re-runs, same bars; readings, not a ranking):"]
    lines.append("VARIANT\tSHARPE\tTOTAL RETURN\tMAX DRAWDOWN")
    lines += [
        f"{row['name']}\t{cell(row['sharpe'])}\t{cell(row['total_return'])}\t"
        f"{cell(row['max_drawdown'])}"
        for row in rows
    ]
    return lines
