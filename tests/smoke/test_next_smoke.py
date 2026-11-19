"""Run `alpha next` through the installed console program on an empty home."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke


def test_next_on_an_empty_home(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(Path(sys.executable).with_name("alpha")), "next", "--json"],
        env={**os.environ, "ALPHA_DATA_DIR": str(tmp_path / "home")},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert sorted(report) == [
        "ideas",
        "last_night",
        "notes",
        "paths",
        "recent_trials",
        "stores",
        "waiting",
    ]
    assert report["stores"] == [] and not (tmp_path / "home").exists()
