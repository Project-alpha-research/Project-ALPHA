"""The work behind `alpha home backup` (`home_cmds`). Checking and restoring are in `home_restore`.

A backup is ONE tar file: every file of the home under `home/`, then `manifest.json` (relative
path, size and SHA-256 of every file; every folder; everything left out, with the reason). The
archive's own SHA-256 is written beside it. The backup holds the nightly lock while it reads, never
follows a link, and never writes inside the home. Restore fills a NEW EMPTY folder only.
"""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import shutil
import stat
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, cast

from alpha_cli.home_disk import human
from alpha_core.atomic import write_text

MANIFEST = "manifest.json"
PREFIX = "home"
CHUNK = 1 << 20


class HomeBackupError(ValueError):
    """The backup, check or restore was refused or failed. The message is for the owner."""


class _Hashing:
    """Pass bytes through and hash them: `read` for a file going in, `write` for the archive."""

    def __init__(self, stream: IO[bytes]) -> None:
        self.stream, self.digest = stream, hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self.stream.read(size)
        self.digest.update(data)
        return data

    def write(self, data: bytes) -> int:
        self.digest.update(data)
        return self.stream.write(data)


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        reader = _Hashing(stream)
        while reader.read(CHUNK):
            pass
    return reader.digest.hexdigest()


def inside(path: Path, folder: Path) -> bool:
    return path.resolve().is_relative_to(folder.resolve())


def _add_file(tar: tarfile.TarFile, path: Path, name: str) -> dict[str, Any]:
    """Copy one file into the archive, hashing the same bytes; fail if it changed meanwhile."""
    changed = (
        f"{name} changed while the backup was reading it, or cannot be read. Nothing was kept. "
        "Stop the command that writes to the data home, then run the backup again."
    )
    try:
        before = path.lstat()
        tar.inodes.clear()  # a second name of one file is stored in full, never as an empty link
        info = tar.gettarinfo(str(path), f"{PREFIX}/{name}")
        if not info.isreg():
            raise HomeBackupError(f"{name} is not a plain file any more. {changed}")
        with path.open("rb") as stream:
            reader = _Hashing(stream)
            tar.addfile(info, reader)
        after = path.lstat()
    except OSError as error:
        raise HomeBackupError(f"{changed} ({error})") from error
    if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
        raise HomeBackupError(changed)
    return {"path": name, "size": info.size, "sha256": reader.digest.hexdigest()}


def _unreadable(error: OSError) -> None:
    raise HomeBackupError(f"A folder of the data home cannot be read, so the backup stops: {error}")


def _fill(tar: tarfile.TarFile, home: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    folders: list[str] = []
    excluded: list[dict[str, str]] = []
    for here, subfolders, names in os.walk(home, followlinks=False, onerror=_unreadable):
        subfolders.sort()
        for entry in sorted([*subfolders, *names]):
            path = Path(here) / entry
            name = path.relative_to(home).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                reason = f"symbolic link to {os.readlink(path)}; links are not followed"
                excluded.append({"path": name, "reason": reason})
            elif stat.S_ISDIR(mode):
                folders.append(name)
                tar.addfile(tar.gettarinfo(str(path), f"{PREFIX}/{name}"))
            elif stat.S_ISREG(mode):
                files.append(_add_file(tar, path, name))
            else:
                excluded.append({"path": name, "reason": "not a regular file (pipe or device)"})
    return {
        "schema": 1,
        "home": str(home),
        "files": files,
        "folders": folders,
        "excluded": excluded,
        "total_bytes": sum(row["size"] for row in files),
    }


def _room(home: Path, target: Path) -> None:
    """Refuse plainly when the target disk cannot hold the archive (each entry costs headers)."""
    need, entries = 0, 0
    for here, subfolders, names in os.walk(home, followlinks=False, onerror=_unreadable):
        for entry in [*subfolders, *names]:
            entries += 1
            need += max(os.lstat(os.path.join(here, entry)).st_size, 0)
    need += entries * 2048 + (1 << 20)
    place = next(p for p in (target, *target.resolve().parents) if p.exists())
    free = shutil.disk_usage(place).free
    if free < need:
        raise HomeBackupError(
            f"There is not enough free space for the backup. It needs about {human(need)} and "
            f"{place} has {human(free)} free. Nothing was written. Free space or choose "
            "another disk."
        )


def backup(home: Path, target: Path, now: datetime | None = None) -> dict[str, Any]:
    """Write one archive of `home` into `target` and its SHA-256 beside it."""
    if not home.is_dir():
        raise HomeBackupError(f"There is no data home at {home}. Nothing to back up.")
    if inside(target, home):
        raise HomeBackupError(
            f"{target} is inside the data home {home}. A backup inside the home would copy "
            "itself and is lost with the home. Choose a folder on another disk."
        )
    lock = home / "nightly" / ".lock"
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    archive = target / f"alpha-home-{stamp}.tar"
    partial = archive.with_name(archive.name + ".partial")
    try:
        lock.parent.mkdir(exist_ok=True)
        held = lock.open("a")
    except OSError as error:
        raise HomeBackupError(f"The nightly lock {lock} cannot be opened: {error}") from error
    with held:
        try:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise HomeBackupError(
                f"A nightly run is in progress (the lock {lock} is held). Nothing was "
                "written. Run the backup again when the nightly run has finished."
            ) from error
        _room(home, target)
        target.mkdir(parents=True, exist_ok=True)
        if archive.exists():
            raise HomeBackupError(f"{archive} already exists. Wait one second and run it again.")
        try:
            with partial.open("xb") as raw:
                out = _Hashing(raw)
                sink = cast(IO[bytes], out)
                with tarfile.open(fileobj=sink, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                    manifest = _fill(tar, home)
                    manifest["created_utc"] = stamp
                    body = json.dumps(manifest, indent=1, sort_keys=True).encode()
                    info = tarfile.TarInfo(MANIFEST)
                    info.size = len(body)
                    tar.addfile(info, io.BytesIO(body))
                raw.flush()
                os.fsync(raw.fileno())
            os.replace(partial, archive)
        finally:
            partial.unlink(missing_ok=True)
    digest = out.digest.hexdigest()
    sidecar = archive.with_name(archive.name + ".sha256")
    write_text(sidecar, f"{digest}  {archive.name}\n")
    return {
        "archive": str(archive),
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": digest,
        "sha256_file": str(sidecar),
        "files": len(manifest["files"]),
        "folders": len(manifest["folders"]),
        "total_bytes": manifest["total_bytes"],
        "excluded": manifest["excluded"],
    }
