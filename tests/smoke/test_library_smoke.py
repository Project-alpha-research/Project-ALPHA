"""List, show and turn a library record into an idea card through the installed console program."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke


def _alpha(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(Path(sys.executable).with_name("alpha")), "library", *args],
        env={**os.environ, "ALPHA_DATA_DIR": str(home)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_a_library_record_becomes_an_idea_card(tmp_path: Path) -> None:
    listing = json.loads(_alpha(tmp_path, "list", "--json").stdout)["records"]
    assert len(listing) >= 20
    made = _alpha(tmp_path, "card", "short-term-reversal", "--json")
    assert made.returncode == 0, made.stderr
    shown = _alpha(tmp_path, "show", "short-term-reversal")
    assert shown.returncode == 0 and json.loads(made.stdout)["card"] in shown.stdout
