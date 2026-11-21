"""The work behind `alpha home backup`, `verify-backup` and `restore` (`home_cmds`).

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
import stat
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, cast

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


def _file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        reader = _Hashing(stream)
        while reader.read(CHUNK):
            pass
    return reader.digest.hexdigest()


def _inside(path: Path, folder: Path) -> bool:
    return path.resolve().is_relative_to(folder.resolve())


def _add_file(tar: tarfile.TarFile, path: Path, name: str) -> dict[str, Any]:
    """Copy one file into the archive, hashing the same bytes; fail if it changed meanwhile."""
    before = path.lstat()
    info = tar.gettarinfo(str(path), f"{PREFIX}/{name}")
    try:
        with path.open("rb") as stream:
            reader = _Hashing(stream)
            tar.addfile(info, reader)
    except OSError as error:
        raise HomeBackupError(
            f"{name} changed while it was read, or is unreadable: {error}"
        ) from error
    after = path.lstat()
    if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
        raise HomeBackupError(
            f"{name} changed while the backup was reading it. Nothing was kept. Stop the "
            "command that writes to the data home, then run the backup again."
        )
    return {"path": name, "size": info.size, "sha256": reader.digest.hexdigest()}


def _fill(tar: tarfile.TarFile, home: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    folders: list[str] = []
    excluded: list[dict[str, str]] = []
    for here, subfolders, names in os.walk(home, followlinks=False):
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


def backup(home: Path, target: Path, now: datetime | None = None) -> dict[str, Any]:
    """Write one archive of `home` into `target` and its SHA-256 beside it."""
    if not home.is_dir():
        raise HomeBackupError(f"There is no data home at {home}. Nothing to back up.")
    if _inside(target, home):
        raise HomeBackupError(
            f"{target} is inside the data home {home}. A backup inside the home would copy "
            "itself and is lost with the home. Choose a folder on another disk."
        )
    lock = home / "nightly" / ".lock"
    lock.parent.mkdir(exist_ok=True)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    archive = target / f"alpha-home-{stamp}.tar"
    partial = archive.with_name(archive.name + ".partial")
    with lock.open("a") as held:
        try:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise HomeBackupError(
                f"A nightly run is in progress (the lock {lock} is held). Nothing was "
                "written. Run the backup again when the nightly run has finished."
            ) from error
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
    sidecar.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
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


def safe_parts(name: str) -> tuple[str, ...]:
    """The path parts under `home/` of one archive entry; anything that could leave is refused."""
    parts = tuple(name.split("/"))
    if parts[0] != PREFIX or len(parts) < 2 or any(part in ("", ".", "..") for part in parts):
        raise HomeBackupError(f"The archive entry {name!r} is unsafe. Nothing more was read.")
    return parts[1:]


def _archive_hash(archive: Path) -> str:
    sidecar = archive.with_name(archive.name + ".sha256")
    if not sidecar.is_file():
        return "not checked: no .sha256 file beside the archive"
    return "matches" if sidecar.read_text().split()[:1] == [_file_hash(archive)] else "differs"


def _read(archive: Path, into: Path | None) -> tuple[dict[str, tuple[int, str]], Any, str | None]:
    """Hash every file entry; write each under `into` if given: (found, manifest, error)."""
    found: dict[str, tuple[int, str]] = {}
    manifest: Any = None
    try:
        with tarfile.open(archive, mode="r|") as tar:
            for member in tar:
                if member.name == MANIFEST:
                    manifest = json.loads(cast(IO[bytes], tar.extractfile(member)).read())
                    continue
                parts = safe_parts(member.name)
                place = into.joinpath(*parts) if into else None
                if member.isdir():
                    if place:
                        place.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise HomeBackupError(
                        f"The archive entry {member.name!r} is unsafe: not a file."
                    )
                reader = _Hashing(cast(IO[bytes], tar.extractfile(member)))
                if place:
                    place.parent.mkdir(parents=True, exist_ok=True)
                    with place.open("xb") as out:
                        while data := reader.read(CHUNK):
                            out.write(data)
                    os.utime(place, (member.mtime, member.mtime))
                else:
                    while reader.read(CHUNK):
                        pass
                found["/".join(parts)] = (member.size, reader.digest.hexdigest())
    except HomeBackupError:
        raise
    except (tarfile.TarError, EOFError, OSError, ValueError) as error:
        last = f" The last whole file read was {list(found)[-1]}." if found else ""
        return found, manifest, f"The archive cannot be read to its end: {error}.{last}"
    return found, manifest, None


def _compare(found: dict[str, tuple[int, str]], manifest: Any) -> tuple[list[str], int]:
    """Every file against the manifest: (problems naming each file, number of bad files)."""
    rows = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(rows, list):
        return [f"The archive has no readable {MANIFEST}: no file can be checked."], 0
    problems: list[str] = []
    listed = {str(row["path"]): (row["size"], row["sha256"]) for row in rows}
    for name, expected in listed.items():
        if name not in found:
            problems.append(f"{name}: listed in the manifest but missing from the archive.")
        elif found[name] != expected:
            problems.append(f"{name}: its content differs from the manifest (size or SHA-256).")
    problems += [
        f"{name}: in the archive but not in the manifest." for name in found.keys() - listed
    ]
    return problems, len(problems)


def verify(archive: Path, into: Path | None = None) -> dict[str, Any]:
    """Read the archive again and check every file against the manifest. Extracts nothing."""
    if not archive.is_file():
        raise HomeBackupError(f"{archive} is not a file.")
    hashed = _archive_hash(archive)
    found, manifest, error = _read(archive, into)
    problems, bad = _compare(found, manifest)
    problems = [
        *(
            ["The archive's own SHA-256 differs from the .sha256 file."]
            if hashed == "differs"
            else []
        ),
        *([error] if error else []),
        *problems,
    ]
    excluded = manifest.get("excluded", []) if isinstance(manifest, dict) else []
    return {
        "archive": str(archive),
        "archive_hash": hashed,
        "ok": not problems,
        "files_checked": len(found),
        "files_ok": len(found) - min(bad, len(found)),
        "files_bad": bad,
        "excluded": len(excluded),
        "problems": problems,
    }


def restore(archive: Path, target: Path, home: Path) -> dict[str, Any]:
    """Check the archive, then write it into a new or empty folder. Never the live home."""
    if _inside(target, home) or _inside(home, target):
        raise HomeBackupError(
            f"{target} is the live data home, inside it, or holds it. Restore writes only to "
            "a new empty folder, so the live home is never overwritten."
        )
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise HomeBackupError(f"{target} is not empty. Restore needs a new or empty folder.")
    checked = verify(archive)
    if not checked["ok"]:
        raise HomeBackupError(
            f"{archive} failed the check, so nothing was restored. First problem: "
            f"{checked['problems'][0]}"
        )
    target.mkdir(parents=True, exist_ok=True)
    written = verify(archive, into=target)
    if not written["ok"]:
        raise HomeBackupError(f"The restore into {target} failed: {written['problems'][0]}")
    return {"archive": str(archive), "target": str(target), "files": written["files_checked"]}
