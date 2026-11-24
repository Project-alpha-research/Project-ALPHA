"""Pages under docs/adr, docs/operations and docs/governance point at docs/work/ only by
a link to that file at the tag pre-thin-2026-11-14, never by a bare local path."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDERS = ("docs/adr", "docs/operations", "docs/governance")
TAG_URL = (
    r"https://github\.com/tradingsystem1880-eng/Project-ALPHA/(?:blob|tree)/"
    r"pre-thin-2026-11-14/docs/work/"
)
_LINK_AT_TAG = re.compile(r"\[[^\]]*\]\(<?" + TAG_URL + r"[^)\s>]*>?\)")
_BARE_AT_TAG = re.compile(TAG_URL + r"[^\s)>\]]*")


def local_work_paths(text: str) -> list[str]:
    """Lines still naming docs/work/ once every link at the tag is taken out."""
    stripped = _BARE_AT_TAG.sub("", _LINK_AT_TAG.sub("", text))
    return [line.strip() for line in stripped.splitlines() if "docs/work/" in line]


def _pages() -> list[Path]:
    pages: list[Path] = []
    for folder in FOLDERS:
        base = ROOT / folder
        if base.is_dir():
            pages.extend(sorted(base.rglob("*.md")))
    return pages


def test_governed_doc_folders_have_pages() -> None:
    assert any(p.is_relative_to(ROOT / "docs/adr") for p in _pages())


def test_tag_link_is_accepted_and_bare_path_is_not() -> None:
    good = (
        "See the [plan](https://github.com/tradingsystem1880-eng/Project-ALPHA/blob/"
        "pre-thin-2026-11-14/docs/work/archive/2026-08/x.md) for detail."
    )
    assert local_work_paths(good) == []
    bad = "- Phase plan: `docs/work/archive/2026-08/x.md`"
    assert local_work_paths(bad) != []
    other_ref = (
        "[record](https://github.com/tradingsystem1880-eng/Project-ALPHA/blob/"
        "094ce61213923cf9b74661013703cd6ebad16ecc/docs/work/archive/x.md)"
    )
    assert local_work_paths(other_ref) != []


def test_no_governed_page_names_a_local_docs_work_path() -> None:
    offenders: list[str] = []
    for page in _pages():
        for line in local_work_paths(page.read_text(encoding="utf-8")):
            offenders.append(f"{page.relative_to(ROOT)}: {line}")
    assert offenders == [], "pages still naming docs/work/ locally:\n" + "\n".join(offenders)
