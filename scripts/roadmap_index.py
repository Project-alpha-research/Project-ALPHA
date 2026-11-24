"""Print the roadmap index: backlog items and staged refactors, made on demand, never stored.

Sources (read-only): ``docs/roadmap/backlog/*.md`` and ``docs/roadmap/refactors/*.md``.

Run ``uv run python scripts/roadmap_index.py`` to print it to the terminal.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
ROADMAP = Path("docs/roadmap")
COMMAND = "uv run python scripts/roadmap_index.py"

_FIELD = re.compile(r"^\*\*(?P<key>[^*]+):\*\* (?P<value>.+)$")
_JSON_BLOCK = re.compile(r"^```json[ \t]*\n(.*?)\n```", re.S | re.M)
_BACKLOG_STATUS = ("Idea", "Scoped")
_SIZES = ("S", "M", "L", "XL")
_RISKS = ("L", "M", "H")


class RoadmapError(ValueError):
    """A source document does not follow its template."""


def _cell(text: str) -> str:
    return text.replace("|", "\\|").strip()


def _title(rel: Path, text: str) -> str:
    fence = False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        elif not fence and line.startswith("# "):
            return line[2:].strip()
    match = _JSON_BLOCK.search(text)
    if match is not None:
        try:
            block = json.loads(match.group(1))
        except ValueError as exc:
            raise RoadmapError(f"{rel}: front block is not valid JSON") from exc
        if isinstance(block, dict) and isinstance(block.get("title"), str):
            return str(block["title"])
    raise RoadmapError(f"{rel}: no '# ' title and no front-block title")


def _fields(rel: Path, text: str, required: dict[str, tuple[str, ...]]) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines()[:8]:
        match = _FIELD.match(line.strip())
        if match is not None:
            found[match.group("key")] = match.group("value").strip()
    for key, allowed in required.items():
        if found.get(key) not in allowed:
            raise RoadmapError(f"{rel}: '**{key}:**' must be one of {', '.join(allowed)}")
    return found


def _read(root: Path, rel: Path) -> str:
    return (root / rel).read_text(encoding="utf-8")


def _docs(root: Path, folder: Path) -> list[Path]:
    return sorted(
        p.relative_to(root) for p in (root / folder).glob("*.md") if p.name != "README.md"
    )


def render(root: Path = ROOT) -> str:
    """The full expected text of docs/roadmap/README.md."""
    backlog: list[tuple[str, str, str]] = []
    for rel in _docs(root, ROADMAP / "backlog"):
        text = _read(root, rel)
        fields = _fields(rel, text, {"Status": _BACKLOG_STATUS, "Rough size": _SIZES})
        link = f"[{_cell(_title(rel, text))}](backlog/{rel.name})"
        backlog.append((link, fields["Status"], fields["Rough size"]))
    refactors: list[tuple[str, str]] = []
    for rel in _docs(root, ROADMAP / "refactors"):
        text = _read(root, rel)
        fields = _fields(rel, text, {"Risk": _RISKS})
        refactors.append((f"[{_cell(_title(rel, text))}](refactors/{rel.name})", fields["Risk"]))

    out = [
        "# Roadmap",
        "",
        f"Index of planned and unplanned work, made on demand by `{COMMAND}`; it is not stored.",
        "",
        "Lifecycle: an unplanned feature starts as a [backlog item](backlog/); when it is built,",
        "its pull request is the record and the item is removed. How a change is built:",
        "[the build team](../reference/project/components/delivery-and-agent-tooling.md).",
        "Structural refactors are staged in [refactors/](refactors/).",
        "",
        "What works today: `uv run python scripts/status.py`, made from the",
        "[capability map](capabilities.toml), which also holds the owner's decisions. Work in",
        "progress is the open pull requests.",
        "",
        f"## Backlog ({len(backlog)})",
        "",
        "| Item | Status | Rough size |",
        "| --- | --- | --- |",
    ]
    out += [f"| {link} | {status} | {size} |" for link, status, size in backlog]
    out += [
        "",
        f"## Staged refactors ({len(refactors)})",
        "",
        "| Refactor | Risk |",
        "| --- | --- |",
    ]
    out += [f"| {link} | {risk} |" for link, risk in refactors]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    try:
        print(render(ROOT), end="")
    except RoadmapError as exc:
        print(f"roadmap_index: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
