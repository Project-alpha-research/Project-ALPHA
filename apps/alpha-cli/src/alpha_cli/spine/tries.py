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


def reading_count_sentence(family: dict[str, Any], symbol: str) -> str | None:
    """How one stored reading's deflated-Sharpe count relates to the headline on ``symbol``.

    The deflated Sharpe counts the larger of its rule family's tests on any asset and the tries on
    the asset, plus the nearby settings it scored. ``family`` is `diagnostics.trials.family`."""
    used = family.get("n_trials_used")
    if not isinstance(used, int) or isinstance(used, bool):
        return None
    this_run = int(family.get("this_run") or 0)
    variants = int(family.get("variants_scored") or 0)
    unknown = int(family.get("unknown_rows") or 0)
    on_family = int(family.get("prior_trials") or 0) + this_run + unknown
    on_asset = int(family.get("same_asset_tests") or 0) + this_run
    head = f"This reading's deflated Sharpe counts {used} tries: "
    settings = f"plus {variants} nearby settings."
    if on_family >= on_asset and used == on_family + variants:
        return f"{head}{on_family} tests of {family.get('family_id')} on any asset, {settings}"
    if used == on_asset + variants:
        return f"{head}the {on_asset} tries on {symbol}, {settings}"
    return f"{head}see alpha ledger families for its parts."


__all__ = ["DEFINITION", "reading_count_sentence", "sentence", "tries"]
