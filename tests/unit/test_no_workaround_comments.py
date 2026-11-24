"""Product source holds no comment that explains a workaround."""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).parents[2]
_WORDS = re.compile(r"\b(hack|workaround|temporary|for now|todo|fixme|xxx)\b", re.IGNORECASE)
_MESSAGE = "Fix the cause or open an order; do not explain a workaround in a comment."


def _hits(source: str) -> list[tuple[int, str]]:
    comments = (
        (tok.start[0], tok.string)
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type == tokenize.COMMENT
    )
    return [(line, text) for line, text in comments if _WORDS.search(text)]


def test_detector_finds_marker_comments_only() -> None:
    assert _hits("x = 1  # temporary hack\n") == [(1, "# temporary hack")]
    assert _hits('x = "todo for now"\n# fine\n') == []


def test_product_source_has_no_workaround_comments() -> None:
    found = []
    for src in [*ROOT.glob("apps/*/src"), *ROOT.glob("packages/*/src")]:
        for path in src.rglob("*.py"):
            if "_vendor" in path.parts:
                continue
            found += [
                f"{path.relative_to(ROOT)}:{line}: {text}"
                for line, text in _hits(path.read_text(encoding="utf-8"))
            ]
    assert not found, _MESSAGE + "\n" + "\n".join(found)
