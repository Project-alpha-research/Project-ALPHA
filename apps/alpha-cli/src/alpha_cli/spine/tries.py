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

from alpha_cli.spine.trial_reader import LedgerSnapshot
from alpha_cli.spine.trial_record import TestKey, row_test_key

DEFINITION = (
    "A try is one distinct test on an asset (one spec on one stretch of one asset's data, with a "
    "Sharpe, or one screen try); repeats and errors are not tries. The deflated Sharpe of a test "
    "on that asset counts at least this many."
)
UNKNOWN = "not recorded"


# The deflated Sharpe's same-asset count reads this too (`deflation.same_asset_tests`); it lives
# here so the ledger commands need no statistics library.
def distinct_asset_tests(
    snapshot: LedgerSnapshot, symbol: str | None
) -> tuple[list[tuple[tuple[str, int], dict[str, Any]]], int, set[TestKey]]:
    """The distinct tests on one asset (every asset when ``symbol`` is None): the rows kept, with
    their ledger keys, the rows not counted, and the test keys seen.

    A row is scored when it has a Sharpe and a bar size. Scored rows of one test key count once;
    a row without a key counts as its own test unless it is labelled repeat (same run id).
    """
    seen: set[TestKey] = set()
    kept: list[tuple[tuple[str, int], dict[str, Any]]] = []
    repeats = 0
    for where, row in snapshot.raw_rows.items():
        scored = row.get("oos_sharpe") is not None and bool(row.get("periods_per_year"))
        # A screen try has no Sharpe; it is a try on this asset all the same (never a zero).
        if not (scored or row.get("kind") == "screen_trial"):
            continue
        if not row.get("symbol") or (symbol is not None and row.get("symbol") != symbol):
            continue
        key = row_test_key(row)
        # A keyed row is matched by its key alone, so a labelled repeat whose earlier row has no
        # Sharpe still counts once; a key-less row is a repeat only by its label (same run id).
        if key in seen or (key is None and "repeat" in (row.get("labels") or ())):
            repeats += 1
            continue
        if key is not None:
            seen.add(key)
        kept.append((where, row))
    return kept, repeats, seen


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


def _ideas(total: int) -> str:
    return f"{total} {'idea' if total == 1 else 'ideas'}"


def sentence(found: dict[str, Any]) -> str:
    """One plain sentence: how many ideas were tested on the asset, and under which rule shapes."""
    where = f"on {found['asset']}" if found["asset"] else "on all assets"
    parts = ", ".join(f"{name} {n}" for name, n in found["by_family"].items())
    by_shape = f" (by rule shape: {parts})" if parts else ""
    return f"You have tested {_ideas(found['total'])} {where}{by_shape}."


def reading_count_sentence(family: dict[str, Any], symbol: str) -> str | None:
    """The one paragraph that states the three counts of a stored reading and how they relate.

    It opens with "When this run was stored: ", so the reader knows the counts are the stored ones.
    The deflated Sharpe counts the larger of its rule shape's tests on any asset and the tests on
    the asset, plus the nearby settings it scored. ``family`` is `diagnostics.trials.family`.
    Printed the same wherever a count is shown; the numbers are the stored ones."""
    used = family.get("n_trials_used")
    if not isinstance(used, int) or isinstance(used, bool):
        return None
    this_run = int(family.get("this_run") or 0)
    variants = int(family.get("variants_scored") or 0)
    unknown = int(family.get("unknown_rows") or 0)
    on_shape = int(family.get("prior_trials") or 0) + this_run + unknown
    on_asset = int(family.get("same_asset_tests") or 0) + this_run
    lead = "When this run was stored: "
    shape = f"This rule shape [{family.get('family_id')}]"
    first = f"You have tested {_ideas(on_asset)} on {symbol}, counting this asset alone."
    if used != max(on_shape, on_asset) + variants:
        return f"{lead}{first} The luck adjustment counts {used} tries in all."
    times = "time" if on_shape == 1 else "times"
    settings = "setting" if variants == 1 else "settings"
    return (
        f"{lead}{first} {shape} has been tried {on_shape} {times} across all assets, "
        "which can be more than the first count. "
        f"It also had {variants} nearby {settings} tried inside this test. "
        "The luck adjustment adds those nearby settings to the larger of the first two counts, "
        f"which makes {used} tries in all."
    )


__all__ = ["DEFINITION", "reading_count_sentence", "sentence", "tries"]
