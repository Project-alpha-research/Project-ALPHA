"""A quick screen counts its tries in the one trial ledger.

Each hypothesis (one signal at one horizon) the screen evaluates becomes one ledger row per
asset, through the existing ``append_trial`` writer. The row carries no Sharpe: a screen scores
no return stream, so nothing here is a fake or zero value. The same-asset count reads the row by
its kind. A re-run of the same screen on the same data has the same test key and counts once.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from alpha_cli.spine.ledger import append_trial, read_trials
from alpha_cli.spine.trial_record import row_test_key

KIND = "screen_trial"


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _data_fingerprint(spec: Mapping[str, Any]) -> str:
    """The rows before the reserved day, and the frozen membership; never a held-back row."""
    return _digest({"rows": spec["data_hash"], "members": spec.get("membership_hash")})


def screen_trial_rows(spec: Mapping[str, Any], result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One ledger row per evaluated hypothesis and asset, built from the frozen spec and result."""
    options = spec["options"]
    fingerprint = _data_fingerprint(spec)
    dates = result["dates"]
    rows: list[dict[str, Any]] = []
    for item in result["results"]:
        hypothesis = {
            "lane": options["lane"],
            "signal": item["signal"],
            "horizon": item["horizon"],
            "min_names": options["min_names"],
            "quantiles": options["quantiles"],
            "cost_bps": options["cost_bps"],
            "category": options["category"] if options["lane"] == "crypto" else None,
            "panel_version": spec["panel_version"],
        }
        for symbol in result["symbols"]:
            rows.append(
                {
                    "kind": KIND,
                    "name": f"{item['signal']}/h{item['horizon']}",
                    "spec_sha256": _digest(hypothesis),
                    "symbol": symbol,
                    "first_ts": dates[0],
                    "last_ts": dates[-1],
                    "bar_size": "1D",
                    "store": options["snapshot"] or "crypto-bulk",
                    "idea_id": fingerprint,
                    "scan_id": result.get("scan_id"),
                    "labels": [],
                }
            )
    return rows


def record_screen_trials(
    data_dir: Path, spec: Mapping[str, Any], result: Mapping[str, Any]
) -> dict[str, Any]:
    """Append the screen's tries; return how many were new to the count, in plain words."""
    appended = [append_trial(data_dir, row) for row in screen_trial_rows(spec, result)]
    added = sum("repeat" not in row["labels"] for row in appended)
    return counted_note(added, hypotheses=len(result["results"]), assets=len(result["symbols"]))


def counted_note(added: int, *, hypotheses: int, assets: int) -> dict[str, Any]:
    if added:
        sentence = (
            f"This screen added {added} tries to the count "
            f"({hypotheses} ideas on {assets} assets). "
            "A later `alpha test` on one of these assets counts them. "
            "A screen is a first look, not a test."
        )
    elif hypotheses:
        sentence = (
            "This screen added 0 tries to the count: the same screen on the same data "
            "was counted before. A screen is a first look, not a test."
        )
    else:
        sentence = "This screen added 0 tries to the count."
    return {"tries_added": added, "hypotheses": hypotheses, "assets": assets, "sentence": sentence}


def record_uncounted_trials(
    data_dir: Path, spec: Mapping[str, Any], result: Mapping[str, Any]
) -> dict[str, Any]:
    """A replay appends only the tries not yet in the ledger, so it adds none to a counted screen.

    A stored screen whose tries were never counted (run before screens counted) is counted here,
    once; a replay is never a way to see a screen's results without its tries counted.
    """
    counted = {row_test_key(row) for row in read_trials(data_dir) if row.get("kind") == KIND}
    missing = [row for row in screen_trial_rows(spec, result) if row_test_key(row) not in counted]
    for row in missing:
        append_trial(data_dir, row)
    note = counted_note(
        len(missing), hypotheses=len(result["results"]), assets=len(result["symbols"])
    )
    if not missing:
        note["sentence"] = (
            "This replay added 0 tries to the count: the first run counted them. "
            "A screen is a first look, not a test."
        )
    return note
