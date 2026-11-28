"""Capabilities the owner decided to remove carry the state "Being removed"; the status page lists
them first, and every page and Read first row that points at them says so."""

from __future__ import annotations

import os
import re
from pathlib import Path

import capabilities
import status

ROOT = Path(__file__).parents[2]
STATE = "Being removed"
HEADING = "## Being removed: do not build on"
RESEARCH_CASES_PAGE = "docs/reference/project/components/research-cases-and-approval.md"
_LINK = re.compile(r"\]\(([^)\s]+)\)")


def _being_removed() -> list[capabilities.Capability]:
    cmap = capabilities.load(ROOT)
    caps = [c for c in cmap.capabilities if c.state == STATE]
    assert caps, "no capability carries the state 'Being removed'"
    return caps


def _removed_pages() -> set[Path]:
    pages = {(ROOT / doc).resolve() for cap in _being_removed() for doc in cap.docs}
    assert pages, "no Being-removed capability lists a document"
    return pages


def _context_files() -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".") and d not in {"node_modules", "__pycache__"}
        ]
        if "CONTEXT.md" in filenames:
            found.append(Path(dirpath) / "CONTEXT.md")
    return found


def _body_first_line(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            text = text[end + 4 :]
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped
    return ""


def test_being_removed_is_a_capability_state() -> None:
    assert STATE in capabilities.STATES
    assert capabilities.main([]) == 0


def test_being_removed_capabilities_link_the_owner_decision() -> None:
    for cap in _being_removed():
        removal = getattr(cap, "removal", "")
        assert removal, cap.id
        assert "owner-decisions-6.md" in removal, cap.id


def test_research_case_page_belongs_to_a_being_removed_capability() -> None:
    assert (ROOT / RESEARCH_CASES_PAGE).resolve() in _removed_pages()


def test_status_page_lists_being_removed_first() -> None:
    text = status.render(ROOT)
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert HEADING in headings
    assert headings.index(HEADING) < headings.index("## What works today")
    section = text.split(HEADING, 1)[1].split("\n## ", 1)[0]
    for cap in _being_removed():
        assert f"**{cap.label}**" in section, cap.id


def test_every_being_removed_page_starts_with_the_marker() -> None:
    for page in sorted(_removed_pages()):
        assert page.is_file(), page
        first = _body_first_line(page.read_text(encoding="utf-8"))
        assert first.lstrip("*_> ").startswith(STATE), f"{page}: {first!r}"


def test_read_first_rows_linking_a_being_removed_page_are_marked() -> None:
    pages = _removed_pages()
    checked = 0
    for ctx in _context_files():
        for line in ctx.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|"):
                continue
            cells = line.split("|")
            if len(cells) < 3:
                continue
            read = cells[1]
            for link in _LINK.findall(read):
                target = link.split("#", 1)[0]
                if not target or "://" in target:
                    continue
                if (ctx.parent / target).resolve() in pages:
                    checked += 1
                    assert "(being removed)" in read, f"{ctx.relative_to(ROOT)}: {line}"
    assert checked >= 2, "the alpha-research and alpha-study rows should link the page"
