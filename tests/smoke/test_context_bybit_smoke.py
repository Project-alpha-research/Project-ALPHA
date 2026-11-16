"""Exercise offline Bybit import and as-known reads through the installed CLI."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.test_context_bybit_import import source

pytestmark = pytest.mark.smoke


def test_context_bybit_offline_import_and_read(tmp_path: Path) -> None:
    restored, data = tmp_path / "restored", tmp_path / "data"
    source(restored, [0, 8])
    source(restored, [0, 1], family="open_interest")
    env = {**os.environ, "ALPHA_DATA_DIR": str(data)}
    for args in [
        ["import-bybit", "--from", str(restored)],
        ["show-bybit", "--symbol", "BTCUSDT", "--kind", "funding", "--as-of", "2024-01-01"],
        [
            "show-bybit",
            "--symbol",
            "BTCUSDT",
            "--kind",
            "open-interest",
            "--as-of",
            "2024-01-01T01:05",
        ],
    ]:
        result = subprocess.run(
            [sys.executable, "-m", "alpha_cli.main", "context", *args, "--json"],
            env=env,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        if args[0] == "import-bybit":
            assert len(payload["tables"]) == 2 and payload["errors"] == {}
        else:
            assert len(payload["rows"]) == 1 and payload["view"] == "as_known"
