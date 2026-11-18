"""What a Codex build reads, what it leaves in git, and how its checks run outside the sandbox.

- **Routed reading.** A workspace's ``CONTEXT.md`` names, in its ``## Read first`` table, the
  files and sections to read and when. ``route`` turns the tables of every workspace a build
  touches into read-list entries by section, each with its size in bytes, drops what the brief's
  own table already covers, puts ``always`` rows first and stops adding at a byte cap, naming
  what it left out. The builder then reads what the routing says, not only what a brief picked.
- **The task folder.** ``docs/work/<date>-<slug>/`` on the build's branch holds ``brief.md``
  (what was asked and decided, editable before a relaunch) and ``report.md`` (the builder's
  final report: what was done and what is unverified). Home paths are made repo-relative or
  ``<outside-repo>`` and model names are removed, so nothing about the machine lands in git.
- **Checks.** ``owned`` runs a pytest check under ``run_owned_test.py``, as ``gate.py`` does;
  ``check_env`` gives checks a private ``TMPDIR`` under ``/dev/shm`` (a stray ``/tmp/.git``
  breaks tests that create repositories); ``web_bundle`` makes sure the built web app exists in
  the worktree before checks run: linked from the main checkout the way the build sandbox links
  it, or built with ``npm`` when the frontend changed or a check runs ``npm`` itself.

Stdlib only.
"""

from __future__ import annotations

import contextlib
import datetime
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from handoff_sandbox import WEB_ASSETS, Prepared, link_built_files

ROUTED_CAP_BYTES = 24 * 1024
WORK_DIR = "docs/work"
WEB_FRONTEND = "apps/alpha-web/frontend"
NPM_TIMEOUT = 900.0
OWNER = Path(__file__).resolve().with_name("run_owned_test.py")
_WHOLE = frozenset({"", "—", "-", "whole", "whole file", "every file"})
_LINK = re.compile(r"\]\(([^)\s]+)\)")
_CODE = re.compile(r"`([^`]+)`")
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_HOME = re.compile(r"(?:/home|/Users)/[^/\s`'\"<>()\[\]]+(?:/[^\s`'\"<>()\[\]]*)?")
_MODEL = re.compile(
    r"\b(?:gpt-[0-9][\w.-]*|claude-[\w.-]+|(?:opus|sonnet|haiku|fable)(?:[- ][0-9][\w.]*)?)\b",
    re.IGNORECASE,
)
_PYTEST = re.compile(r"\buv run (?:--\S+ )*pytest\b")
_NPM = re.compile(r"\b(?:npm|npx|vite|vitest)\b")


@dataclass(frozen=True)
class ReadRow:
    """One file a reading table names: ``section`` is "" for the whole file."""

    target: str
    section: str
    when: str
    origin: str


def github_slug(heading: str) -> str:
    """The anchor GitHub gives a heading (as ``tests/unit/test_docs_links.py`` computes it)."""
    text = re.sub(r"<[^>]+>", "", heading)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text).replace("`", "").lower()
    kept = [c for c in text if c in " -_" or unicodedata.category(c)[0] in "LNM"]
    return "".join(kept).replace(" ", "-")


def headings(text: str) -> list[tuple[int, int, str]]:
    """(line index, level, title) for every heading outside fenced code."""
    found, fence = [], None
    for index, line in enumerate(text.splitlines()):
        match = _FENCE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        heading = _HEADING.match(line) if fence is None else None
        if heading:
            found.append((index, len(heading.group(1)), heading.group(2)))
    return found


def section_bytes(text: str, section: str) -> int | None:
    """Bytes from the named heading to the next heading of the same or higher level."""
    lines, found = text.splitlines(keepends=True), headings(text)
    for position, (index, level, title) in enumerate(found):
        if github_slug(title) == github_slug(section):
            end = next((i for i, lvl, _ in found[position + 1 :] if lvl <= level), len(lines))
            return len("".join(lines[index:end]).encode("utf-8"))
    return None


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _targets(cell: str, doc_dir: Path, root: Path) -> list[tuple[str, str]]:
    """(repo-relative path or the raw text, anchor) for each link or code span in a Read cell."""
    raw = _LINK.findall(cell) or _CODE.findall(cell) or [cell.strip("`")]
    found = []
    for item in raw:
        path, _, anchor = item.strip().partition("#")
        if not path:
            continue
        try:
            rel = (doc_dir / path).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = path
        found.append((rel, anchor))
    return found


def table_rows(
    text: str, doc_dir: Path, root: Path, origin: str
) -> tuple[list[ReadRow], list[str]]:
    """Rows of the ``## Read first`` table (Read | Section | When), and what could not be read."""
    lines = text.splitlines()
    start = next((i for i, lvl, t in headings(text) if lvl == 2 and t == "Read first"), None)
    if start is None:
        return [], []
    end = next((i for i, lvl, _ in headings(text) if i > start and lvl <= 2), len(lines))
    table = [ln for ln in lines[start + 1 : end] if ln.strip().startswith("|")]
    if not table:
        return [], []
    if _cells(table[0]) != ["Read", "Section", "When"]:
        return [], [f"{origin}: the Read first table header is not '| Read | Section | When |'"]
    rows, problems = [], []
    for line in table[1:]:
        cells = _cells(line)
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if len(cells) != 3:
            problems.append(f"{origin}: Read first row skipped (needs 3 cells): {line.strip()}")
            continue
        section = "" if cells[1].lower() in _WHOLE else cells[1]
        for target, anchor in _targets(cells[0], doc_dir, root):
            rows.append(ReadRow(target, section or anchor, cells[2], origin))
    return rows, problems


def workspace_contexts(root: Path, files: Sequence[str]) -> list[str]:
    """The nearest ``CONTEXT.md`` above each file in scope, once each, in order."""
    found: list[str] = []
    for item in files:
        path = Path(re.split(r"[*?\[]", item, maxsplit=1)[0].rstrip("/"))
        for parent in [path, *path.parents]:
            if parent == Path("."):
                break
            candidate = parent / "CONTEXT.md"
            if (root / candidate).is_file():
                if candidate.as_posix() not in found:
                    found.append(candidate.as_posix())
                break
    return found


def reading_rows(root: Path, context: str) -> tuple[list[ReadRow], list[str]]:
    text = (root / context).read_text(encoding="utf-8")
    return table_rows(text, (root / context).parent, root, context)


@dataclass
class Routing:
    """The routed read list for one build, sized and capped."""

    cap: int
    entries: list[dict[str, Any]] = field(default_factory=list)
    left_out: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(int(e["bytes"]) for e in self.entries)

    def prompt_lines(self) -> list[str]:
        lines = [
            f"- `{e['path']}` — {e['section'] or 'whole file'} ({e['bytes']:,} bytes); "
            f"{e['when']} (routed from `{e['from']}`)"
            for e in self.entries
        ]
        if self.left_out:
            names = ", ".join(f"`{e['path']}` {e['section'] or 'whole'}" for e in self.left_out)
            lines.append(f"- Also routed, left out over the {self.cap:,}-byte cap: {names}")
        return lines

    def record(self) -> dict[str, Any]:
        return {
            "entries": self.entries,
            "total_bytes": self.total,
            "cap_bytes": self.cap,
            "left_out": self.left_out,
            "problems": self.problems,
        }


def route(
    root: Path, contexts: Sequence[str], brief: Sequence[ReadRow], cap: int = ROUTED_CAP_BYTES
) -> Routing:
    """Read-list entries from each touched workspace's reading table, minus what the brief reads."""
    whole = {r.target for r in brief if not r.section}
    seen = {(r.target, github_slug(r.section)) for r in brief if r.section}
    rows: list[ReadRow] = []
    routing = Routing(cap)
    for context in contexts:
        found, problems = reading_rows(root, context)
        rows += found
        routing.problems += problems
    for row in sorted(rows, key=lambda r: r.when.strip().lower() != "always"):
        key = (row.target, github_slug(row.section))
        if row.target in whole or key in seen:
            continue
        seen.add(key)
        path = root / row.target
        if not path.is_file():
            routing.problems.append(f"{row.origin}: {row.target} is not a file")
            continue
        text = path.read_text(encoding="utf-8")
        size = section_bytes(text, row.section) if row.section else len(text.encode("utf-8"))
        if size is None:
            routing.problems.append(f"{row.origin}: {row.target} has no section {row.section!r}")
            continue
        entry = {"path": row.target, "section": row.section, "when": row.when, "bytes": size}
        entry["from"] = row.origin
        if routing.total + size > cap:
            routing.left_out.append(entry)
            continue
        routing.entries.append(entry)
        if not row.section:
            whole.add(row.target)  # its sections, routed later, add nothing
    return routing


# ---------------------------------------------------------------------------------------------
# The task folder in git


def strip_paths(text: str, roots: Sequence[Path]) -> str:
    """Paths in a root made repo-relative, other home paths ``<outside-repo>``; no model names."""
    for root in sorted((Path(r).as_posix() for r in roots), key=len, reverse=True):
        text = re.sub(re.escape(root) + r"(?:/|(?=[\s`'\"<>()\[\],;:]|\.?$))", "", text)
    return _MODEL.sub("<model>", _HOME.sub(_outside, text))


def _outside(match: re.Match[str]) -> str:
    found = match.group(0)
    path = found.rstrip(".,;:")
    return "<outside-repo>" + found[len(path) :]


def task_folder(worktree: Path, name: str, task_dir: str | None, today: str) -> str:
    """The build's folder: the task's own, an existing one for this brief, or a new dated one."""
    if task_dir:
        return task_dir
    existing = sorted((worktree / WORK_DIR).glob(f"????-??-??-{name}"))
    return (
        existing[-1].relative_to(worktree).as_posix() if existing else f"{WORK_DIR}/{today}-{name}"
    )


def save_task_files(
    worktree: Path, roots: Sequence[Path], folder: str, *, brief: str | None, report: str
) -> list[str]:
    """Write ``brief.md`` (when given) and ``report.md`` (when the builder reported)."""
    written = []
    name = folder.rsplit("/", 1)[-1][11:]
    for file, text in (("brief.md", brief), ("report.md", report)):
        if not text or not text.strip():
            continue
        body = text if file == "brief.md" else f"# Build report: {name}\n\n{text.strip()}\n"
        target = worktree / folder / file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(strip_paths(body, roots), encoding="utf-8")
        written.append(f"{folder}/{file}")
    return written


def _today() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")


def task_file_paths(worktree: Path, name: str, task_dir: str | None) -> list[str]:
    """The two files a build may leave in its task folder (outputs, never scope)."""
    folder = task_folder(worktree, name, task_dir, _today())
    return [f"{folder}/brief.md", f"{folder}/report.md"]


def leave_task_files(
    worktree: Path, main: Path, name: str, task_dir: str | None, brief: str | None, report: str
) -> list[str]:
    """Write the brief and the builder's report into the task folder; a note naming them."""
    folder = task_folder(worktree, name, task_dir, _today())
    written = save_task_files(worktree, [worktree, main], folder, brief=brief, report=report)
    return [f"task folder: wrote {', '.join(written)}"] if written else []


# ---------------------------------------------------------------------------------------------
# Checks outside the sandbox


def owned(command: str, timeout: float) -> str:
    """A pytest check wrapped in ``run_owned_test.py`` (it reaps orphans, as ``gate.py`` does)."""
    if not _PYTEST.search(command):
        return command
    owner = [sys.executable, str(OWNER), "--timeout", str(int(timeout)), "--", "bash", "-c"]
    return shlex.join([*owner, command])


@contextlib.contextmanager
def check_env() -> Iterator[dict[str, str]]:
    """The environment for checks: a private ``TMPDIR`` under ``/dev/shm`` when there is one."""
    env = dict(os.environ)
    shm = Path("/dev/shm")
    if not (shm.is_dir() and os.access(shm, os.W_OK)):
        yield env
        return
    private = Path(tempfile.mkdtemp(prefix="alpha-handoff-", dir=shm))
    env["TMPDIR"] = str(private)
    try:
        yield env
    finally:
        shutil.rmtree(private, ignore_errors=True)


@dataclass
class WebStep:
    """What ``web_bundle`` did: links to remove after the checks, new ignored paths, notes."""

    prep: Prepared | None = None
    ignored: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)


def web_bundle(
    worktree: Path, main: Path, changed: Sequence[str], commands: Sequence[str]
) -> WebStep:
    """Make the built web app present in the worktree before checks run there."""
    step = WebStep()
    if not (worktree / WEB_FRONTEND / "package.json").is_file():
        return step
    frontend_changed = any(p.startswith(f"{WEB_FRONTEND}/") for p in changed)
    if (worktree / WEB_ASSETS / "index.html").is_file() and not frontend_changed:
        return step
    runs_npm = any(_NPM.search(c) for c in commands)
    main_built = (
        main / WEB_ASSETS / "index.html"
    ).is_file() and main.resolve() != worktree.resolve()
    if main_built and not frontend_changed and not runs_npm:
        step.prep = Prepared(main)
        link_built_files(worktree, step.prep)
        step.notes.append("linked the main checkout's built web app for the checks")
        return step
    if shutil.which("npm") is None:
        step.notes.append("web app not built for the checks: npm is not available")
        return step
    cwd = worktree / WEB_FRONTEND
    before = {
        rel
        for rel in (f"{WEB_FRONTEND}/node_modules/", f"{WEB_ASSETS}/")
        if (worktree / rel).exists()
    }
    steps = [["npm", "run", "build"]]
    if not (cwd / "node_modules").is_dir():
        steps.insert(0, ["npm", "ci"])
    for command in steps:
        try:
            out = subprocess.run(
                command, cwd=cwd, capture_output=True, text=True, timeout=NPM_TIMEOUT, check=False
            )
        except subprocess.TimeoutExpired:
            step.notes.append(
                f"web app not built for the checks: `{shlex.join(command)}` timed out"
            )
            return step
        if out.returncode != 0:
            tail = (out.stdout + out.stderr).strip()[-200:]
            step.notes.append(f"web app not built for the checks: `{shlex.join(command)}`: {tail}")
            return step
    step.ignored = {
        rel
        for rel in (f"{WEB_FRONTEND}/node_modules/", f"{WEB_ASSETS}/")
        if (worktree / rel).exists() and rel not in before
    }
    step.notes.append(
        f"built the web app in the worktree for the checks ({', '.join(map(shlex.join, steps))})"
    )
    return step
