"""Run one owner-confirmed frozen test on the reserved period, once, and record what it shows.

Order, each step before the next: the owner's Touch ID yes (an authorization row), the frozen test
read again, the recheck of the earlier period (it must MATCH the stored run, else nothing is
spent), the slot receipt, and only then the read of reserved bars (`reserve.open_with_receipt`).
A run that stops after the receipt resumes with the same receipt and the same bars; it never takes
a new slot. The result is stored and shown whatever it is.
"""

from __future__ import annotations

import contextlib
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpha_cli import _artifacts, reserved_slots
from alpha_cli.spine import reserve
from alpha_cli.spine.confirm import KIND, Frozen, frozen_test, plan, summary
from alpha_cli.spine.data_health import health_labels, run_health_record, verify_inputs
from alpha_cli.spine.diagnose import staged_run
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.ledger import append_trial, read_trials
from alpha_cli.spine.reading import reading_word, stored_reading
from alpha_cli.spine.recheck import recheck_one
from alpha_cli.spine.run import (
    assemble_run_spec,
    gauntlet_knobs,
    new_result,
    prepare_bars,
    write_run,
)
from alpha_cli.spine.stores import resolve_asset
from alpha_core import DataError
from alpha_core.reserve import RESERVED_INSTANT, RESERVED_START


def _numbers(manifest: dict[str, Any]) -> dict[str, Any]:
    """One period's reading in numbers and words; no pass or fail, no advice."""
    reading = stored_reading(manifest)
    spine = manifest.get("spine") or {}
    return {
        "run_id": manifest.get("run_id"),
        "scored_from": (spine.get("traded_period") or {}).get("first_ts"),
        "scored_to": (spine.get("traded_period") or {}).get("last_ts"),
        "reading": reading_word(reading) if reading else None,
        "sentence": reading.get("sentence") if reading else None,
        "oos_sharpe": (manifest.get("oos_metrics") or {}).get("sharpe"),
        "labels": list(spine.get("labels") or []),
    }


# The one stored field the earlier period may differ in: the count of bars held back. It is not a
# computed result; it grows each time new bars from 2024-01-01 on are stored.
COUNT_ONLY = "manifest.spine.reserve.held_back_bars"


def _matches(found: dict[str, Any]) -> bool:
    """The recheck matched, except at most for the held-back count."""
    if found.get("match") is True:
        return True
    differences = found.get("differences") or []
    return (
        found.get("match") is False
        and found.get("differences_total") == len(differences) >= 1
        and all(d["field"] == COUNT_ONLY for d in differences)
    )


def _receipt_for(home: Path, run_id: str) -> dict[str, Any] | None:
    return next((r for r in reserved_slots.receipts(home) if r["run_id"] == run_id), None)


def _take(home: Path, run_id: str, authorization_id: str, now: datetime) -> dict[str, Any]:
    """Recheck the earlier period, then spend the slot. A refusal here spends nothing."""
    payload = reserved_slots.authorization_payload(home, authorization_id)
    reserved_end = str(payload["reserved_end"])
    if payload.get("summary") != summary(plan(home, run_id, reserved_end=reserved_end)):
        raise SpineError(
            "OWNER_WORDS_DIFFER",
            "The words the owner read before the touch do not describe this test as it is now "
            "(the slots, the code or the data changed, or the link was not from alpha confirm "
            "request). No slot was used.",
            f"Run alpha confirm plan {run_id}, then alpha confirm request {run_id} again.",
        )
    frozen = frozen_test(home, run_id, reserved_end=reserved_end)
    found = recheck_one(
        frozen.idea,
        frozen.asset,
        home=home,
        knobs=gauntlet_knobs(frozen.seed, frozen.quick),
        quick=frozen.quick,
        no_diagnose=frozen.no_diagnose,
    )["recheck"]
    if not _matches(found) or found.get("compared_with") != run_id:
        fields = ", ".join(str(d["field"]) for d in found.get("differences") or [])
        why = found.get("reason") or f"{found.get('differences_total')} differences: {fields}"
        raise SpineError(
            "RECHECK_MISMATCH",
            f"The earlier period, computed again, is not the same as stored run {run_id} "
            f"({why}; compared with {found.get('compared_with')}). No slot was used.",
            "Run alpha test <spec> --recheck to see the differences.",
        )
    return reserved_slots.take_slot(
        home, authorization_id=authorization_id, frozen=frozen.record(), now=now
    )


def _compute(home: Path, frozen: Frozen, receipt: dict[str, Any]) -> dict[str, Any]:
    """The same reading as the stored test, scored on the reserved bars only."""
    bars, dividends, snapshot_id = reserve.open_with_receipt(home, receipt["receipt_id"])
    first = next(i for i, bar in enumerate(bars) if bar.ts >= RESERVED_INSTANT)
    spec = assemble_run_spec(frozen.idea, frozen.symbol, frozen.periods_per_year, len(bars))
    start = first - spec.min_train - spec.embargo
    if start < 0:
        raise DataError("too few bars before 2024-01-01 to warm the rule up")
    used = bars[start:]
    held = [d for d in dividends if d.ex_date >= used[0].ts.date()]
    resolved = resolve_asset(frozen.asset, data_dir=home)
    result = new_result(frozen.asset, quick=frozen.quick, no_diagnose=frozen.no_diagnose)
    result["data_health"] = run_health_record([resolved])
    result["labels"].extend([*health_labels(result["data_health"]), reserve.CONFIRMATION])
    result.update(symbol=resolved.symbol, store=resolved.store_name, source=resolved.source)
    verify_inputs([resolved], result["data_health"])
    knobs = gauntlet_knobs(frozen.seed, frozen.quick)
    prepared = prepare_bars(
        frozen.idea,
        resolved,
        (used, held, snapshot_id),
        home,
        knobs,
        result,
        {"research_cutoff": None, "confirmation": receipt["receipt_id"], "of": frozen.run_id},
        ppy_given=(frozen.periods_per_year, frozen.periods_per_year_basis),
    )
    rdir = Path(result["run_dir"])
    if (rdir / "manifest.json").is_file():  # a resumed run that was already stored
        return _artifacts.read_manifest(rdir)
    test_id = f"confirm-slot-{receipt['slot']}"
    with staged_run(result) as staged, contextlib.redirect_stdout(io.StringIO()):
        manifest = write_run(frozen.idea, prepared, home, staged, knobs, test_id, result)
        scored = datetime.fromisoformat(manifest["spine"]["traded_period"]["first_ts"])
        if scored < RESERVED_INSTANT:
            raise DataError("the scored days would start before 2024-01-01; nothing stored")
    return manifest


def _ledger(home: Path, frozen: Frozen, receipt: dict[str, Any], manifest: dict[str, Any]) -> None:
    """One ledger row of its own kind; it is not a research trial and is never counted."""
    if any(row.get("receipt_id") == receipt["receipt_id"] for row in read_trials(home)):
        return
    spine = manifest["spine"]
    append_trial(
        home,
        {
            "kind": KIND,
            "test_id": spine["test_id"],
            "name": frozen.idea.name,
            "idea": frozen.idea.idea,
            "spec_sha256": frozen.idea.spec_sha256,
            "rule": frozen.rule,
            "params": frozen.idea.rule.params,
            "costs": frozen.idea.costs.model_dump(),
            "symbol": frozen.symbol,
            "store": frozen.store,
            "run_id": manifest["run_id"],
            "confirmed_run_id": frozen.run_id,
            "receipt_id": receipt["receipt_id"],
            "slot": receipt["slot"],
            "reserved_start": RESERVED_START,
            "reserved_end": frozen.reserved_end,
            "reserved_reading": _numbers(manifest),
            "labels": list(spine["labels"]),
        },
    )


def confirm_run(
    home: Path, run_id: str, *, authorization_id: str | None, now: datetime | None = None
) -> dict[str, Any]:
    """Confirm one frozen test once, or resume or show the one confirmation it already has."""
    stamp = now or datetime.now(UTC)
    receipt = _receipt_for(home, run_id)
    if receipt is None:
        if authorization_id is None:
            raise SpineError(
                "NO_OWNER_YES",
                "Confirming on the reserved period needs the owner's own Touch ID yes.",
                f"Run alpha confirm plan {run_id}, then alpha confirm request {run_id}.",
            )
        receipt = _take(home, run_id, authorization_id, stamp)
    if receipt["result"] is None:
        frozen = frozen_test(home, run_id, reserved_end=str(receipt["frozen"]["reserved_end"]))
        if frozen.record()["artifact_hash"] != receipt["frozen"]["artifact_hash"]:
            raise DataError("the stored test changed after its slot was spent; it cannot resume")
        manifest = _compute(home, frozen, receipt)
        _ledger(home, frozen, receipt, manifest)
        reserved_slots.record_result(
            home,
            receipt_id=receipt["receipt_id"],
            confirmation_run_id=str(manifest["run_id"]),
            result={"reserved": _numbers(manifest)},
            now=stamp,
        )
    return shown(home, run_id)


def shown(home: Path, run_id: str) -> dict[str, Any]:
    """A finished confirmation as stored: both periods side by side. Reads no reserved bar."""
    receipt = _receipt_for(home, run_id)
    if receipt is None or receipt["result"] is None:
        raise DataError(f"run {run_id} has no finished confirmation")
    done = receipt["result"]
    return {
        "receipt_id": receipt["receipt_id"],
        "slot": receipt["slot"],
        "slots_left": reserved_slots.SLOTS - len(reserved_slots.receipts(home)),
        "confirmed_run_id": run_id,
        "confirmation_run_id": done["confirmation_run_id"],
        "completed_at": done["completed_at"],
        "frozen": receipt["frozen"],
        "earlier": _numbers(_artifacts.read_manifest(_artifacts.run_dir(home, run_id))),
        "reserved": done["reserved"],
    }


__all__ = ["confirm_run", "shown"]
