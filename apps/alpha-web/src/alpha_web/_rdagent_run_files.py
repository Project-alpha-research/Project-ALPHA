"""Bounded, link-refusing reads of recorded RD-Agent files and their closed projection."""

from __future__ import annotations

import json
import math
import os
import stat
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import Any

from alpha_web.api.errors import safe_message
from alpha_web.api.rdagent_models import RecordedFact

MISSING = "not recorded by this run"
RECEIPT_SCHEMA = "AlphaRdagentFactorRunReceiptV1"
FACTOR_SCHEMAS = {f"AlphaRdagentFactorTrialV{version}" for version in (1, 2, 3)}
MAX_FILE_BYTES = 32 * 1024 * 1024


TEXT_CHUNK = 400


def _clean(piece: str) -> str:
    """Slashes joining words (admitted/approved) are prose; paths start a word and are redacted."""
    tokens = [
        token if token.startswith(("/", "~")) or ":" in token else token.replace("/", "\u2215")
        for token in f"x {piece}".split(" ")
    ]
    protected = " ".join(tokens)
    return safe_message(protected, fallback="x ")[2:].replace("\u2215", "/")


def _text(value: str) -> str:
    """Redact secrets and paths without cutting long recorded text or refusing a leading bracket.

    safe_message keeps 500 characters and rejects text that starts with a bracket, so the text is
    prefixed and passed in whole-word pieces; secrets contain no spaces, so no piece splits one.
    """
    words, pieces, current = value.split(), [], ""
    for word in words:
        if current and len(current) + len(word) >= TEXT_CHUNK:
            pieces.append(current)
            current = ""
        current = f"{current} {word}".strip()
    if current:
        pieces.append(current)
    cleaned = [_clean(piece) for piece in pieces]
    return " ".join(cleaned) if cleaned else safe_message("", fallback="Recorded text unavailable.")


def _get(row: dict[str, Any], path: str) -> Any:
    current: Any = row
    for part in path.split("."):
        if not isinstance(current, dict):
            if current is None:
                return None
            raise ValueError("Recorded RD-Agent object has an invalid shape.")
        current = current.get(part)
    return current


def counted(value: int | float, basis: str) -> RecordedFact:
    """A figure obtained by counting recorded rows or subtracting two recorded times."""
    return RecordedFact(value=value, basis=basis)


def fact(value: Any) -> RecordedFact:
    if value is None:
        return RecordedFact(value=None, reason=MISSING)
    if isinstance(value, str):
        return RecordedFact(value=_text(value))
    if isinstance(value, (bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Non-finite RD-Agent figure.")
        return RecordedFact(value=value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return RecordedFact(value=[_text(item) for item in value])
    raise ValueError("Recorded RD-Agent fact has an invalid shape.")


def project(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, RecordedFact]:
    return {field: fact(_get(row, field)) for field in fields}


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Recorded RD-Agent file must contain JSON objects.")
    return value


def _record_path(root: Path, relative: str) -> Path:
    """Only names selected from local records reach here; refuse links at every component."""
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("RD-Agent recorded files must not be symbolic links.")
    return path


def _read(root: Path, relative: str) -> bytes | None:
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or ".." in parts:
        raise ValueError("Invalid relative record name.")
    # Pin the directory descriptors during the read, including across a concurrent replacement.
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        with ExitStack() as directories:
            directory = os.open(root, directory_flags)
            directories.callback(os.close, directory)
            for part in parts[:-1]:
                directory = os.open(part, directory_flags, dir_fd=directory)
                directories.callback(os.close, directory)
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                    raise ValueError("RD-Agent recorded file is not a bounded regular file.")
                content = stream.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(content) > MAX_FILE_BYTES:
        raise ValueError("RD-Agent recorded file exceeds the read limit.")
    return content


def _json(root: Path, relative: str) -> dict[str, Any]:
    content = _read(root, relative)
    return {} if content is None else _object(json.loads(content))


def _lines(root: Path, relative: str) -> tuple[list[dict[str, Any]], str | None]:
    content = _read(root, relative)
    if content is None:
        return [], MISSING
    lines = content.splitlines(keepends=True)
    incomplete = bool(lines and not lines[-1].endswith(b"\n"))
    if incomplete:
        lines = lines[:-1]
    rows = [_object(json.loads(line)) for line in lines]
    return (
        rows,
        "The last record is still being written; refresh to read it." if incomplete else None,
    )


def _stamp(value: Any) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("RD-Agent timestamps must include a timezone.")
    return stamp
