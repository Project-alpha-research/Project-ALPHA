"""Staleness of the file system's living documents: do they still match their sources?

A living document starts with front matter naming its ``owner``, the ``sources`` it describes
(git pathspec globs: ``*`` within a path segment, ``**`` across segments) and ``verified``: the
fingerprint of those sources when the document was last checked against them. A generated
document declares ``generated_by`` instead of ``owner``/``verified``; its freshness is checked
by its generator, so it is skipped here.

The fingerprint is a hash of the path and content of every source file in the working tree
(tracked, or new and not ignored; the file system's own documents do not count). A document is
stale when its ``verified`` differs from the current fingerprint: any source was edited, added
or removed since. ``verify`` writes the current fingerprint; ``owners`` answers the reverse
question, which documents describe a path. A fingerprint, unlike a commit, can be written in
the same commit as the source change, needs no history, and two branches that each change a
document's sources both rewrite the one ``verified`` line, so git reports a conflict.
Standard library only.
"""

from __future__ import annotations

import functools
import hashlib
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FRONT_MATTER_KEYS = ("owner", "sources", "verified")
GENERATED_KEYS = ("generated_by", "sources")
_KEY = re.compile(r"^([a-z_]+):\s*(.*?)\s*$")
_ITEM = re.compile(r"^\s+-\s+(.+?)\s*$")


class FrontMatterError(ValueError):
    """The front matter block is present but malformed."""


def front_matter(text: str) -> dict[str, str | list[str]] | None:
    """Parse a leading ``---`` block of ``key: value`` and ``key:`` + ``  - item`` lines.

    Returns None when the text has no front matter. Only this small YAML subset is accepted.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    result: dict[str, str | list[str]] = {}
    current: str | None = None
    for number, line in enumerate(lines[1:], 2):
        if line.strip() == "---":
            return result
        if not line.strip():
            continue
        item = _ITEM.match(line)
        if item and current is not None and isinstance(result[current], list):
            items = result[current]
            assert isinstance(items, list)
            items.append(item.group(1).strip("'\""))
            continue
        key = _KEY.match(line)
        if not key:
            raise FrontMatterError(f"line {number}: expected 'key: value' or '  - item'")
        name, value = key.group(1), key.group(2)
        if name in result:
            raise FrontMatterError(f"line {number}: duplicate key {name!r}")
        result[name] = value.strip("'\"") if value else []
        current = name
    raise FrontMatterError("front matter is not closed with '---'")


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


def pathspecs(globs: list[str]) -> list[str]:
    return [f":(glob){pattern}" for pattern in globs]


def tracked_matches(root: Path, pattern: str) -> list[str]:
    return [p for p in git(root, "ls-files", "--", *pathspecs([pattern])).splitlines() if p]


@functools.cache
def glob_regex(pattern: str) -> re.Pattern[str]:
    """The paths a ``sources`` glob covers, as git's ``:(glob)`` pathspec matches them."""
    if not any(char in pattern for char in "*?["):
        return re.compile(f"{re.escape(pattern.rstrip('/'))}(?:/.*)?")
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i) and (i == 0 or pattern[i - 1] == "/"):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i) and i + 2 == len(pattern) and out.endswith("/"):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out)


@functools.cache
def _any_of(sources: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{glob_regex(pattern).pattern})" for pattern in sources))


def covers(sources: list[str], path: str) -> bool:
    return _any_of(tuple(sources)).fullmatch(path) is not None


def working_files(root: Path) -> list[str]:
    """Every tracked file, and every new file git does not ignore, in path order."""
    listed = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted({p for p in listed.split("\0") if p})


def _digest(path: Path) -> str | None:
    if path.is_symlink():
        return hashlib.sha256(os.readlink(path).encode()).hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


@dataclass
class Tree:
    """One reading of the working tree, shared by every document checked in a run."""

    root: Path
    files: list[str]
    skip: frozenset[str]
    digests: dict[str, str | None] = field(default_factory=dict)


def fingerprint(tree: Tree, sources: list[str]) -> str:
    """Sixteen hex characters naming the content of the source files as they are on disk."""
    combined = hashlib.sha256()
    for rel in tree.files:
        if rel in tree.skip or not covers(sources, rel):
            continue
        if rel not in tree.digests:
            tree.digests[rel] = _digest(tree.root / rel)
        digest = tree.digests[rel]
        if digest is not None:  # a tracked file deleted from the working tree is gone
            combined.update(f"{rel}\0{digest}\n".encode())
    return combined.hexdigest()[:16]


@dataclass
class Report:
    path: str
    verified: str
    fingerprint: str = ""
    changed_files: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def stale(self) -> bool:
        return not self.problems and self.verified != self.fingerprint

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "verified": self.verified,
            "fingerprint": self.fingerprint,
            "stale": self.stale,
            "files": self.changed_files,
            "problems": self.problems,
        }


def living_documents(root: Path) -> dict[str, dict[str, str | list[str]]]:
    """Tracked Markdown files whose front matter has ``owner``/``sources``/``verified``."""
    found: dict[str, dict[str, str | list[str]]] = {}
    for rel in git(root, "ls-files", "-z", "--", "*.md").split("\0"):
        path = root / rel
        if not rel or not path.is_file() or path.is_symlink():
            continue
        with path.open(encoding="utf-8") as handle:
            if handle.readline().strip() != "---":
                continue
        try:
            meta = front_matter(path.read_text(encoding="utf-8"))
        except FrontMatterError:
            continue  # Not a file-system document (other tools' YAML); the contract test owns ours.
        if meta is not None and "owner" in meta and "verified" in meta:
            found[rel] = meta
    return found


def file_system_documents(root: Path, documents: dict[str, Any]) -> frozenset[str]:
    """Living documents and instruction files: prose, so never a source of another document."""
    loaders = git(root, "ls-files", "-z", "--", "CLAUDE.md", "*/CLAUDE.md", "AGENTS.md")
    return frozenset({*documents, *(rel for rel in loaders.split("\0") if rel)})


def _changed_since_last_commit(root: Path, rel: str, sources: list[str]) -> list[str]:
    """A hint for the reader: sources that differ from the commit that last changed ``rel``."""
    last = git(root, "log", "-1", "--format=%H", "--", rel).strip()
    if not last:
        return []
    names = git(root, "diff", "--name-only", last, "--").splitlines()
    return [name for name in names if covers(sources, name)]


def read_tree(root: Path, documents: dict[str, Any]) -> Tree:
    return Tree(root, working_files(root), file_system_documents(root, documents))


def check_document(tree: Tree, rel: str, meta: dict[str, str | list[str]]) -> Report:
    root = tree.root
    verified = meta.get("verified", "")
    sources = meta.get("sources", [])
    report = Report(rel, verified if isinstance(verified, str) else "")
    if not isinstance(sources, list) or not sources:
        report.problems.append("front matter has no 'sources' list")
        return report
    for pattern in sources:
        if not any(glob_regex(pattern).fullmatch(name) for name in tree.files):
            report.problems.append(f"source glob matches no file: {pattern}")
    if report.problems:
        return report
    # Edits to file-system documents themselves (this one, or a routing file inside a source
    # tree) do not make a document stale: they are prose, checked by the link and contract tests.
    report.fingerprint = fingerprint(tree, sources)
    if report.stale:
        report.changed_files = [
            p for p in _changed_since_last_commit(root, rel, sources) if p not in tree.skip
        ]
    return report


def stale(root: Path) -> list[Report]:
    """One report per living document, in path order."""
    documents = living_documents(root)
    tree = read_tree(root, documents)
    return [check_document(tree, rel, meta) for rel, meta in sorted(documents.items())]


def owners(root: Path, paths: list[str]) -> dict[str, list[str]]:
    """For each path, the living documents whose ``sources`` cover it (none for a document)."""
    documents = living_documents(root)
    skip = file_system_documents(root, documents)
    return {
        path: []
        if path in skip
        else sorted(
            rel
            for rel, meta in documents.items()
            if isinstance(sources := meta.get("sources"), list) and covers(sources, path)
        )
        for path in paths
    }


_VERIFIED_LINE = re.compile(r"^verified:.*$", re.MULTILINE)


def verify(root: Path, rels: list[str]) -> list[Report]:
    """Write the current fingerprint into each named document; refuse what cannot be checked."""
    documents = living_documents(root)
    tree = read_tree(root, documents)
    reports = []
    for rel in rels:
        if rel not in documents:
            raise ValueError(f"{rel} is not a living document (owner / sources / verified)")
        report = check_document(tree, rel, documents[rel])
        if report.problems:
            raise ValueError(f"{rel}: {'; '.join(report.problems)}")
        reports.append(report)
    for report in reports:
        if report.stale:
            path = root / report.path
            head, rule, body = path.read_text(encoding="utf-8").partition("\n---")
            stamped = _VERIFIED_LINE.sub(f"verified: {report.fingerprint}", head, count=1)
            path.write_text(stamped + rule + body, encoding="utf-8")
    return reports


def render_text(reports: list[Report]) -> str:
    flagged = [r for r in reports if r.stale or r.problems]
    lines = [
        f"{len(reports)} living documents checked; {sum(r.stale for r in reports)} "
        f"stale; {sum(bool(r.problems) for r in reports)} with problems"
    ]
    for report in flagged:
        if report.problems:
            lines.append(f"PROBLEM {report.path}")
            lines.extend(f"  - {problem}" for problem in report.problems)
        else:
            lines.append(f"STALE   {report.path}: its sources changed since it was verified")
            lines.extend(f"  - changed: {name}" for name in report.changed_files)
    if any(r.stale for r in reports):
        lines.append(
            "To fix: re-read each stale document against its sources, correct it, then run "
            "`uv run python scripts/fs.py verify <document>...`."
        )
    return "\n".join(lines)
