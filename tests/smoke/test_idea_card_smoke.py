"""Write, read and list an idea card through the installed console program."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke
EXAMPLE = Path(__file__).parents[2] / "research/examples/idea-card.example.toml"


def _alpha(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(Path(sys.executable).with_name("alpha")), "idea", *args],
        env={**os.environ, "ALPHA_DATA_DIR": str(home)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_the_example_card_can_be_saved_shown_and_listed(tmp_path: Path) -> None:
    saved = _alpha(tmp_path, "new", "--from", str(EXAMPLE), "--json")
    assert saved.returncode == 0, saved.stderr
    identity = json.loads(saved.stdout)["id"]
    shown = _alpha(tmp_path, "show", identity)
    assert shown.returncode == 0 and "Not stated yet" not in shown.stdout
    listing = json.loads(_alpha(tmp_path, "list", "--json").stdout)
    assert [card["id"] for card in listing["cards"]] == [identity]
