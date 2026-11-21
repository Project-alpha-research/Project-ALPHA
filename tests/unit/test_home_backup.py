"""`alpha home backup`, `verify-backup` and `restore`: one archive, checked, never over the home."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tarfile
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli.home_backup import HomeBackupError, backup
from alpha_cli.home_restore import restore, safe_parts, verify
from alpha_cli.main import app

RUNNER = CliRunner()
NEEDLE = b"NEEDLE-" * 40


def synthetic_home(root: Path) -> Path:
    home = root / "home"
    (home / "data" / "1d").mkdir(parents=True)
    (home / "data" / "1d" / "SPY.parquet").write_bytes(bytes(range(256)) * 1200)
    (home / "ledger").mkdir()
    (home / "ledger" / "trials.jsonl").write_text('{"trial": 1}\n', encoding="utf-8")
    (home / "nightly" / "2026-11-20-1").mkdir(parents=True)
    (home / "nightly" / "2026-11-20-1" / "record.json").write_bytes(NEEDLE)
    (home / "notes").mkdir()
    (home / "notes" / "idée ü.txt").write_text("plain words\n", encoding="utf-8")
    (home / "empty.bin").write_bytes(b"")
    (home / "empty-folder").mkdir()
    return home


def tree(root: Path) -> dict[str, bytes | None]:
    """Every path under `root`: file bytes, or None for a folder."""
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
        if p.name != ".lock"
    }


def test_round_trip_is_byte_identical(tmp_path: Path) -> None:
    home = synthetic_home(tmp_path)
    before = tree(home)
    made = backup(home, tmp_path / "backups")
    archive = Path(made["archive"])
    assert archive.parent == tmp_path / "backups" and archive.suffix == ".tar"
    assert {p.name for p in archive.parent.iterdir()} == {archive.name, archive.name + ".sha256"}
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert made["archive_sha256"] == digest
    assert Path(made["sha256_file"]).read_text() == f"{digest}  {archive.name}\n"
    assert made["files"] == sum(1 for v in before.values() if v is not None) + 1  # + the lock file
    checked = verify(archive)
    assert checked["ok"] is True and checked["problems"] == []
    assert checked["files_checked"] == made["files"] and checked["files_ok"] == made["files"]
    assert checked["archive_hash"] == "matches"
    target = tmp_path / "restored"
    done = restore(archive, target, home)
    assert done["files"] == made["files"]
    assert tree(target) == before
    assert tree(home) == before  # the live home is untouched


def test_the_manifest_lists_every_file_with_size_and_hash(tmp_path: Path) -> None:
    home = synthetic_home(tmp_path)
    archive = Path(backup(home, tmp_path / "out")["archive"])
    with tarfile.open(archive) as tar:
        names = tar.getnames()
        member = tar.extractfile("manifest.json")
        assert member is not None
        manifest = json.loads(member.read())
    assert names[-1] == "manifest.json"
    listed = {row["path"]: row for row in manifest["files"]}
    row = listed["nightly/2026-11-20-1/record.json"]
    assert row == {
        "path": "nightly/2026-11-20-1/record.json",
        "size": len(NEEDLE),
        "sha256": hashlib.sha256(NEEDLE).hexdigest(),
    }
    assert "empty-folder" in manifest["folders"] and manifest["excluded"] == []
    assert {f"home/{path}" for path in listed} <= set(names)


def test_a_link_out_of_the_home_is_never_followed_and_is_listed(tmp_path: Path) -> None:
    home = synthetic_home(tmp_path)
    secret = tmp_path / "outside-secret.txt"
    secret.write_bytes(b"OUTSIDE-CONTENT-MUST-NOT-BE-COPIED")
    (home / "link-out").symlink_to(secret)
    (home / "folder-link").symlink_to(tmp_path)
    made = backup(home, tmp_path / "out")
    archive = Path(made["archive"])
    assert b"OUTSIDE-CONTENT" not in archive.read_bytes()
    paths = {row["path"]: row["reason"] for row in made["excluded"]}
    assert set(paths) == {"link-out", "folder-link"}
    assert "symbolic link" in paths["link-out"] and "not followed" in paths["link-out"]
    assert verify(archive)["excluded"] == 2
    restore(archive, tmp_path / "new", home)
    assert not (tmp_path / "new" / "link-out").exists()


def test_backup_refuses_to_write_inside_the_home(tmp_path: Path) -> None:
    home = synthetic_home(tmp_path)
    before = tree(home)
    for inside in (home, home / "backups", home / "data" / ".." / "deep" / "x"):
        with pytest.raises(HomeBackupError, match="inside the data home"):
            backup(home, inside)
    assert tree(home) == before
    with pytest.raises(HomeBackupError, match="no data home"):
        backup(tmp_path / "absent", tmp_path / "out")


def test_backup_refuses_while_the_nightly_lock_is_held(tmp_path: Path) -> None:
    home = synthetic_home(tmp_path)
    lock = home / "nightly" / ".lock"
    with lock.open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(HomeBackupError, match="nightly run is in progress"):
            backup(home, tmp_path / "out")
        assert not (tmp_path / "out").exists() or list((tmp_path / "out").iterdir()) == []
    assert Path(backup(home, tmp_path / "out")["archive"]).is_file()  # free again: it works


def test_backup_holds_the_nightly_lock_while_it_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = synthetic_home(tmp_path)
    seen: list[bool] = []
    real = tarfile.TarFile.addfile

    def watching(self: tarfile.TarFile, info: tarfile.TarInfo, fileobj: Any = None) -> None:
        with (home / "nightly" / ".lock").open("a") as other:
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                seen.append(False)
            except BlockingIOError:
                seen.append(True)
        real(self, info, fileobj)

    monkeypatch.setattr(tarfile.TarFile, "addfile", watching)
    backup(home, tmp_path / "out")
    assert seen and all(seen)


def test_a_file_that_changes_during_the_backup_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = synthetic_home(tmp_path)
    real = tarfile.TarFile.addfile

    def writer(self: tarfile.TarFile, info: tarfile.TarInfo, fileobj: Any = None) -> None:
        real(self, info, fileobj)
        if info.name == "home/ledger/trials.jsonl":
            with (home / "ledger" / "trials.jsonl").open("a") as handle:
                handle.write('{"trial": 2}\n')

    monkeypatch.setattr(tarfile.TarFile, "addfile", writer)
    with pytest.raises(HomeBackupError, match=r"ledger/trials\.jsonl changed while"):
        backup(home, tmp_path / "out")
    assert list((tmp_path / "out").iterdir()) == []  # no half archive stays behind


def corrupt(archive: Path) -> None:
    raw = bytearray(archive.read_bytes())
    at = raw.index(NEEDLE) + 10
    raw[at] ^= 0xFF
    archive.write_bytes(bytes(raw))


def test_a_corrupted_archive_fails_verification_and_names_the_file(tmp_path: Path) -> None:
    home = synthetic_home(tmp_path)
    archive = Path(backup(home, tmp_path / "out")["archive"])
    corrupt(archive)
    checked = verify(archive)
    assert checked["ok"] is False and checked["files_bad"] == 1
    assert checked["archive_hash"] == "differs"
    assert any("nightly/2026-11-20-1/record.json" in line for line in checked["problems"])
    with pytest.raises(HomeBackupError, match="failed the check"):
        restore(archive, tmp_path / "new", home)
    assert not (tmp_path / "new").exists()
    result = RUNNER.invoke(app, ["home", "verify-backup", str(archive)])
    assert result.exit_code == 1
    assert "BACKUP CHECK FAILED" in result.output
    assert "nightly/2026-11-20-1/record.json" in result.output


def test_a_cut_off_archive_and_a_missing_hash_file_are_reported(tmp_path: Path) -> None:
    home = synthetic_home(tmp_path)
    archive = Path(backup(home, tmp_path / "out")["archive"])
    Path(str(archive) + ".sha256").unlink()
    assert verify(archive)["archive_hash"] == "not checked: no .sha256 file beside the archive"
    assert verify(archive)["ok"] is True
    archive.write_bytes(archive.read_bytes()[:4000])
    cut = verify(archive)
    assert cut["ok"] is False and cut["problems"]
    with pytest.raises(HomeBackupError, match="not a file"):
        verify(tmp_path / "absent.tar")


def test_restore_only_fills_a_new_empty_folder(tmp_path: Path) -> None:
    home = synthetic_home(tmp_path)
    before = tree(home)
    archive = Path(backup(home, tmp_path / "out")["archive"])
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "keep.txt").write_text("mine")
    with pytest.raises(HomeBackupError, match="not empty"):
        restore(archive, busy, home)
    assert [p.name for p in busy.iterdir()] == ["keep.txt"]
    for live in (home, home / "sub", tmp_path):
        with pytest.raises(HomeBackupError):
            restore(archive, live, home)
    assert tree(home) == before
    empty = tmp_path / "empty-target"
    empty.mkdir()
    assert restore(archive, empty, home)["files"] > 0


def test_restore_refuses_an_archive_entry_that_would_leave_the_folder() -> None:
    assert safe_parts("home/data/1d/SPY.parquet") == ("data", "1d", "SPY.parquet")
    for name in ("home/../evil", "/etc/passwd", "other/file", "home/a/../../b"):
        with pytest.raises(HomeBackupError, match="unsafe"):
            safe_parts(name)


def test_the_commands_print_plain_words_and_json(tmp_path: Path) -> None:
    home = synthetic_home(tmp_path)
    env = {"ALPHA_DATA_DIR": str(home)}
    made = RUNNER.invoke(app, ["home", "backup", str(tmp_path / "out")], env=env)
    assert made.exit_code == 0, made.output
    assert "Backup written: " in made.output and " kB" in made.output
    assert "Nothing was left out." in made.output
    as_json = RUNNER.invoke(app, ["home", "backup", str(tmp_path / "out2"), "--json"], env=env)
    archive = json.loads(as_json.output)["archive"]
    checked = RUNNER.invoke(app, ["home", "verify-backup", archive, "--json"], env=env)
    assert checked.exit_code == 0 and json.loads(checked.output)["ok"] is True
    words = RUNNER.invoke(app, ["home", "verify-backup", archive], env=env)
    assert "Backup check passed" in words.output and "files checked" in words.output
    refused = RUNNER.invoke(app, ["home", "backup", str(home / "inside")], env=env)
    assert refused.exit_code == 2 and "inside the data home" in refused.output
    target = tmp_path / "restored"
    done = RUNNER.invoke(app, ["home", "restore", archive, str(target)], env=env)
    assert done.exit_code == 0 and "Restored " in done.output
    assert "ALPHA_DATA_DIR" in done.output  # it says how to look at the copy, and changes nothing
    again = RUNNER.invoke(app, ["home", "restore", archive, str(target)], env=env)
    assert again.exit_code == 2 and "not empty" in again.output


def test_the_archive_is_readable_by_the_owner_only_from_the_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = synthetic_home(tmp_path)
    modes: list[int] = []
    real = tarfile.TarFile.addfile

    def watching(self: tarfile.TarFile, info: tarfile.TarInfo, fileobj: Any = None) -> None:
        modes.extend(p.stat().st_mode & 0o777 for p in (tmp_path / "out").iterdir())
        real(self, info, fileobj)

    monkeypatch.setattr(tarfile.TarFile, "addfile", watching)
    old = os.umask(0o022)
    try:
        archive = Path(backup(home, tmp_path / "out")["archive"])
    finally:
        os.umask(old)
    assert modes and set(modes) == {0o600}  # never wider, even while it is written
    assert archive.stat().st_mode & 0o777 == 0o600
