"""`alpha follow` through the installed console program: an empty list and a refused factor."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke


def _alpha(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(Path(sys.executable).with_name("alpha")), "follow", *args],
        env={**os.environ, "ALPHA_DATA_DIR": str(home)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_an_empty_home_lists_no_follows_and_a_factor_is_refused(tmp_path: Path) -> None:
    listing = _alpha(tmp_path, "list", "--json")
    assert listing.returncode == 0, listing.stderr
    assert json.loads(listing.stdout) == {"follows": []}
    refused = _alpha(tmp_path, "start", "--factor", "x")
    assert refused.returncode == 1 and "not built yet" in refused.stdout
    assert not (tmp_path / "forward").exists()
