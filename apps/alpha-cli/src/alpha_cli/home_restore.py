"""The work behind `alpha home verify-backup` and `restore` (`home_cmds`).

Verify reads the whole archive and checks every entry against the manifest inside it, and the
archive against its `.sha256` file; it writes nothing. Restore fills a NEW EMPTY folder only,
refuses any entry that could leave it, and checks the written files again from disk.
"""

from __future__ import annotations

import json
import os
import stat
import tarfile
from pathlib import Path
from typing import IO, Any, cast

from alpha_cli.home_backup import (
    CHUNK,
    MANIFEST,
    PREFIX,
    HomeBackupError,
    _Hashing,
    file_hash,
    inside,
)

Found = dict[str, tuple[int, str]]


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
    return "matches" if sidecar.read_text().split()[:1] == [file_hash(archive)] else "differs"


def _write(place: Path, reader: _Hashing, member: tarfile.TarInfo) -> None:
    place.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(place, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out:
        while data := reader.read(CHUNK):
            out.write(data)
    os.chmod(place, member.mode & 0o777)
    os.utime(place, (member.mtime, member.mtime))


def _read(
    archive: Path, into: Path | None
) -> tuple[Found, list[str], Any, list[str], list[tuple[Path, tarfile.TarInfo]]]:
    """Hash every entry; write each under `into` if given. Returns what was found, the folders,
    the manifest, the problems met (a double entry, a read error) and the folders written."""
    found: Found = {}
    folders: list[str] = []
    problems: list[str] = []
    written: list[tuple[Path, tarfile.TarInfo]] = []
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
                    folders.append("/".join(parts))
                    if place:
                        place.mkdir(parents=True, exist_ok=True)
                        written.append((place, member))
                    continue
                if not member.isfile():
                    raise HomeBackupError(
                        f"The archive entry {member.name!r} is unsafe: not a file."
                    )
                if "/".join(parts) in found:
                    problems.append(f"{'/'.join(parts)}: stored twice in the archive.")
                    continue
                reader = _Hashing(cast(IO[bytes], tar.extractfile(member)))
                if place:
                    _write(place, reader, member)
                else:
                    while reader.read(CHUNK):
                        pass
                found["/".join(parts)] = (member.size, reader.digest.hexdigest())
    except HomeBackupError:
        raise
    except (tarfile.TarError, EOFError, OSError, ValueError) as error:
        last = f" The last whole file read was {list(found)[-1]}." if found else ""
        problems.append(f"The archive cannot be read to its end: {error}.{last}")
    return found, folders, manifest, problems, written


def _listed(manifest: Any) -> tuple[dict[str, tuple[int, str]], list[str], list[str]]:
    """The manifest's files and folders, and a problem for every row that cannot be read."""
    problems: list[str] = []
    rows = manifest.get("files") if isinstance(manifest, dict) else None
    folders = manifest.get("folders") if isinstance(manifest, dict) else None
    if not isinstance(rows, list) or not isinstance(folders, list):
        return {}, [], [f"The archive has no readable {MANIFEST}: no file can be checked."]
    listed: dict[str, tuple[int, str]] = {}
    for number, row in enumerate(rows, 1):
        ok = isinstance(row, dict) and isinstance(row.get("path"), str)
        ok = ok and type(row.get("size")) is int and isinstance(row.get("sha256"), str)
        if ok:
            listed[row["path"]] = (row["size"], row["sha256"])
        else:
            problems.append(f"Manifest file row {number} cannot be read: {row!r}.")
    return listed, [str(name) for name in folders], problems


def _compare(found: Found, seen_folders: list[str], manifest: Any) -> tuple[list[str], int]:
    """Every file and folder against the manifest: (problems naming each, bad file count)."""
    listed, folders, problems = _listed(manifest)
    bad = 0
    for name, expected in listed.items():
        if name not in found:
            problems.append(f"{name}: listed in the manifest but missing from the archive.")
        elif found[name] != expected:
            problems.append(f"{name}: its content differs from the manifest (size or SHA-256).")
        else:
            continue
        bad += 1
    extra = found.keys() - listed.keys()
    problems += [f"{name}: in the archive but not in the manifest." for name in sorted(extra)]
    for name in sorted(set(folders) - set(seen_folders)):
        problems.append(f"{name}: a folder listed in the manifest but missing from the archive.")
    for name in sorted(set(seen_folders) - set(folders)):
        problems.append(f"{name}: a folder in the archive but not in the manifest.")
    return problems, bad + len(extra)


def verify(archive: Path, into: Path | None = None) -> dict[str, Any]:
    """Read the archive again and check every file against the manifest. Extracts nothing."""
    if not archive.is_file():
        raise HomeBackupError(f"{archive} is not a file.")
    hashed = _archive_hash(archive)
    found, seen, manifest, problems, _ = _read(archive, into)
    differences, bad = _compare(found, seen, manifest)
    problems = [
        *(
            ["The archive's own SHA-256 differs from the .sha256 file."]
            if hashed == "differs"
            else []
        ),
        *problems,
        *differences,
    ]
    excluded = manifest.get("excluded", []) if isinstance(manifest, dict) else []
    return {
        "archive": str(archive),
        "archive_hash": hashed,
        "ok": not problems,
        "files_checked": len(found),
        "files_ok": max(len(found) - bad, 0),
        "files_bad": bad,
        "excluded": len(excluded) if isinstance(excluded, list) else 0,
        "problems": problems,
    }


def _check_disk(target: Path, manifest: Any) -> list[str]:
    """Read every restored file from disk again and compare it with the manifest."""
    listed, folders, problems = _listed(manifest)
    on_disk: set[str] = set()
    for here, subfolders, names in os.walk(target, followlinks=False):
        for entry in [*subfolders, *names]:
            on_disk.add((Path(here) / entry).relative_to(target).as_posix())
    for name, (size, digest) in listed.items():
        path = target / name
        if not path.is_file() or path.stat().st_size != size or file_hash(path) != digest:
            problems.append(f"{name}: the written file differs from the manifest.")
    for name in sorted(on_disk - listed.keys() - set(folders)):
        problems.append(f"{name}: written but not in the manifest.")
    return problems


def _finish_folders(written: list[tuple[Path, tarfile.TarInfo]]) -> None:
    """Folder modes and times last and deepest first: a read-only folder blocks its own files."""
    for place, member in sorted(written, key=lambda row: len(row[0].parts), reverse=True):
        os.chmod(place, stat.S_IMODE(member.mode) & 0o777)
        os.utime(place, (member.mtime, member.mtime))


def restore(archive: Path, target: Path, home: Path) -> dict[str, Any]:
    """Check the archive, then write it into a new or empty folder. Never the live home."""
    if inside(target, home) or inside(home, target):
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
    # Owner only, and it stays so: the archive does not record the mode of the home folder itself.
    os.chmod(target, 0o700)
    found, seen, manifest, problems, folders = _read(archive, target)
    problems += _compare(found, seen, manifest)[0]
    problems = problems or _check_disk(target, manifest)
    if problems:
        raise HomeBackupError(
            f"The restore into {target} failed: {problems[0]} The folder is incomplete. Delete "
            "it and start again; the live data home was not touched."
        )
    _finish_folders(folders)
    return {
        "archive": str(archive),
        "target": str(target),
        "files": len(found),
        "left_out": checked["excluded"],
    }
