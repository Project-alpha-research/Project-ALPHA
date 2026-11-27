"""Count a run's funnel from its receipt, rounds and recorded factor trials."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alpha_web._rdagent_run_files import FACTOR_SCHEMAS, _get, _lines, _object, counted, project
from alpha_web._rdagent_run_words import FUNNEL, REFUSED_STATUSES, SCREENED, SPREAD_CHECKED
from alpha_web.api.rdagent_models import RecordedFact


def _ledger_factor_rows(
    ledger_rows: list[dict[str, Any]], run_id: str, folder: Path
) -> list[dict[str, Any]]:
    """Older runs recorded their folder name, not the receipt's run id, in the ledger."""
    return [
        row
        for row in ledger_rows
        if row.get("run_id") in {run_id, folder.name} and row.get("schema") in FACTOR_SCHEMAS
    ]


def _funnel(
    receipt: dict[str, Any],
    factor_rows: list[dict[str, Any]] | None,
    rounds: list[dict[str, Any]] | None,
) -> dict[str, RecordedFact]:
    """Recorded funnel figures win; gaps are filled only by counting recorded rows."""
    recorded = _object(receipt.get("funnel", {}))
    result = project(recorded, FUNNEL)
    basis_rows = "counted from the recorded factor trials"
    if factor_rows == [] and rounds is None:
        factor_rows = None  # nothing at all was recorded for this run
    derived: dict[str, RecordedFact] = {}
    refused = None
    stopped = 0
    if rounds is not None:
        refused = sum(1 for row in rounds if row.get("status") in REFUSED_STATUSES)
        derived["refused_closed_family"] = counted(
            refused, "counted from the proposals refused in rounds.jsonl"
        )
        stopped = sum(
            len(row.get("factor_names", []))
            for row in rounds
            if str(row.get("status", "")).startswith(
                ("coding_failed_provider_", "proposal_failed_provider_")
            )
            and not row.get("trial_created")
        )
        derived["stopped_by_provider"] = counted(
            stopped, "factors stopped by the model provider, counted from rounds.jsonl"
        )
    if factor_rows is not None:
        own = [row for row in factor_rows if row.get("status") != "IMPORTED"]
        clocks = [
            clock
            for row in own
            for clock in _object(row.get("clocks") or {"daily": row}).values()
            if isinstance(clock, dict)
        ]
        derived["code_ran"] = counted(
            sum(1 for row in own if row.get("status") != "FAILED"), basis_rows
        )
        derived["passed_rank_screen"] = counted(
            sum(1 for row in own if _any_clock(row, SCREENED)), basis_rows
        )
        replayed = [c for c in clocks if c.get("status") in SPREAD_CHECKED]
        if all(_get(c, "spread.status") in ("PASS", "FAIL") for c in replayed):
            derived["passed_spread_check"] = counted(
                sum(1 for row in own if _any_clock(row, SPREAD_CHECKED)), basis_rows
            )
        else:
            derived["passed_spread_check"] = RecordedFact(
                value=None, reason="this run's trials were recorded before the spread check"
            )
        derived["passed_deflation"] = counted(
            sum(1 for row in own if _passed_deflation(row)), basis_rows
        )
        derived["shortlisted"] = (
            counted(sum(row["shortlist"] is True for row in own), basis_rows)
            if all(type(row.get("shortlist")) is bool for row in own)
            else RecordedFact(value=None, reason="shortlist not recorded for every factor trial")
        )
        if refused is not None:
            derived["proposed"] = counted(
                len(own) + refused + stopped,
                "recorded factor trials, proposals refused before coding (one proposal can"
                " hold several factors) and factors stopped by the model provider",
            )
    for key, value in derived.items():
        if result[key].value is None:
            result[key] = value
    return result


def _any_clock(row: dict[str, Any], statuses: frozenset[str]) -> bool:
    clocks = _object(row.get("clocks") or {"daily": row})
    return any(isinstance(c, dict) and c.get("status") in statuses for c in clocks.values())


def _passed_deflation(row: dict[str, Any]) -> bool:
    clocks = _object(row.get("clocks") or {"daily": row})
    return any(
        isinstance(c, dict) and _get(c, "replay.deflated_sharpe.passed") is True
        for c in clocks.values()
    )


def _ledger(ledger: Path) -> tuple[list[dict[str, Any]], str | None]:
    rows, reason = _lines(ledger.parent.parent, f"{ledger.parent.name}/{ledger.name}")
    return rows, "The factor trial ledger is absent." if not ledger.exists() else reason
