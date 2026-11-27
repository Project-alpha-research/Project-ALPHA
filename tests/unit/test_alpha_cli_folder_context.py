"""The spine, toolbox and figures folders of alpha-cli carry folder notes in the workspace shape.

Each folder has a CONTEXT.md with the workspace sections and a one-line CLAUDE.md that imports
it; the file-system contract's context_files() lists them and the alpha-cli code map names them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
PACKAGE = ROOT / "apps" / "alpha-cli" / "src" / "alpha_cli"
FOLDERS = ("spine", "toolbox", "figures")
SECTIONS = ("Purpose", "Read first", "How to change it", "Outputs")
LOADER = "@CONTEXT.md\n"


def test_alpha_cli_package_folders_exist() -> None:
    missing = [name for name in FOLDERS if not (PACKAGE / name).is_dir()]
    assert not missing, f"alpha-cli folders missing: {missing}"


@pytest.mark.parametrize("folder", FOLDERS)
def test_folder_has_context_with_workspace_sections(folder: str) -> None:
    path = PACKAGE / folder / "CONTEXT.md"
    assert path.is_file(), f"add {path.relative_to(ROOT)}"
    text = path.read_text(encoding="utf-8")
    headings = {
        m.group(1).strip() for m in re.finditer(r"^#{2,3}\s+(.+?)\s*$", text, flags=re.MULTILINE)
    }
    missing = [s for s in SECTIONS if s not in headings]
    assert not missing, f"{path.relative_to(ROOT)} lacks sections {missing}"


@pytest.mark.parametrize("folder", FOLDERS)
def test_folder_has_one_line_loader(folder: str) -> None:
    path = PACKAGE / folder / "CLAUDE.md"
    assert path.is_file(), f"add {path.relative_to(ROOT)}"
    assert path.read_text(encoding="utf-8") == LOADER


def test_context_files_lists_folder_notes() -> None:
    from tests.unit.test_filesystem_contract import context_files

    listed = set(context_files())
    expected = {f"apps/alpha-cli/src/alpha_cli/{name}/CONTEXT.md" for name in FOLDERS}
    missing = sorted(expected - listed)
    assert not missing, f"context_files() does not list {missing}"


def test_alpha_cli_code_map_lists_folder_notes() -> None:
    readme = (ROOT / "apps" / "alpha-cli" / "README.md").read_text(encoding="utf-8")
    missing = [name for name in FOLDERS if f"{name}/CONTEXT.md" not in readme]
    assert not missing, f"apps/alpha-cli/README.md code map does not name {missing}"
