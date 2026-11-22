"""The judge's trading costs: read from the one cost table, never kept here.

The judge scores a panel of spot coins, so it takes the table row for crypto spot. The row is read
at each call, so a change to the table reaches the next score. A stored score keeps the costs it
was made with; a row without a `costs` record was made before the judge read the table.
"""

from __future__ import annotations

from typing import Any

from alpha_cli.spine import cost_classes

JUDGE_COST_CLASS = "crypto_spot"


def judge_costs() -> dict[str, Any]:
    """The costs a new score uses, with their source, as `alpha test` records them."""
    row = cost_classes.ROWS[JUDGE_COST_CLASS]
    return {
        "fee_bps": row.fee_bps,
        "slippage_bps": row.slippage_bps,
        "source": cost_classes.CLASS_DEFAULT,
        "asset_class": JUDGE_COST_CLASS,
    }


def costs_text(costs: dict[str, Any]) -> str:
    return f"{costs['fee_bps']:g} bps fee + {costs['slippage_bps']:g} bps slippage per side"


def other_cost_rows(history: list[dict[str, Any]], costs: dict[str, Any]) -> int:
    """How many stored scores were made under costs other than `costs` (or none recorded)."""
    return sum(1 for row in history if row["status"] != "REPEAT" and row.get("costs") != costs)


def other_cost_note(count: int) -> str:
    """One plain sentence, or nothing when every stored score used the same costs."""
    if not count:
        return ""
    return (
        f"{count} earlier scores were made under other costs than these. They keep their own "
        "costs, are not re-scored, and still count as trials."
    )
