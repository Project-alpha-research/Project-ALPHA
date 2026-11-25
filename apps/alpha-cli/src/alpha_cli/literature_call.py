"""Literature worker call and owner-PDF read and extraction checks; imports no command module."""

from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import shutil
import stat
import tempfile
from contextlib import ExitStack
from pathlib import Path

from alpha_cli._cli_json import json_object_option as _object
from alpha_cli.control_store import _MAX_OWNER_PDF_BYTES
from alpha_core import DataError

_MAX_PDF_BYTES = _MAX_OWNER_PDF_BYTES
_MAX_PDF_PAGES = 200
_MAX_PDF_CHARACTERS = 2_000_000
_SHA256 = re.compile(r"[0-9a-f]{64}")
_EXTRACTION_ID = re.compile(r"rx_[0-9a-f]{64}")


def _apply_literature_worker_limits() -> None:
    """Bound the isolated parser/fetch child before it executes any worker code."""
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def _run_literature_worker(argv: list[str], *, timeout_seconds: int = 180) -> dict[str, object]:
    """Run the isolated worker with no inherited credential or shell environment."""
    import subprocess

    worker_dir = Path(__file__).resolve().parents[4] / "workers" / "literature"
    if not (worker_dir / "pyproject.toml").is_file():
        raise DataError("literature worker is unavailable outside a checked-out repository")
    worker_source = worker_dir / "src" / "literature_worker" / "__main__.py"
    if not worker_source.is_file():
        raise DataError("literature worker source is unavailable in the checkout")
    uv_executable = shutil.which("uv")
    if uv_executable is None or not Path(uv_executable).is_absolute():
        raise DataError("the pinned literature worker runtime is unavailable")
    child_env = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.defpath,
        "PYTHONPATH": str(worker_dir / "src"),
        "UV_NO_CONFIG": "1",
        "UV_OFFLINE": "1",
    }
    with ExitStack() as cleanup:
        configured_cache = os.environ.get("UV_CACHE_DIR")
        if configured_cache is None:
            cache_dir = cleanup.enter_context(
                tempfile.TemporaryDirectory(prefix="alpha-literature-uv-cache-")
            )
        else:
            cache_path = Path(configured_cache)
            if (
                not configured_cache
                or "\x00" in configured_cache
                or not cache_path.is_dir()
                or not os.access(cache_path, os.W_OK | os.X_OK)
            ):
                raise DataError("configured UV_CACHE_DIR must be an existing writable directory")
            cache_dir = configured_cache
        child_env["UV_CACHE_DIR"] = str(cache_dir)
        completed = subprocess.run(
            [
                uv_executable,
                "run",
                "--locked",
                "--no-sync",
                "--project",
                str(worker_dir),
                "python",
                "-P",
                "-m",
                "literature_worker",
                *argv,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            env=child_env,
            start_new_session=True,
            preexec_fn=_apply_literature_worker_limits,
        )
    if completed.returncode != 0:
        raise DataError(
            completed.stderr.strip() or completed.stdout.strip() or "literature worker failed"
        )
    return _object(completed.stdout, "literature worker output")


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        stat.S_IFMT(value.st_mode),
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_open_pdf(fd: int, path: Path, before: os.stat_result) -> tuple[bytes, str]:
    if not stat.S_ISREG(before.st_mode):
        raise DataError("owner-provided PDF must be a regular file")
    if before.st_size < 5:
        raise DataError("owner-provided file is not a PDF")
    if before.st_size > _MAX_PDF_BYTES:
        raise DataError("owner-provided PDF exceeds the 10 MiB byte limit")

    contents = bytearray()
    while len(contents) <= _MAX_PDF_BYTES:
        count = min(64 * 1024, _MAX_PDF_BYTES + 1 - len(contents))
        chunk = os.read(fd, count)
        if not chunk:
            break
        contents.extend(chunk)
    if len(contents) > _MAX_PDF_BYTES:
        raise DataError("owner-provided PDF exceeds the 10 MiB byte limit")

    after = os.fstat(fd)
    try:
        path_after = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise DataError("owner-provided PDF path changed during import") from exc
    if (
        len(contents) != before.st_size
        or _stat_identity(after) != _stat_identity(before)
        or _stat_identity(path_after) != _stat_identity(before)
    ):
        raise DataError("owner-provided PDF changed during import")

    raw = bytes(contents)
    if not raw.startswith(b"%PDF-"):
        raise DataError("owner-provided file is not a PDF")
    return raw, hashlib.sha256(raw).hexdigest()


def _read_owner_pdf(path: Path) -> tuple[bytes, str]:
    """Read only the selected file, rejecting final symlinks and concurrent replacement."""
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise DataError("this platform cannot safely reject a symlinked owner PDF")
    selected = path.expanduser()
    # O_NONBLOCK: a FIFO or device must not block the open before the fstat regular-file check
    # rejects it; it has no effect on reading a regular file.
    flags = os.O_RDONLY | no_follow | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(selected, flags)
    except OSError as exc:
        raise DataError("owner-provided PDF must be an existing non-symlink file") from exc
    try:
        try:
            before = os.fstat(descriptor)
            return _read_open_pdf(descriptor, selected, before)
        except OSError as exc:
            raise DataError("owner-provided PDF could not be read safely") from exc
    finally:
        os.close(descriptor)


def _validated_extraction(artifact: dict[str, object], *, source_sha256: str) -> dict[str, object]:
    if artifact.get("schema") != "ResearchDocumentTextV1":
        raise DataError("literature worker returned an unsupported PDF extraction")
    if artifact.get("source_sha256") != source_sha256:
        raise DataError("literature worker extraction hash does not match the owner PDF")
    if artifact.get("status") != "extracted":
        status = artifact.get("status")
        raise DataError(f"owner PDF extraction is incomplete ({status}); source was not imported")
    if artifact.get("trust_label") != "UNTRUSTED_SOURCE":
        raise DataError("literature worker extraction is missing its untrusted-source label")

    extraction_id = artifact.get("extraction_id")
    config_hash = artifact.get("config_hash")
    parser_version = artifact.get("parser_version")
    pages = artifact.get("pages")
    warnings = artifact.get("warnings")
    page_count = artifact.get("page_count")
    character_count = artifact.get("character_count")
    if (
        not isinstance(extraction_id, str)
        or _EXTRACTION_ID.fullmatch(extraction_id) is None
        or not isinstance(config_hash, str)
        or _SHA256.fullmatch(config_hash) is None
        or not isinstance(parser_version, str)
        or not parser_version
        or not isinstance(pages, list)
        or isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or not 1 <= page_count <= _MAX_PDF_PAGES
        or len(pages) != page_count
        or isinstance(character_count, bool)
        or not isinstance(character_count, int)
        or not 0 <= character_count <= _MAX_PDF_CHARACTERS
        or warnings != []
    ):
        raise DataError("literature worker extraction metadata is incomplete or inconsistent")

    observed_characters = 0
    has_text = False
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            raise DataError("literature worker extraction contains an invalid page")
        text = page.get("text")
        page_characters = page.get("character_count")
        page_sha256 = page.get("text_sha256")
        page_number = page.get("page")
        if (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or page_number != index
            or not isinstance(text, str)
            or isinstance(page_characters, bool)
            or not isinstance(page_characters, int)
            or page_characters != len(text)
            or not isinstance(page_sha256, str)
            or page_sha256 != hashlib.sha256(text.encode()).hexdigest()
        ):
            raise DataError("literature worker extraction contains inconsistent page text")
        observed_characters += len(text)
        has_text = has_text or bool(text)
    if observed_characters != character_count or not has_text:
        raise DataError("literature worker extraction does not contain complete readable text")
    artifact_core = {
        key: value
        for key, value in artifact.items()
        if key not in {"extraction_id", "artifact_sha256"}
    }
    expected_id = (
        "rx_"
        + hashlib.sha256(
            json.dumps(
                artifact_core,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
    )
    if extraction_id != expected_id:
        raise DataError("literature worker extraction identity does not match its contents")
    return artifact
