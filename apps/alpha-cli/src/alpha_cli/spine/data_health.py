"""Bind stored daily health evidence to the inputs of one rule test or setup."""

from __future__ import annotations

import json
import shlex
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from alpha_cli.spine.errors import SpineError
from alpha_core.reserve import RESERVED_DAY

if TYPE_CHECKING:
    from alpha_cli.spine.stores import ResolvedAsset


class HealthRecord(dict[str, Any]):
    """The health record as shown and stored: facts about the files, never a fingerprint of them.

    The stored bar file also holds the held-back rows. A hash of that file would move whenever a
    nightly pull appends or revises such a row, so it stays out of the record. The guard
    fingerprints that `verify_inputs` needs live on the object only and are never written.
    """

    guards: tuple[str, ...]

    def __init__(self, data: dict[str, Any], guards: tuple[str, ...]) -> None:
        super().__init__(data)
        self.guards = guards


def _held_back_only(check: Any) -> bool:
    """A problem whose every row is listed and falls on or after the reserved day.

    A check that lists no dates, or fewer dates than its count, may touch a row a test reads, so
    it is never set aside.
    """
    dates = check.example_dates
    return bool(dates) and check.count == len(dates) and min(dates) >= RESERVED_DAY


# In increasing order of severity. Stale evidence and absent evidence share a disclosure label.
_LABELS = {
    "pass": "data-health-pass",
    "warn": "data-health-warn",
    "unchecked": "data-health-unchecked",
    "out-of-date": "data-health-unchecked",
    "fail": "data-health-fail",
}


def _series(
    asset: ResolvedAsset, check_data: bool, report_time: datetime | None
) -> tuple[dict[str, Any], str]:
    """The shown facts of one series, and the guard fingerprint of the whole stored file."""
    from alpha_cli._data_health import compute_report, current_fingerprint, read_report

    store = asset.daily_store()
    saved = read_report(store, asset.symbol)
    fingerprint = current_fingerprint(store, asset.symbol, saved)
    if check_data and (saved is None or saved.source_fingerprint != fingerprint):
        saved = compute_report(
            store,
            asset.symbol,
            saved.universe_file if saved else None,
            report_time or datetime.now(UTC),
            use_peers=True,
        )
        fingerprint = saved.source_fingerprint
    outcome = "unchecked"
    checks = []
    held_problems = 0
    if saved is not None:
        outcome = saved.verdict if saved.source_fingerprint == fingerprint else "out-of-date"
        if outcome != "out-of-date":
            flagged = [c for c in saved.checks if c.status in {"warn", "fail"}]
            held = [c for c in flagged if _held_back_only(c)]
            held_problems = sum(c.count for c in held)
            if held:
                rest = [c.status for c in saved.checks if c not in held]
                outcome = "fail" if "fail" in rest else "warn" if "warn" in rest else "pass"
            checks = [
                c.model_dump(mode="json", include={"id", "status", "finding", "example_dates"})
                for c in flagged
                if c not in held
            ]
    shown = dict(
        asset=f"{asset.symbol}@{asset.store_name}",
        status=outcome,
        checks=checks,
        report_time=saved.report_time.isoformat() if saved else None,
        peers_used=len(saved.peer_symbols) if saved and saved.peer_symbols is not None else None,
        **({"held_back_problems": held_problems} if held_problems else {}),
    )
    return shown, fingerprint


def run_health_record(
    assets: Sequence[ResolvedAsset],
    *,
    check_data: bool = False,
    accept_bad_data: str | None = None,
    report_time: datetime | None = None,
) -> HealthRecord:
    if accept_bad_data is not None and not accept_bad_data.strip():
        raise SpineError(
            "BAD_OPTION",
            "--accept-bad-data needs a reason.",
            'Give the reason in quotes, for example --accept-bad-data "checked the raw prices".',
        )
    looked_up = [_series(a, check_data, report_time) for a in assets]
    series = [shown for shown, _ in looked_up]
    verdict = max((s["status"] for s in series), key=tuple(_LABELS).index)
    parts = [f"Data health: {verdict}."]
    failures = []
    for row in series:
        asset = row["asset"]
        for check in row["checks"]:
            parts.append(f"{asset}: {check['finding']}")
            if check["status"] == "fail":
                dates = ", ".join(check["example_dates"]) or "none recorded"
                name = check["id"].replace("_", " ")
                failures.append(f"{asset}, check {name}: {check['finding']} First dates: {dates}.")
        if row["status"] in {"unchecked", "out-of-date"}:
            why = (
                "No report" if row["status"] == "unchecked" else "The stored report is out of date"
            )
            parts.append(
                f"{asset}: {why}. Check it with alpha data health {shlex.quote(asset)}, "
                "or run again with --check-data."
            )
        else:
            # The report covers every stored bar at its report time, the held-back ones too.
            checked = f"{asset}: report of {row['report_time'][:10]} covers all stored bars."
            parts.append(checked)
            if row.get("held_back_problems"):
                n = row["held_back_problems"]
                parts.append(
                    f"{asset}: {n} {'problem' if n == 1 else 'problems'} "
                    "in held-back rows, not used."
                )
            if row["status"] == "fail":
                failures.append(checked)
        if row["status"] not in {"unchecked", "out-of-date"} and row["peers_used"] is not None:
            count = row["peers_used"]
            peer_count = f"{asset}: {count} stock {'peer' if count == 1 else 'peers'} used."
            parts.append(peer_count)
            if row["status"] == "fail":
                failures.append(peer_count)
    reason = accept_bad_data.strip() if accept_bad_data and verdict == "fail" else None
    if verdict == "fail" and not reason:
        step = 'Fix the data, or run again with --accept-bad-data "reason".'
        raise SpineError(
            "DATA_HEALTH_FAILED",
            " ".join(["Data health: fail.", *failures, step]),
            # A re-check with --check-data keeps the stock peers that made the split check fail.
            "After a repair, run the same command again with --check-data.",
        )
    if reason:
        parts.append(f"Data health overridden: {reason}.")
    record = dict(verdict=verdict, series=series, override_reason=reason, sentence=" ".join(parts))
    return HealthRecord(record, tuple(guard for _, guard in looked_up))


def health_labels(record: dict[str, Any]) -> list[str]:
    labels = [_LABELS[record["verdict"]]]
    if record["override_reason"]:
        labels.append("data-health-overridden")
    return labels


def health_sentence(record: dict[str, Any] | None) -> str:
    return record["sentence"] if record else "Data health: not recorded."


def identity_record(record: dict[str, Any]) -> dict[str, Any]:
    """What of a health record may enter an identity: the assets checked and the owner's override.

    The verdict, the report and its age describe the whole stored file, the held-back rows too, so
    they never enter an identity. The rows a test may read are fingerprinted on their own.
    """
    assets = [row["asset"] for row in record["series"]]
    return {"assets": assets, "override_reason": record["override_reason"]}


def identity_part(record: dict[str, Any]) -> str:
    return json.dumps(identity_record(record), sort_keys=True, separators=(",", ":"))


def identity_labels(labels: Sequence[str]) -> list[str]:
    """The labels that may enter an identity: no health label and no held-back label."""
    from alpha_cli.spine import reserve

    return [x for x in labels if not x.startswith("data-health-") and x != reserve.HELD_BACK]


def verify_inputs(assets: Sequence[ResolvedAsset], record: HealthRecord) -> None:
    """Reject a data promotion between the health lookup and the run's input read."""
    from alpha_cli._data_health import current_fingerprint, read_report

    for asset, row, guard in zip(assets, record["series"], record.guards, strict=True):
        store = asset.daily_store()
        fingerprint = current_fingerprint(store, asset.symbol, read_report(store, asset.symbol))
        if fingerprint != guard:
            raise SpineError(
                "DATA_CHANGED",
                f"{row['asset']}: source changed during run preparation.",
                "Run the command again on stable data.",
            )
