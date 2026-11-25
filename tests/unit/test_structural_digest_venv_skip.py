"""Bug: the tree scans in tests/unit/test_structural_digest.py read worker environments.

A worker environment such as ``.venv-rule-qualified`` sits at the repository root next to
``.venv``. The scans must skip every folder whose name starts with ``.venv``, so whatever a
worker environment contains can never change their result.

The check plants a hostile worker environment (undecodable bytes, a syntax error and digest
reader calls) at the root, runs the real structural-digest test file through pytest, and
requires it to still pass. The planted folder is always removed afterwards.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = "tests/unit/test_structural_digest.py"

_HOSTILE = (
    b"\xff\xfe\x00\x80 not utf-8\n"
    b"from alpha_cli._structural_digest import binding_digest, file_binding, source_binding\n"
    b"from alpha_cli import _structural_digest\n"
    b"file_binding(open('x', 'rb').read())\n"
    b"source_binding(b'')\n"
    b"binding_digest(None)\n"
    b"def (:\n"
)


def _plant(venv: Path) -> None:
    files = [
        venv / "probe_reader.py",
        venv / "lib" / "python3.12" / "site-packages" / "alpha_cli" / "_structural_digest.py",
        venv / "lib" / "python3.12" / "site-packages" / "alpha_cli" / "probe_reader.py",
        venv / "lib" / "python3.12" / "site-packages" / "probe_pkg" / "__init__.py",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_HOSTILE)


def test_structural_digest_scans_ignore_worker_venv_folders() -> None:
    venv = ROOT / f".venv-spec-probe-{uuid.uuid4().hex[:8]}"
    assert not venv.exists()
    try:
        _plant(venv)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", TARGET],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    finally:
        shutil.rmtree(venv, ignore_errors=True)
    assert result.returncode == 0, (
        f"{TARGET} read the worker environment {venv.name}:\n"
        f"{result.stdout[-6000:]}\n{result.stderr[-3000:]}"
    )
