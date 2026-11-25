"""Lint as law: product code may not end a run with os._exit or hook it with atexit.register.

A run must end by its own result, so the ruff banned-api rules (TID251) forbid both calls,
each with a message that says so.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"


def _banned_api() -> dict[str, Any]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    tool = data.get("tool", {})
    ruff = tool.get("ruff", {})
    lint = ruff.get("lint", ruff)
    tidy = lint.get("flake8-tidy-imports", {})
    return dict(tidy.get("banned-api", {}))


def _message(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("msg", ""))
    return str(entry)


def test_banned_api_table_already_exists() -> None:
    banned = _banned_api()
    assert banned, "the banned-api table (with the date rules) should already exist"


def test_os_exit_is_banned_with_own_result_message() -> None:
    banned = _banned_api()
    assert "os._exit" in banned, f"os._exit is not banned; banned: {sorted(banned)}"
    assert "own result" in _message(banned["os._exit"]).lower()


def test_atexit_register_is_banned_with_own_result_message() -> None:
    banned = _banned_api()
    assert "atexit.register" in banned, f"atexit.register is not banned; banned: {sorted(banned)}"
    assert "own result" in _message(banned["atexit.register"]).lower()


def test_ruff_flags_os_exit_and_atexit_register(tmp_path: Path) -> None:
    sample = tmp_path / "sample_exit.py"
    sample.write_text(
        "import atexit\n"
        "import os\n"
        "\n"
        "\n"
        "def _bye() -> None:\n"
        "    pass\n"
        "\n"
        "\n"
        "atexit.register(_bye)\n"
        "os._exit(0)\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--config",
            str(PYPROJECT),
            "--select",
            "TID251",
            "--output-format",
            "concise",
            str(sample),
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "os._exit" in output, output
    assert "atexit.register" in output, output
    assert output.lower().count("own result") >= 2, output
