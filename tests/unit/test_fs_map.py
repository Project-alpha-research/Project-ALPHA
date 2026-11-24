"""The code map is read from the code: path, lines, docstring line; ``--find`` filters."""

from __future__ import annotations

from pathlib import Path

import fs
import fs_map
import pytest

from tests.unit._harness_support import REPO_ROOT as ROOT


def _fake_workspace(root: Path) -> None:
    pkg = root / "apps/demo/src/demo"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__/junk.py").write_text('"""Skipped."""\n')
    (pkg / "alpha.py").write_text('"""Estimate the time.\n\nMore text.\n"""\nX = 1\n')
    (pkg / "sub/beta.py").write_text("X = 2\n")
    front = root / "apps/demo/frontend/src"
    front.mkdir(parents=True)
    (front / "Panel.tsx").write_text("// Shows the panel.\nexport const P = 1;\n")
    (front / "api.generated.ts").write_text("// Skipped.\n")


def test_map_lists_path_line_count_and_first_docstring_line(tmp_path: Path) -> None:
    _fake_workspace(tmp_path)
    text = fs_map.code_map(tmp_path, "apps/demo")
    assert "apps/demo/src/demo/ (1)" in text
    assert "  alpha.py  5  Estimate the time." in text
    assert "  beta.py  1  (no description)" in text
    assert "  Panel.tsx  2  Shows the panel." in text
    assert "junk" not in text
    assert "generated" not in text


def test_find_needs_every_word_in_path_or_description(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_workspace(tmp_path)
    assert fs.main(["--root", str(tmp_path), "map", "apps/demo", "--find", "ESTIMATE", "time"]) == 0
    out = capsys.readouterr().out
    assert "alpha.py" in out
    assert "beta.py" not in out
    assert "no module in apps/demo matches" in fs_map.code_map(
        tmp_path, "apps/demo", ["estimate", "panel"]
    )
    assert "beta.py" in fs_map.code_map(tmp_path, "apps/demo", ["sub/beta"])


def test_unknown_workspace_is_an_error(tmp_path: Path) -> None:
    assert fs.main(["--root", str(tmp_path), "map", "apps/none"]) == 2


def test_every_alpha_cli_module_has_a_description() -> None:
    lines = fs_map.code_map(ROOT, "apps/alpha-cli").splitlines()
    missing = [ln for ln in lines if fs_map.NO_TEXT in ln and "__init__.py" not in ln]
    assert missing == []
