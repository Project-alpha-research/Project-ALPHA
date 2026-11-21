"""What the owner may confirm on the reserved period: one frozen, stored rule test.

The frozen test is the exact stored `alpha test` run: its spec (rule, parameters, costs), its asset
and store, its data identity (the test key) and its engine settings (seed, quick, diagnostics). The
owner can change none of these. The reserved span is fixed when the owner asks (its last stored
bar), so a resumed run reads the same bars. Nothing here reads a price from the reserved period.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from alpha_cli import _artifacts, reserved_slots
from alpha_cli.spine import reserve
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.facts import read_json
from alpha_cli.spine.ledger import read_trials_readonly
from alpha_cli.spine.spec import IdeaSpec
from alpha_cli.spine.stores import resolve_asset
from alpha_cli.spine.trial_record import row_test_key
from alpha_core.reserve import RESERVED_START

KIND = "reserved_confirmation"
CONSEQUENCES = (
    "This uses 1 of the 10 slots for the reserved period.",
    "It cannot be undone.",
    "This rule, with any settings, can never be confirmed again on this asset.",
    "The result is recorded and shown, whatever it is; it cannot be discarded.",
)


def _refuse(code: str, message: str, next_step: str) -> SpineError:
    return SpineError(code, message, next_step)


@dataclass(frozen=True)
class Frozen:
    """One stored rule test, exactly as it ran, and the reserved bars it would meet."""

    run_id: str
    idea: IdeaSpec
    asset: str
    symbol: str
    store: str
    rule: str
    test_key: list[Any]
    seed: int
    quick: bool
    no_diagnose: bool
    periods_per_year: int
    periods_per_year_basis: str
    reading: dict[str, Any]
    reserved_first: str
    reserved_end: str
    reserved_bars: int

    def record(self) -> dict[str, Any]:
        """The canonical frozen test: what the owner's yes and the slot receipt are bound to."""
        body = {
            "kind": "reserved-period-confirmation",
            "run_id": self.run_id,
            "spec_sha256": self.idea.spec_sha256,
            "asset": self.asset,
            "symbol": self.symbol,
            "store": self.store,
            "rule": self.rule,
            "test_key": self.test_key,
            "seed": self.seed,
            "quick": self.quick,
            "no_diagnose": self.no_diagnose,
            "periods_per_year": self.periods_per_year,
            "reserved_start": RESERVED_START,
            "reserved_first": self.reserved_first,
            "reserved_end": self.reserved_end,
            "reserved_bars": self.reserved_bars,
        }
        return {
            **body,
            "artifact_hash": reserved_slots.sha256(body),
            "test_key_sha256": reserved_slots.sha256(self.test_key),
            "family_asset": reserve.family_asset(self.rule, self.symbol),
        }


def _stored_row(home: Path, run_id: str) -> dict[str, Any]:
    for row in read_trials_readonly(home):
        if row.get("run_id") == run_id and "error" not in (row.get("labels") or ()):
            if row.get("kind", "rule_test") != "rule_test":
                break
            return row
    raise _refuse(
        "NOT_A_RULE_TEST",
        f"Run {run_id} is not a stored rule test. Only an `alpha test` run can be confirmed; "
        "a Setup Lab run cannot be confirmed yet.",
        "Run alpha confirm list, or alpha test <spec> first.",
    )


def frozen_test(home: Path, run_id: str, *, reserved_end: str | None = None) -> Frozen:
    """The frozen test of a stored run; refuses a run that cannot be confirmed (spends nothing)."""
    row = _stored_row(home, run_id)
    folder = _artifacts.run_dir(home, run_id)
    manifest = read_json(folder / "manifest.json")
    spine = manifest.get("spine") or {}
    labels = list(spine.get("labels") or [])
    if reserve.seen(spine.get("data_period", {}).get("last_ts"), manifest):
        raise _refuse(
            "RESERVED_PERIOD_SEEN",
            f"Run {run_id} used data from {RESERVED_START} on, so that period is not unseen "
            "for it.",
            "Run alpha test again; the new run holds the period back. Confirm that run.",
        )
    stored = read_json(folder / "spec.json")
    sha = stored.pop("spec_sha256", None)
    idea = IdeaSpec.model_validate(stored)
    if not (sha == idea.spec_sha256 == row.get("spec_sha256") == spine.get("spec_sha256")):
        raise _refuse(
            "SPEC_CHANGED",
            f"The stored spec of run {run_id} does not match its record.",
            "Run alpha test <spec> again and confirm the new run.",
        )
    key = row_test_key(row)
    asset = None
    for name in idea.assets:
        found = resolve_asset(name, data_dir=home)
        if (found.symbol, found.store_name) == (row["symbol"], row["store"]):
            asset = name
    if key is None or asset is None:
        raise _refuse(
            "NOT_A_RULE_TEST",
            f"Run {run_id} has no complete test record (spec, asset, store and data).",
            "Run alpha test <spec> again and confirm the new run.",
        )
    resolved = resolve_asset(asset, data_dir=home)
    until = datetime.fromisoformat(reserved_end) if reserved_end else None
    n, first, last = reserve.reserved_span(resolved, until)
    if n == 0 or first is None or last is None:
        raise _refuse(
            "NO_RESERVED_BARS",
            f"No {resolved.symbol} bars from {RESERVED_START} on are stored, so there is "
            "nothing to confirm on.",
            "Refresh the data first (alpha nightly or alpha data).",
        )
    return Frozen(
        run_id=run_id,
        idea=idea,
        asset=asset,
        symbol=resolved.symbol,
        store=resolved.store_name,
        rule=idea.rule.kind,
        test_key=[list(v) if isinstance(v, tuple) else v for v in key],
        seed=int(manifest["metadata"]["seed"]),
        quick="quick" in labels,
        no_diagnose="no-diagnostics" in labels,
        periods_per_year=int(spine["annualisation"]["periods_per_year"]),
        periods_per_year_basis=str(spine["annualisation"]["basis"]),
        reading=dict(manifest.get("reading") or {}),
        reserved_first=first.isoformat(),
        reserved_end=last.isoformat(),
        reserved_bars=n,
    )


def refuse_spent(frozen: Frozen, home: Path) -> None:
    """A test, run or family already confirmed, or no slot left: refuse before asking anyone."""
    record = frozen.record()
    found = reserved_slots.receipts(home)
    for item in found:
        if item["family_asset"] == record["family_asset"] or item["run_id"] == frozen.run_id:
            raise _refuse(
                "ALREADY_CONFIRMED",
                f"A {frozen.rule} rule on {frozen.symbol} was already confirmed (slot "
                f"{item['slot']}, {str(item['created_at'])[:10]}). A second look at the same "
                "period is not a fresh confirmation.",
                f"Run alpha confirm show {item['receipt_id']}.",
            )
    if len(found) >= reserved_slots.SLOTS:
        raise _refuse(
            "NO_SLOTS_LEFT",
            f"All {reserved_slots.SLOTS} slots for the reserved period are used.",
            "Run alpha confirm list.",
        )


def plan(home: Path, run_id: str) -> dict[str, Any]:
    """What would be tested and what it costs. Read-only: it writes nothing anywhere."""
    frozen = frozen_test(home, run_id)
    used = len(reserved_slots.receipts(home))
    refuse_spent(frozen, home)
    record = frozen.record()
    return {
        "frozen": record,
        "spec": frozen.idea.model_dump(mode="json"),
        "rule": {
            "kind": frozen.rule,
            "params": frozen.idea.rule.params,
            "costs": frozen.idea.costs.model_dump(mode="json"),
            "name": frozen.idea.name,
        },
        "slots": {"used": used, "left": reserved_slots.SLOTS - used, "total": reserved_slots.SLOTS},
        "consequences": list(CONSEQUENCES),
        "earlier_reading": frozen.reading,
    }


__all__ = ["CONSEQUENCES", "KIND", "Frozen", "frozen_test", "plan", "refuse_spent"]
