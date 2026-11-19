"""Append-only, locked and durable record of every rule trial and investigation-tool run."""

from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpha_cli.spine.trial_record import row_test_key
from alpha_core import DataError


def _history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for index, line in enumerate(path.read_bytes().splitlines(keepends=True), 1):
        try:
            row = json.loads(line)
            if not line.endswith(b"\n") or not isinstance(row, dict):
                raise ValueError("incomplete JSON object")
            if (
                row.get("schema") != "AlphaTrialV1"
                or row.get("trial_index") != index
                or row.get("total_trials") != index
            ):
                raise ValueError("schema or trial index mismatch")
        except ValueError as exc:
            raise DataError(f"corrupt trial ledger {path} at line {index}: {exc}") from exc
        # Rows written before investigation tools existed carry no kind: they are rule tests.
        row.setdefault("kind", "rule_test")
        rows.append(row)
    return rows


def first_same_test(rows: list[dict[str, Any]], values: dict[str, Any]) -> dict[str, Any] | None:
    """The earliest row this one repeats: the same run, or (rule tests) the same test key.

    The test key is what was tested, not which code ran it, so a re-run after a code change is a
    repeat. An earlier error row is never matched, by run id or by key: a failed attempt never
    hides the later real one. Rows without a key match only on the same run id.
    """
    key = row_test_key(values)
    for row in rows:
        if "error" in (row.get("labels") or ()):
            continue
        same_run = values.get("run_id") is not None and all(
            row.get(name) == values.get(name) for name in ("run_id", "kind", "tool_output")
        )
        if same_run or (key is not None and row_test_key(row) == key):
            return row
    return None


def append_trial(home: Path, values: dict[str, Any]) -> dict[str, Any]:
    """Allocate the next index and append under the RD-Agent lock-file/fsync discipline."""
    path = home / "ledger" / "trials.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".jsonl.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        rows = _history(path)
        labels = list(values["labels"])
        values = {"kind": "rule_test", **values}
        first = first_same_test(rows, values)
        if first is not None and "repeat" not in labels:
            labels.append("repeat")
        if first is not None and first.get("run_id") is not None:
            values["repeat_of"] = first["run_id"]
        index = len(rows) + 1
        row = {
            **values,
            "schema": "AlphaTrialV1",
            "trial_index": index,
            "total_trials": index,
            "recorded_at": datetime.now(UTC).isoformat(),
            "labels": labels,
        }
        rendered = (
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        ).encode()
        with path.open("ab", buffering=0) as stream:
            if stream.write(rendered) != len(rendered):
                raise DataError(f"short trial ledger write at {path}")
            os.fsync(stream.fileno())
        return row


def read_trials(home: Path) -> list[dict[str, Any]]:
    """Read a consistent ledger snapshot; older rows may lack variant counts or a kind."""
    path = home / "ledger" / "trials.jsonl"
    if not path.exists():
        return []
    with path.with_suffix(".jsonl.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
        return _history(path)
