"""Plain text for `alpha results`: a table with headers, and a one-screen summary of one run."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

SHOWN_FACTS = 8


def cell(value: object) -> str:
    """One table cell: a missing value is a dash, never a zero or an empty word."""
    if value is None or value == [] or value == "":
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    """Header line, then one line per row, columns padded to the widest cell."""
    body = [[cell(value) for value in row] for row in rows]
    widths = [max([len(head), *(len(row[i]) for row in body)]) for i, head in enumerate(headers)]

    def line(parts: Sequence[str]) -> str:
        return "  ".join(
            part.ljust(width) for part, width in zip(parts, widths, strict=True)
        ).rstrip()

    return [line(headers), *(line(row) for row in body)]


def _number(value: object) -> str:
    return f"{value:.4g}" if isinstance(value, float) else cell(value)


def summary_lines(run: dict[str, Any]) -> list[str]:
    """What fits on one screen: the numbers, counts of checks and flags, and where to read more."""
    lines: list[str] = []
    # A setup study or trade stores its reading and outcome as plain text: show both first.
    for key, label in (("reading", "Reading"), ("outcome", "Outcome")):
        if isinstance(run.get(key), str) and run[key].strip():
            lines.append(f"{label}: {run[key]}")
    facts = [
        fact
        for fact in run.get("facts", [])
        if fact.get("value") is not None and fact.get("metric") != "verdict"
    ][:SHOWN_FACTS]
    if facts:
        lines.append("Key numbers:")
        lines += [
            f"  {fact['metric'].replace('_', ' ')}: {_number(fact['value'])}" for fact in facts
        ]
    audit = Counter(str(item.get("status")) for item in run.get("audit", []))
    if audit:
        lines.append(
            "Checks: " + ", ".join(f"{count} {word}" for word, count in sorted(audit.items()))
        )
    flags = run.get("flags") or []
    lines.append(f"Flags raised: {len(flags)}." if flags else "Flags raised: none.")
    if run.get("labels"):
        lines.append("Labels: " + cell(run["labels"]))
    tools = run.get("tools") or []
    lines.append(f"Investigation tools run on it: {len(tools)}.")
    if run.get("charts"):
        lines.append("Charts: " + cell(run["charts"]))
    lines.append(f"Full detail: alpha results show {run['run_id']} --json")
    return lines
