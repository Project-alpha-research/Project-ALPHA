"""How many tries: one headline number wherever a count of tries is shown.

The words, each defined once:
- A ledger row is one line of `ledger/trials.jsonl`: every recorded run, errors and older repeats
  included. It is an audit sequence; no statistic reads the row count.
- A try is one distinct test on an asset: one test key (spec, asset, store, data window, bar size
  and data content) with a Sharpe, or one screen try. Repeats and errors are not tries.
- The headline number is the count of tries on an asset (or on every asset). It is the count of
  distinct tests on the asset that the deflated Sharpe of a test there counts at least.
`alpha ledger summary` breaks the headline down by kind and family; the parts add up to it.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from alpha_cli.spine.deflation import distinct_asset_tests
from alpha_cli.spine.trial_reader import LedgerSnapshot

DEFINITION = (
    "A try is one distinct test on an asset (one spec on one stretch of one asset's data, with a "
    "Sharpe, or one screen try); repeats and errors are not tries. The deflated Sharpe of a test "
    "on that asset counts at least this many."
)
UNKNOWN = "not recorded"


def tries(snapshot: LedgerSnapshot, symbol: str | None = None) -> dict[str, Any]:
    """The headline count of tries on ``symbol`` (every asset when None) and its parts."""
    kept, repeats, _ = distinct_asset_tests(snapshot, symbol)
    records = {(r.source_file, r.source_line): r for r in snapshot.records}
    kinds: Counter[str] = Counter()
    families: Counter[str] = Counter()
    for where, row in kept:
        record = records.get(where)
        kinds[record.kind if record else str(row.get("kind") or UNKNOWN)] += 1
        families[record.family_id if record else UNKNOWN] += 1
    return {
        "asset": symbol,
        "total": len(kept),
        "by_kind": dict(sorted(kinds.items())),
        "by_family": dict(sorted(families.items())),
        "rows_not_counted": repeats,
        "definition": DEFINITION,
    }


def sentence(found: dict[str, Any]) -> str:
    """One plain sentence: how many tries, on what, and of which kinds."""
    where = f"on {found['asset']}" if found["asset"] else "on all assets"
    total = found["total"]
    noun = "try" if total == 1 else "tries"
    parts = ", ".join(f"{name} {n}" for name, n in found["by_family"].items())
    return f"Tries {where}: {total} {noun}" + (f" ({parts})." if parts else ".")


__all__ = ["DEFINITION", "sentence", "tries"]
