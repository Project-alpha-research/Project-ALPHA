"""The toolbox checks and the reading stored for one rule test, relayed from the CLI.

Everything comes from ``alpha results show --json``; nothing is computed here. The run's reading
(``AlphaReadingV1``) is the CLI's: stored with a new run, derived by the CLI for an old one.
Each stored tool output becomes one row with its stored reading; each
failed attempt in the trial ledger becomes one row with its stored error code. Rows are ordered by
the time the CLI recorded them.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from alpha_core import DataError
from alpha_web._catalog import _run_json


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _labels(value: Any) -> list[str]:
    return [str(label) for label in value] if isinstance(value, list) else []


def _rows(value: Any) -> list[Mapping[str, Any]]:
    return [row for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _stored(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tool": str(row.get("tool")),
        "outcome": "ok",
        "reading": _text(row.get("reading")),
        "error": None,
        "labels": _labels(row.get("labels")),
        "recorded_at": _text(row.get("recorded_at")),
        "status": _text(row.get("status")),
    }


def _counts(value: Any) -> dict[str, Any] | None:
    """The CLI's count line of the stored results, passed on whole or not at all."""
    if not isinstance(value, Mapping):
        return None
    total, declared, exploratory = (value.get(k) for k in ("total", "declared", "exploratory"))
    text = _text(value.get("text"))
    numbers = (total, declared, exploratory)
    if text is None or any(not isinstance(n, int) or isinstance(n, bool) for n in numbers):
        return None
    return {"total": total, "declared": declared, "exploratory": exploratory, "text": text}


def _failed(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "tool": str(row.get("kind", "")).removeprefix("tool:"),
        "outcome": "error",
        "reading": None,
        "error": _text(row.get("error_code")) or "no error code was stored",
        "labels": _labels(row.get("labels")),
        "recorded_at": _text(row.get("recorded_at")),
        "status": None,
    }


def rule_test_checks(run_id: str, *, data_dir: Path) -> dict[str, Any]:
    """Stored checks of one run, oldest first; an empty list when none were run."""
    shown = _run_json(["results", "show", run_id, "--json"], data_dir=data_dir)
    runs = _rows(shown.get("runs")) if isinstance(shown, Mapping) else []
    if len(runs) != 1:
        raise DataError("alpha results show returned no single run")
    run = runs[0]
    checks = [_stored(row) for row in _rows(run.get("tools"))]
    checks += [
        _failed(row) for row in _rows(run.get("tool_history")) if row.get("outcome") == "error"
    ]
    checks.sort(key=lambda check: check["recorded_at"] or "")
    reading = run.get("reading")
    return {
        "run_id": run_id,
        "checks": checks,
        "reading": dict(reading) if isinstance(reading, Mapping) else None,
        "counts": _counts(run.get("tool_counts")),
    }
