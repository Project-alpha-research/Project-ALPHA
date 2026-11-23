"""Plain text for `alpha results`: a table with headers, and a one-screen summary of one run."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from alpha_cli.spine.label_meaning import label_block

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
    if isinstance(value, dict) and {"first_ts", "last_ts"} <= value.keys():
        return f"{str(value['first_ts'])[:10]} to {str(value['last_ts'])[:10]}"
    return f"{value:.4g}" if isinstance(value, float) else cell(value)


# What a key number means, for the names an owner may not know.
GLOSS = {
    "inverted_sharpe": "Sharpe ratio of the opposite rule, as a check",
    "inverted_sharpe_se": "the likely error of that Sharpe ratio",
}


def summary_lines(run: dict[str, Any]) -> list[str]:
    """What fits on one screen: the numbers, counts of checks and flags, and where to read more."""
    lines: list[str] = []
    # A setup study or trade stores its reading and outcome as plain text: show both first.
    for key, label in (("reading", "Reading"), ("outcome", "Outcome")):
        if isinstance(run.get(key), str) and run[key].strip():
            lines.append(f"{label}: {run[key]}")
    # A setup find that failed for some assets says which, so partial coverage is visible.
    for asset in run.get("assets") or []:
        error = asset.get("error") if isinstance(asset, dict) else None
        if isinstance(error, dict):
            reason = error.get("message") or error.get("code") or "no reason stored"
            lines.append(f"Not completed: {asset.get('symbol') or 'an asset'}: {reason}")
    facts = [
        fact
        for fact in run.get("facts", [])
        if fact.get("value") is not None and fact.get("metric") != "verdict"
    ][:SHOWN_FACTS]
    if facts:
        lines.append("Key numbers:")
        lines += [
            f"  {fact['metric'].replace('_', ' ')}: {_number(fact['value'])}"
            + (f" ({GLOSS[fact['metric']]})" if fact["metric"] in GLOSS else "")
            for fact in facts
        ]
    audit = Counter(str(item.get("status")) for item in run.get("audit", []))
    if audit:
        lines.append(
            "Checks: " + ", ".join(f"{count} {word}" for word, count in sorted(audit.items()))
        )
    flags = run.get("flags") or []
    flagged = audit.get("flagged", 0)
    apart = (
        f" These are warnings from the diagnostic pass; the {flagged} flagged "
        f"{'check' if flagged == 1 else 'checks'} above are counted apart."
        if flags and flagged
        else ""
    )
    lines.append(f"Flags raised: {len(flags)}.{apart}" if flags else "Flags raised: none.")
    if run.get("labels"):
        lines.extend(label_block(run["labels"], "Labels:"))
    tools = run.get("tools") or []
    lines.append(f"Investigation tools run on it: {len(tools)}.")
    if run.get("charts"):
        lines.append("Charts: " + cell(run["charts"]))
    lines.append(f"Full detail: alpha results show {run['run_id']} --json")
    return lines
