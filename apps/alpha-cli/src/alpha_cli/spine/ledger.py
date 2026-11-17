"""Append-only, locked and durable record of every rule trial and investigation-tool run."""

from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def append_trial(home: Path, values: dict[str, Any]) -> dict[str, Any]:
    """Allocate the next index and append under the RD-Agent lock-file/fsync discipline."""
    path = home / "ledger" / "trials.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".jsonl.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        rows = _history(path)
        labels = list(values["labels"])
        # A repeat is the same run recorded again by the same kind of row (and tool output).
        same = ("run_id", "kind", "tool_output")
        values = {"kind": "rule_test", **values}
        if (
            values.get("run_id") is not None
            and any(all(row.get(key) == values.get(key) for key in same) for row in rows)
            and "repeat" not in labels
        ):
            labels.append("repeat")
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
