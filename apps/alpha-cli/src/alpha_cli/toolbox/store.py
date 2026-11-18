"""Durable attempt history and immutable, versioned diagnostic outputs."""

from __future__ import annotations

import fcntl
import hashlib
import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpha_cli._identity import _digest_sources, _source_files
from alpha_cli.ml_contract import canonical_json_bytes
from alpha_cli.spine.ledger import read_trials
from alpha_cli.toolbox.contract import Result, ToolSpec
from alpha_cli.toolbox.inputs import Target
from alpha_cli.toolbox.registry import ALIASES
from alpha_cli.toolbox.reserve import RESERVED_START
from alpha_core import atomic


@contextmanager
def target_lock(home: Path, target: str) -> Iterator[None]:
    folder = home / "ledger" / "tool-locks"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / hashlib.sha256(target.encode()).hexdigest()).open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def history(home: Path, target: str) -> list[dict[str, Any]]:
    return [
        row
        for row in read_trials(home)
        if row.get("run_id") == target and row["kind"].startswith("tool:")
    ]


def settings_tried(rows: list[dict[str, Any]], tool: str) -> list[dict[str, Any]]:
    settings = []
    for row in rows:
        name = row["kind"].removeprefix("tool:")
        if (
            ALIASES.get(name, name) == tool
            and (params := row.get("settings", row.get("params"))) is not None
            and params not in settings
        ):
            settings.append(params)
    return settings


def output_path(target: str, spec: ToolSpec, key: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json_bytes(key)).hexdigest()[:8]
    return f"diagnostics/{target}/{spec.id}@v{spec.version}-{digest}.json"


def cached(
    home: Path, file: str, key: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    for row in reversed(rows):
        if row.get("tool_output") == file and row.get("outcome") == "ok":
            document = json.loads((home / file).read_bytes())
            if document["cache_key"] != key:
                raise ValueError(f"tool output identity mismatch at {file}")
            return {**document, "file": file, "trials_total": row["total_trials"]}
    return None


def publish(
    home: Path,
    target: Target,
    file: str,
    spec: ToolSpec,
    result: Result,
    key: dict[str, Any],
    labels: list[str],
    settings: list[dict[str, Any]],
    elapsed: float,
) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        check=False,
    )
    document = {
        "tool": spec.id,
        "version": spec.version,
        "params": result.params or key["params"],
        "cache_key": key,
        "settings_tried": settings,
        "git_commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "git_commit_reason": commit.stderr.strip() if commit.returncode else None,
        "validation_sha256": _digest_sources(
            _source_files("alpha_validation"), domain="toolbox-validation-v1"
        ),
        "reserve_start": RESERVED_START,
        "elapsed_seconds": elapsed,
        "run_id": target.run_id,
        "test_id": target.manifest["spine"].get("test_id"),
        "recorded_at": datetime.now(UTC).isoformat(),
        "labels": labels,
        "basis": result.basis,
        "values": result.values,
        "reasons": result.reasons,
        "figure": result.figure,
        "reading": spec.render(result.values),
        "caveats": list(spec.caveats),
        "result": {
            **result.details,
            **({"series": result.series} if result.series is not None else {}),
        },
        "facts": [
            {
                "metric": f"{spec.id}.{output.key}",
                "value": result.values[output.key],
                "run_id": target.run_id,
                "basis": result.basis,
                "source": f"{file}:{output.source or ('values.' + output.key)}",
                "labels": labels,
                "reason": result.reasons.get(output.key),
            }
            for output in spec.outputs
        ],
    }
    atomic.write_text(home / file, json.dumps(document, sort_keys=True, indent=2, allow_nan=False))
    return document
