"""ADR awareness drift check, imported lazily by gate.py."""

from __future__ import annotations

import re
from pathlib import Path

_ADR_ID_RE = re.compile(r"^(\d{4})-")


def adr_files(root: Path) -> list[str]:
    """ADR filenames (``NNNN-*.md``) in docs/adr, sorted."""
    adr_dir = root / "docs" / "adr"
    if not adr_dir.is_dir():
        return []
    return sorted(p.name for p in adr_dir.glob("*.md") if _ADR_ID_RE.match(p.name))


_INDEX_LINK_RE = re.compile(r"\]\(\s*(?:\./)?(\d{4}-[^)\s#]+\.md)")


def adr_drift(root: Path) -> list[str]:
    """ADR files that the ADR index ``docs/adr/README.md`` does not link (its one listing)."""
    index = root / "docs" / "adr" / "README.md"
    text = index.read_text(errors="replace") if index.exists() else ""
    linked = set(_INDEX_LINK_RE.findall(text))
    ids: list[str] = []
    for name in adr_files(root):
        if name not in linked:
            match = _ADR_ID_RE.match(name)
            assert match is not None
            ids.append(f"ADR-{match.group(1)}")
    return ids
