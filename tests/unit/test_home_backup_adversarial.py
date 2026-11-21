"""Adversarial cases for the home backup: links, modes, space, crafted archives, bad manifests."""

from __future__ import annotations

import io
import json
import os
import shutil
import tarfile
from collections import namedtuple
from pathlib import Path
from typing import Any

import pytest

from alpha_cli import home_restore
from alpha_cli.home_backup import HomeBackupError, backup, file_hash
from alpha_cli.home_restore import restore, verify
from tests.unit.test_home_backup import synthetic_home, tree

Usage = namedtuple("Usage", "total used free")


def test_a_hard_linked_file_is_stored_in_full_under_both_names(tmp_path: Path) -> None:
    home = synthetic_home(tmp_path)
    os.link(home / "ledger" / "trials.jsonl", home / "ledger" / "twin.jsonl")
    made = backup(home, tmp_path / "out")
    archive = Path(made["archive"])
    rows = {r["path"]: r for r in json.loads(_manifest(archive))["files"]}
    for name in ("ledger/trials.jsonl", "ledger/twin.jsonl"):
        assert rows[name]["size"] == len(b'{"trial": 1}\n')
    assert verify(archive)["ok"] is True
    target = tmp_path / "back"
    restore(archive, target, home)
    assert (target / "ledger" / "twin.jsonl").read_bytes() == b'{"trial": 1}\n'
    assert tree(target) == tree(home)


def _manifest(archive: Path) -> bytes:
    with tarfile.open(archive) as tar:
        member = tar.extractfile("manifest.json")
        assert member is not None
        return member.read()


def test_restore_keeps_file_modes_and_times(tmp_path: Path) -> None:
    home = synthetic_home(tmp_path)
    script = home / "notes" / "run.sh"
    script.write_text("echo hi\n")
    script.chmod(0o750)
    os.utime(script, (1_700_000_000, 1_700_000_000))
    archive = Path(backup(home, tmp_path / "out")["archive"])
    target = tmp_path / "back"
    restore(archive, target, home)
    copy = target / "notes" / "run.sh"
    assert copy.stat().st_mode & 0o777 == 0o750
    assert int(copy.stat().st_mtime) == 1_700_000_000


def test_a_target_without_room_is_refused_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = synthetic_home(tmp_path)
    monkeypatch.setattr(shutil, "disk_usage", lambda _: Usage(10**9, 10**9 - 100, 100))
    with pytest.raises(HomeBackupError, match="not enough free space"):
        backup(home, tmp_path / "out")
    assert not (tmp_path / "out").exists() or list((tmp_path / "out").iterdir()) == []


def crafted(path: Path, members: list[tuple[str, bytes, bytes | None]]) -> Path:
    """A tar whose entries are (name, body, link target); a link target makes a symbolic link."""
    with tarfile.open(path, "w") as tar:
        listed = []
        for name, body, link in members:
            info = tarfile.TarInfo(name)
            if link is not None:
                info.type, info.linkname = tarfile.SYMTYPE, link.decode()
                tar.addfile(info)
                continue
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
            listed.append({"path": name.removeprefix("home/"), "size": len(body), "sha256": "0"})
        text = json.dumps({"files": listed}).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(text)
        tar.addfile(info, io.BytesIO(text))
    return path


@pytest.mark.parametrize(
    "members",
    [
        [("home/../evil", b"x", None)],
        [("/abs/evil", b"x", None)],
        [("home/ok", b"x", None), ("home/link", b"", b"/etc")],
        [("home/link", b"", b"../outside"), ("home/link/evil", b"x", None)],
    ],
)
def test_a_crafted_archive_cannot_write_outside_the_new_folder(
    tmp_path: Path, members: list[tuple[str, bytes, bytes | None]]
) -> None:
    home = synthetic_home(tmp_path)
    archive = crafted(tmp_path / "bad.tar", members)
    target = tmp_path / "area" / "new"
    with pytest.raises(HomeBackupError):
        restore(archive, target, home)
    assert not (tmp_path / "area" / "evil").exists() and not (tmp_path / "evil").exists()
    assert not target.exists() or list(target.rglob("*")) == []
    assert not Path("/abs/evil").exists()


def test_a_member_stored_twice_is_a_problem(tmp_path: Path) -> None:
    archive = crafted(tmp_path / "dup.tar", [("home/a", b"one", None), ("home/a", b"two", None)])
    checked = verify(archive)
    assert checked["ok"] is False
    assert any("twice" in line for line in checked["problems"])


@pytest.mark.parametrize("rows", ["[1, 2]", '[{"size": 1}]', '"text"', "[null]"])
def test_a_damaged_manifest_is_reported_not_a_crash(tmp_path: Path, rows: str) -> None:
    path = tmp_path / "m.tar"
    body = ('{"files": ' + rows + "}").encode()
    with tarfile.open(path, "w") as tar:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
    checked = verify(path)
    assert checked["ok"] is False and checked["problems"]


def test_a_folder_missing_from_the_archive_is_a_problem(tmp_path: Path) -> None:
    home = synthetic_home(tmp_path)
    made = Path(backup(home, tmp_path / "out")["archive"])
    cut = tmp_path / "cut.tar"
    with tarfile.open(made) as src, tarfile.open(cut, "w") as dst:
        for member in src:
            if member.name != "home/empty-folder":
                dst.addfile(member, src.extractfile(member) if member.isfile() else None)
    checked = verify(cut)
    assert checked["ok"] is False and any("empty-folder" in p for p in checked["problems"])


def test_restore_checks_the_written_files_again_from_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = synthetic_home(tmp_path)
    archive = Path(backup(home, tmp_path / "out")["archive"])
    real = file_hash
    monkeypatch.setattr(
        home_restore, "file_hash", lambda p: "0" * 64 if "back" in p.parts else real(p)
    )
    with pytest.raises(HomeBackupError, match="written"):
        restore(archive, tmp_path / "back", home)


def test_a_symlink_to_the_home_is_not_a_place_to_restore(tmp_path: Path) -> None:
    home = synthetic_home(tmp_path)
    archive = Path(backup(home, tmp_path / "out")["archive"])
    (tmp_path / "door").symlink_to(home, target_is_directory=True)
    for target in (tmp_path / "door", tmp_path / "door" / "sub"):
        with pytest.raises(HomeBackupError):
            restore(archive, target, home)
    refused: Any = None
    with pytest.raises(HomeBackupError):
        backup(home, tmp_path / "door" / ".." / "home" / "x")
    assert refused is None


def test_a_folder_that_cannot_be_read_stops_the_backup_instead_of_being_skipped(
    tmp_path: Path,
) -> None:
    home = synthetic_home(tmp_path)
    locked = home / "notes"
    locked.chmod(0)
    try:
        with pytest.raises(HomeBackupError, match="cannot be read"):
            backup(home, tmp_path / "out")
    finally:
        locked.chmod(0o755)
    assert not list((tmp_path / "out").glob("*.tar")) if (tmp_path / "out").exists() else True


def test_restore_keeps_folder_modes_even_when_read_only(tmp_path: Path) -> None:
    home = synthetic_home(tmp_path)
    (home / "ledger").chmod(0o555)
    try:
        archive = Path(backup(home, tmp_path / "out")["archive"])
        restore(archive, tmp_path / "back", home)
    finally:
        (home / "ledger").chmod(0o755)
    copy = tmp_path / "back" / "ledger"
    assert copy.stat().st_mode & 0o777 == 0o555
    copy.chmod(0o755)
