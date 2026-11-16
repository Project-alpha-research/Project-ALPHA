"""Run the honesty scorecard through the installed console program."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke


def test_partner_selftest(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(Path(sys.executable).with_name("alpha")), "partner", "selftest", "--json"],
        env={**os.environ, "ALPHA_DATA_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["total"] == report["passed"] == 25
