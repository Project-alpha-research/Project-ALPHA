"""Back up, check and restore a throwaway home through the installed `alpha` program."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke


def alpha(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(Path(sys.executable).with_name("alpha")), "home", *args],
        env={**os.environ, "ALPHA_DATA_DIR": str(home)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_backup_verify_and_restore_round_trip(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "data" / "1d").mkdir(parents=True)
    (home / "data" / "1d" / "AAA.bin").write_bytes(bytes(range(256)) * 400)
    (home / "ledger").mkdir()
    (home / "ledger" / "trials.jsonl").write_text('{"trial": 1}\n', encoding="utf-8")
    before = {
        str(p.relative_to(home)): p.read_bytes() for p in sorted(home.rglob("*")) if p.is_file()
    }
    made = alpha(home, "backup", str(tmp_path / "backups"), "--json")
    assert made.returncode == 0, made.stderr
    archive = json.loads(made.stdout)["archive"]
    checked = alpha(home, "verify-backup", archive, "--json")
    assert checked.returncode == 0, checked.stderr
    report = json.loads(checked.stdout)
    assert report["ok"] is True and report["files_bad"] == 0 and report["files_checked"] == 3
    target = tmp_path / "restored"
    restored = alpha(home, "restore", archive, str(target))
    assert restored.returncode == 0, restored.stderr
    after = {
        str(p.relative_to(target)): p.read_bytes()
        for p in sorted(target.rglob("*"))
        if p.is_file() and p.name != ".lock"
    }
    assert after == before
    inside = alpha(home, "backup", str(home / "backups"))
    assert inside.returncode == 2 and "inside the data home" in inside.stderr
    again = alpha(home, "restore", archive, str(target))
    assert again.returncode == 2 and "not empty" in again.stderr
