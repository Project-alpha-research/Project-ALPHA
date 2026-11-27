"""The CLI registry test exists, passes, and fails when a registry string points nowhere."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_TEST = ROOT / "tests" / "unit" / "test_cli_registry.py"
PROBE = "alpha_cli._missing_registry_probe"

_BROKEN = """
import json, sys
import pytest
import alpha_cli.main as entry

probe = sys.argv[1]
first = entry.GROUPS[0]
broken = []
for field in first:
    if isinstance(field, str) and "alpha_cli" in field:
        suffix = ":" + field.split(":", 1)[1] if ":" in field else ""
        broken.append(probe + suffix)
    else:
        broken.append(field)
broken[0] = "zz-registry-probe"
entry.GROUPS = (*entry.GROUPS, tuple(broken))
sys.exit(pytest.main([sys.argv[2], "-q", "-p", "no:cacheprovider"]))
"""


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["TYPER_USE_RICH"] = "0"
    return env


def _pytest(target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(target), "-q", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=_env(),
        timeout=300,
        check=False,
    )


def test_registry_still_loads() -> None:
    import alpha_cli.main as entry

    assert len(entry.GROUPS) > 0
    assert all(isinstance(group, tuple) and len(group) == 3 for group in entry.GROUPS)
    assert callable(entry._full_app)


def test_registry_test_exists_and_passes() -> None:
    assert REGISTRY_TEST.is_file(), f"missing {REGISTRY_TEST}"
    result = _pytest(REGISTRY_TEST)
    assert result.returncode == 0, result.stdout + result.stderr
    assert " passed" in result.stdout, result.stdout


def test_registry_test_fails_when_a_registry_string_is_broken() -> None:
    assert REGISTRY_TEST.is_file(), f"missing {REGISTRY_TEST}"
    result = subprocess.run(
        [sys.executable, "-c", _BROKEN, PROBE, str(REGISTRY_TEST)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=_env(),
        timeout=300,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "_missing_registry_probe" in output, json.dumps(output[-4000:])
