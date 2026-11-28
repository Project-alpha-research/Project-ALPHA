"""The persistent RD-Agent memory store: its manifest, lock, quarantine and loop count."""

from __future__ import annotations

import fcntl
import hashlib
import importlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "AlphaRdagentResearchMemoryV1"
KNOWLEDGE = "costeer/factor-knowledge.pkl"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def _hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@contextmanager
def _lock(root: Path, *, shared: bool = False) -> Iterator[None]:
    path = root / "memory.lock"
    # Inspection must not even create a lock file in an empty directory.
    if shared and not path.exists():
        yield
        return
    with path.open("rb" if shared else "a+b") as stream:
        fcntl.flock(stream, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _write(root: Path, value: dict[str, Any]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".memory-", dir=root)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(_json(value) + "\n")
        os.replace(name, root / "memory.json")
    finally:
        Path(name).unlink(missing_ok=True)


def _fresh(source: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "rdagent_source_sha256": source,
        "scenario": "fin_factor",
        "knowledge_file": KNOWLEDGE,
        "latest_session": None,
        "runs": [],
    }


def _fields(value: Any, fields: Mapping[str, Any]) -> bool:
    return isinstance(value, dict) and all(
        key in value and type(value[key]) in (kind if isinstance(kind, tuple) else (kind,))
        for key, kind in fields.items()
    )


def _read(root: Path) -> dict[str, Any]:
    value = json.loads((root / "memory.json").read_text())
    valid = _fields(
        value,
        {
            "schema": str,
            "rdagent_source_sha256": str,
            "scenario": str,
            "knowledge_file": str,
            "runs": list,
            "latest_session": (dict, type(None)),
        },
    )
    if not valid or (value["schema"], value["scenario"], value["knowledge_file"]) != (
        SCHEMA,
        "fin_factor",
        KNOWLEDGE,
    ):
        raise ValueError("Invalid memory manifest")
    latest = value["latest_session"]
    if latest is not None and (
        not _fields(
            latest,
            {
                "run_id": str,
                "run_dir": str,
                "session_dir": str,
                "completed_loops": int,
                "judge_sha256": str,
                "recorded_at": str,
            },
        )
        or latest["completed_loops"] < 0
    ):
        raise ValueError("Invalid latest session")
    for run in value["runs"]:
        if not _fields(
            run,
            {
                "run_id": str,
                "run_dir": str,
                "started_at": str,
                "ended_at": str,
                "continued_from_run_id": (str, type(None)),
                "loops_before": int,
                "loops_after": int,
                "knowledge_sha256_before": (str, type(None)),
                "knowledge_sha256_after": (str, type(None)),
                "judge_sha256": str,
                "warnings": list,
            },
        ) or any(not _fields(w, {"code": str, "message": str}) for w in run["warnings"]):
            raise ValueError("Invalid memory run")
    return dict(value)


def _warning(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _quarantine(
    root: Path, paths: Sequence[Path], warning: dict[str, str], *, delete: bool = False
) -> None:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parent = root / "quarantine"
    parent.mkdir(exist_ok=True)
    destination = parent / f"{stamp}-{warning['code']}"
    # Preserve earlier quarantines even if two failures occur within the same second.
    if destination.exists():
        destination = Path(tempfile.mkdtemp(prefix=destination.name + "-", dir=parent))
    else:
        destination.mkdir()
    moved = []
    for path in paths:
        if path.exists():
            moved.append(str(path.relative_to(root)))
            if delete:
                path.unlink()
            else:
                shutil.move(str(path), destination / path.name)
    (destination / "reason.json").write_text(
        _json(
            {
                "schema": "AlphaRdagentMemoryQuarantineV1",
                **warning,
                "moved": moved,
            }
        )
        + "\n"
    )


def completed_loops(session_dir: Path) -> int:
    """Loops completed in the whole session lineage: highest recorded loop index plus one.

    A continued session keeps RD-Agent's loop numbering, so its folder holds only the new loops
    (for example ``2`` after two inherited ones); counting folders would undercount and the next
    run's ``loop_n`` would be spent on loops that already finished.
    """
    if not session_dir.is_dir():
        return 0
    indexes = [
        int(folder.name)
        for folder in session_dir.iterdir()
        if folder.is_dir()
        and folder.name.isdecimal()
        and any(p.is_file() for p in folder.glob("*_record"))
    ]
    return max(indexes) + 1 if indexes else 0


def _load_knowledge(path: Path) -> Any:
    # These modules exist only in the verified factor runtime, not the root environment.
    knowledge_module = importlib.import_module(
        "rdagent.components.coder.CoSTEER.knowledge_management"
    )
    serialization = importlib.import_module("rdagent.core.serialization")

    with path.open("rb") as stream:
        knowledge = serialization.load(stream)
    if not isinstance(knowledge, knowledge_module.CoSTEERKnowledgeBaseV2):
        raise TypeError("Unexpected knowledge type")
    return knowledge
