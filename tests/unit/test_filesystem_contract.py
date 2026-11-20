"""The file system's contract: small routing files, exact read lists, one home per fact.

The file system (ADR-0040) follows the Interpretable Context Methodology adapted to a codebase:

* Layer 0: ``CLAUDE.md`` (identity and the non-negotiable rules) and ``AGENTS.md`` (a pointer for
  other agents) are small and send the reader to the root ``CONTEXT.md``.
* Layer 1: the root ``CONTEXT.md`` routes every kind of task to a workspace.
* Layer 2: every workspace (each project under ``packages/``, ``apps/``, ``workers/``,
  plus ``scripts/``, ``tests/``, ``docs/``, the delivery pipeline ``workflow/`` and the research
  route ``research/``) has a ``CONTEXT.md`` with the sections Purpose, Read first, How to
  change it, Outputs. Its Read first table names exact files and sections. Each stage of the
  delivery pipeline, ``workflow/stages/NN-name/``, has a ``CONTEXT.md`` with Purpose, Inputs,
  Read first, Process, Outputs, Checkpoint, and the pipeline's ``CONTEXT.md`` links every stage.
  Research is not staged: ``research/CONTEXT.md`` routes to the playbook, tool cards, skills and
  lessons, which ``tests/unit/test_research_playbook.py`` checks against the program.
* Outputs: a task folder ``docs/work/<yyyy-mm-dd>-<slug>/`` holds a planned task's stage files
  and its ``02-plan.md``, or a build's ``brief.md`` and ``report.md`` (``docs/work/CONTEXT.md``).
* Layer 3: reference documents under ``docs/reference/``: the rules (``invariants/``) and the
  project layer (``project/``: what each major part is for, and the owner's decisions).
* Loading: each workspace has a one-line ``CLAUDE.md`` that imports its ``CONTEXT.md``; Claude
  Code loads a subdirectory's ``CLAUDE.md`` when it opens a file there. ``.claude/rules/*.md`` are
  thin path-scoped pointers (an ``@`` import inside a path-scoped rule loads at launch, so the
  rules link instead of importing).

Every routing and reference document declares who owns it, which files it describes and the
fingerprint of those files it was verified against (``scripts/fs.py stale`` uses these). The
"always read" set of a workspace (CLAUDE.md, rules, both CONTEXT files, always rows) must stay
within 16 KB. Failure messages say what to change.
"""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import fs_stale
import pytest

from tests.unit.test_docs_links import _FENCE, _HEADING, anchors, broken_links, github_slug

ROOT = Path(__file__).parents[2]
CONTEXT = "CONTEXT.md"
WORKSPACE_PARENTS = ("packages", "apps", "workers")
EXTRA_WORKSPACES = ("scripts", "tests", "docs", "workflow", "research")
REFERENCE_DIR = "docs/reference"
REQUIRED_SECTIONS = ("Purpose", "Read first", "How to change it", "Outputs")
PIPELINES = ("workflow",)  # each has <pipeline>/stages/NN-name/CONTEXT.md; research is not staged
STAGES = "stages"
STAGE_SECTIONS = ("Purpose", "Inputs", "Read first", "Process", "Outputs", "Checkpoint")
_STAGE_NAME = re.compile(r"^\d{2}-[a-z]+$")
WORK_DIR = "docs/work"
TASK_PLAN = "02-plan.md"
BUILD_RECORD = "03-build.json"  # written by scripts/handoff.py, committed with the build
STAGE_OUTPUTS = frozenset({"01-brief.md", TASK_PLAN, BUILD_RECORD, "04-verify.md", "05-handoff.md"})
# A build from a brief leaves these (scripts/handoff_routing.py): outputs, not living documents.
BUILD_OUTPUTS = frozenset({"brief.md", "report.md"})
_TASK_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*$")
CONTEXT_MAX_LINES = 40
CONTEXT_MAX_BYTES = 2_560
STAGE_CONTEXT_MAX_LINES = 60  # a stage file keeps its Process, which is a contract
CONTEXT_BODY_MAX_LINES = 14  # non-blank lines of a workspace body, headings and tables left out
READ_FIRST_MAX_ROWS = 12
WHEN_MAX_CHARS = 60
REFERENCE_MAX_LINES = 200
REFERENCE_LINES_ADVICE = "split by heading into a sibling file; do not shorten text"
CONTEXT_LINES_ADVICE = "move detail to a reference file and link to its section"
MAX_LINE_CHARS = 160
ALWAYS_BUDGET_BYTES = 16_384
ALWAYS_ROWS_MAX_BYTES = 6_144  # the "always" rows of one workspace, section rows counted in full
ALWAYS_WHOLE_FILE_MAX_BYTES = 3_072  # an "always" row may name a whole file only up to this size
LIVING_KEYS = {"owner", "sources", "verified"}
GENERATED_KEYS = {"generated_by", "sources"}
_OWNER = re.compile(r"^[a-z][a-z0-9 ,/&()-]{2,40}$")
_LINK = re.compile(r"^\[[^\]]+\]\(([^)\s]+)\)$")
_COMING = "(coming)"
NONE_MARK = "—"
IDENTITY = "CLAUDE.md"
AGENT_POINTER = "AGENTS.md"
IDENTITY_MAX_LINES = 80
AGENT_POINTER_MAX_LINES = 12
RULES_DIR = ".claude/rules"
RULE_MAX_LINES = 12
UNSCOPED_RULES = ("00-karpathy.md",)
WORKSPACE_LOADER = "@CONTEXT.md\n"


@dataclass(frozen=True)
class ReadRow:
    read: str
    target: str | None
    section: str
    when: str


def workspaces() -> list[str]:
    """Workspace directories, discovered from the tree (a project has a pyproject.toml)."""
    found = [
        path.relative_to(ROOT).as_posix()
        for parent in WORKSPACE_PARENTS
        for path in sorted((ROOT / parent).iterdir())
        if path.is_dir() and (path / "pyproject.toml").is_file()
    ]
    return [*found, *EXTRA_WORKSPACES]


def stage_files(pipeline: str | None = None) -> list[str]:
    """``<pipeline>/stages/NN-name/CONTEXT.md`` for every stage folder of one or all pipelines."""
    return [
        f"{name}/{STAGES}/{path.name}/{CONTEXT}"
        for name in ((pipeline,) if pipeline else PIPELINES)
        for path in sorted((ROOT / name / STAGES).iterdir())
        if path.is_dir()
    ]


def is_stage_file(rel: str) -> bool:
    return any(rel.startswith(f"{name}/{STAGES}/") for name in PIPELINES)


def context_files() -> list[str]:
    return [CONTEXT, *(f"{ws}/{CONTEXT}" for ws in workspaces()), *stage_files()]


@cache
def tracked_markdown(prefix: str) -> tuple[str, ...]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--", f"{prefix}/*.md"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    untracked = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            f"{prefix}/*.md",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return tuple(sorted(set((out + untracked).split())))


def reference_files() -> list[str]:
    return list(tracked_markdown(REFERENCE_DIR))


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _body_lines(text: str) -> list[tuple[int, str]]:
    """(line index, line) outside fenced code blocks."""
    lines: list[tuple[int, str]] = []
    fence: str | None = None
    for index, line in enumerate(text.splitlines()):
        match = _FENCE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append((index, line))
    return lines


def headings(text: str) -> list[tuple[int, int, str]]:
    """(line index, level, title) for every Markdown heading outside code fences."""
    found = []
    for index, line in _body_lines(text):
        match = _HEADING.match(line)
        if match:
            found.append((index, len(match.group(1)), match.group(2)))
    return found


def section_bytes(path: Path, section: str) -> int | None:
    """Bytes from the named heading to the next heading of the same or higher level."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    found = headings(text)
    wanted = github_slug(section)
    for position, (index, level, title) in enumerate(found):
        if github_slug(title) != wanted:
            continue
        end = next((i for i, lvl, _ in found[position + 1 :] if lvl <= level), len(lines))
        return len("".join(lines[index:end]).encode("utf-8"))
    return None


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def read_first_rows(rel: str) -> list[ReadRow]:
    """Rows of the table under ``## Read first`` (columns Read | Section | When)."""
    text = _text(rel)
    lines = text.splitlines()
    found = headings(text)
    start = next(i for i, level, title in found if level == 2 and title == "Read first")
    end = next((i for i, level, _ in found if i > start and level <= 2), len(lines))
    table = [line for line in lines[start + 1 : end] if line.strip().startswith("|")]
    assert table, f"{rel}: '## Read first' must contain a table with columns Read | Section | When"
    assert _cells(table[0]) == ["Read", "Section", "When"], (
        f"{rel}: the Read first table header must be exactly '| Read | Section | When |', "
        f"found {table[0]!r}"
    )
    rows = []
    for line in table[2:]:
        cells = _cells(line)
        assert len(cells) == 3, f"{rel}: Read first row needs exactly 3 cells: {line!r}"
        link = _LINK.match(cells[0])
        target = None
        if link:
            target = (
                (ROOT / rel).parent.joinpath(link.group(1)).resolve().relative_to(ROOT).as_posix()
            )
        rows.append(ReadRow(cells[0], target, cells[1], cells[2]))
    return rows


# ---------------------------------------------------------------------------------------------
# Workspace layout


def _test_filename_violations() -> list[str]:
    # Two numbered modules predate the naming rule. New fixes belong with their behaviour.
    legacy_names = {
        "tests/unit/test_rdagent_real_proposals_5.py",
        "tests/unit/test_spine_honesty_3.py",
    }
    test_paths = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            ":(glob)**/test_*.py",
            ":(glob)**/*_test.py",
            ":(exclude)tests/holdout/**",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return [
        path
        for path in test_paths
        if path not in legacy_names
        and (ROOT / path).is_file()
        and ("fixups" in Path(path).name or re.search(r"_\d+\.py$", Path(path).name))
    ]


def test_every_workspace_has_a_context_file() -> None:
    missing = [rel for rel in context_files() if not (ROOT / rel).is_file()]
    assert not missing, (
        "These code areas have no CONTEXT.md routing file; copy the shape of an existing one "
        "(for example packages/alpha-core/CONTEXT.md):\n" + "\n".join(missing)
    )

    violations = _test_filename_violations()
    assert not violations, f"fixes go into the behaviour's file: {violations}"


# ---------------------------------------------------------------------------------------------
# Size and shape


def _shape_problems(rel: str, max_lines: int | None, advice: str = "") -> list[str]:
    lines = _text(rel).splitlines()
    problems = []
    if max_lines is not None and len(lines) > max_lines:
        problems.append(
            f"{rel}: {len(lines)} lines; the limit is {max_lines}. {advice.capitalize()}."
        )
    for number, line in enumerate(lines, 1):
        if len(line) > MAX_LINE_CHARS:
            problems.append(
                f"{rel}:{number}: line is {len(line)} characters; wrap it at {MAX_LINE_CHARS}."
            )
    return problems


def _front_matter_problems(rel: str, *, allow_generated: bool) -> list[str]:
    try:
        meta = fs_stale.front_matter(_text(rel))
    except fs_stale.FrontMatterError as exc:
        return [f"{rel}: front matter is malformed ({exc})"]
    if meta is None:
        return [f"{rel}: must start with front matter (--- owner / sources / verified ---)"]
    keys = set(meta)
    problems = []
    if allow_generated and "generated_by" in keys:
        if keys != GENERATED_KEYS:
            problems.append(
                f"{rel}: a generated file declares exactly generated_by and sources, "
                f"found {sorted(keys)}"
            )
    elif keys != LIVING_KEYS:
        problems.append(
            f"{rel}: front matter keys must be exactly owner, sources, verified; "
            f"found {sorted(keys)}"
        )
    owner = meta.get("owner")
    if owner is not None and not (isinstance(owner, str) and _OWNER.match(owner)):
        problems.append(
            f"{rel}: owner must be a short lowercase role phrase such as "
            f"'data layer', not a person; found {owner!r}"
        )
    sources = meta.get("sources")
    if not isinstance(sources, list) or not sources:
        problems.append(f"{rel}: sources must be a non-empty list of globs")
    else:
        problems += [
            f"{rel}: source glob {pattern!r} matches no tracked file; fix or remove it"
            for pattern in sources
            if not fs_stale.tracked_matches(ROOT, pattern)
        ]
    verified = meta.get("verified")
    if "verified" in keys and not (
        isinstance(verified, str) and re.fullmatch(r"[0-9a-f]{16}", verified)
    ):
        problems.append(
            f"{rel}: verified {verified!r} is not a fingerprint of the sources; re-read the "
            f"document against them, then run `uv run python scripts/fs.py verify {rel}`"
        )
    return problems


def _context_line_limit(rel: str) -> int:
    if rel == CONTEXT:
        return ROOT_MAX_LINES
    return STAGE_CONTEXT_MAX_LINES if is_stage_file(rel) else CONTEXT_MAX_LINES


def test_context_files_are_small_and_declare_owner_sources_verified() -> None:
    problems = []
    for rel in context_files():
        if (ROOT / rel).is_file():
            problems += _shape_problems(rel, _context_line_limit(rel), CONTEXT_LINES_ADVICE)
            problems += _front_matter_problems(rel, allow_generated=False)
    assert not problems, "\n".join(problems)


def test_workspace_context_files_stay_within_the_byte_limit() -> None:
    problems = [
        f"{rel}: {size:,} bytes; the limit is {CONTEXT_MAX_BYTES:,}. "
        f"{CONTEXT_LINES_ADVICE.capitalize()}."
        for rel in context_files()
        if rel != CONTEXT
        and not is_stage_file(rel)
        and (ROOT / rel).is_file()
        and (size := (ROOT / rel).stat().st_size) > CONTEXT_MAX_BYTES
    ]
    assert not problems, "\n".join(problems)


def _outside_tables(rel: str) -> list[str]:
    """Body lines of a CONTEXT file that are not headings, blank, front matter or table rows."""
    text = _text(rel)
    body = text.split("\n---\n", 1)[1] if text.startswith("---\n") else text
    return [
        line
        for _, line in _body_lines(body)
        if line.strip() and not line.startswith("#") and not line.lstrip().startswith("|")
    ]


def _bullets(lines: list[str]) -> list[str]:
    """Each bullet joined with its indented continuation lines."""
    bullets: list[str] = []
    for line in lines:
        if line.startswith("- "):
            bullets.append(line)
        elif line.startswith("  ") and bullets:
            bullets[-1] += " " + line.strip()
    return bullets


def test_workspace_context_bodies_route_and_do_not_hold_rules() -> None:
    problems = []
    for ws in workspaces():
        rel = f"{ws}/{CONTEXT}"
        if not (ROOT / rel).is_file():
            continue
        lines = _outside_tables(rel)
        if len(lines) > CONTEXT_BODY_MAX_LINES:
            problems.append(
                f"{rel}: {len(lines)} body lines outside tables; the limit is "
                f"{CONTEXT_BODY_MAX_LINES}. Move rule text to its invariants page."
            )
        problems += [
            f"{rel}: a bullet must hold a command, a path or a link: {bullet[:70]!r}"
            for bullet in _bullets(lines)
            if "`" not in bullet and "](" not in bullet
        ]
    assert not problems, "\n".join(problems)


def test_read_first_tables_are_short_with_short_when_cells() -> None:
    problems = []
    for rel in context_files():
        if rel == CONTEXT or not (ROOT / rel).is_file():
            continue
        rows = read_first_rows(rel)
        if len(rows) > READ_FIRST_MAX_ROWS:
            problems.append(
                f"{rel}: {len(rows)} Read first rows; the limit is {READ_FIRST_MAX_ROWS}"
            )
        problems += [
            f"{rel}: When must be 'always' or at most {WHEN_MAX_CHARS} characters: {row.when!r}"
            for row in rows
            if row.when != "always" and len(row.when) > WHEN_MAX_CHARS
        ]
    assert not problems, "\n".join(problems)


def test_reference_files_are_small_and_declare_owner_sources_verified() -> None:
    files = reference_files()
    assert files, "docs/reference/ has no Markdown files"
    problems = []
    for rel in files:
        generated = "generated_by" in (fs_stale.front_matter(_text(rel)) or {})
        problems += _shape_problems(
            rel, None if generated else REFERENCE_MAX_LINES, REFERENCE_LINES_ADVICE
        )
        problems += _front_matter_problems(rel, allow_generated=True)
    assert not problems, "\n".join(problems)


def test_context_sections_appear_in_order() -> None:
    problems = []
    for rel in context_files():
        if not (ROOT / rel).is_file():
            continue
        required = STAGE_SECTIONS if is_stage_file(rel) else REQUIRED_SECTIONS
        titles = [title for _, level, title in headings(_text(rel)) if level == 2]
        present = [title for title in titles if title in required]
        if present != list(required):
            problems.append(
                f"{rel}: needs the sections {', '.join(required)} once each, "
                f"in that order; found {titles}"
            )
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------------------------
# Read first tables resolve to real files and headings


def test_read_first_rows_resolve_to_existing_files_and_sections() -> None:
    problems = []
    for rel in context_files():
        if not (ROOT / rel).is_file():
            continue
        for row in read_first_rows(rel):
            if row.target is None:
                if rel == CONTEXT and _COMING in row.read and "](" not in row.read:
                    continue
                problems.append(
                    f"{rel}: Read cell must be a relative Markdown link: {row.read!r} "
                    f"(only the root file may list '{_COMING}' rows without a link)"
                )
                continue
            if not (ROOT / row.target).is_file():
                problems.append(f"{rel}: {row.target} does not exist")
                continue
            if row.section != NONE_MARK and github_slug(row.section) not in anchors(
                (ROOT / row.target).resolve()
            ):
                problems.append(
                    f"{rel}: {row.target} has no heading {row.section!r}; use an "
                    f"exact heading from that file or '{NONE_MARK}' for the whole file"
                )
            if not row.when:
                problems.append(f"{rel}: When must be 'always' or a short condition: {row.when!r}")
        problems += broken_links(rel)
    assert not problems, "\n".join(problems)


def _always_bytes(rel: str) -> tuple[int, list[str]]:
    total, problems = 0, []
    for row in read_first_rows(rel):
        if row.when != "always" or row.target is None:
            continue
        path = ROOT / row.target
        if row.section == NONE_MARK:
            total += path.stat().st_size
            continue
        size = section_bytes(path, row.section)
        if size is None:
            problems.append(f"{rel}: always row names a missing section {row.section!r}")
        else:
            total += size
    return total, problems


def _always_set_bytes(ws: str) -> tuple[int, list[str]]:
    """Bytes read for every task in a workspace: identity, rules, root, workspace, always rows."""
    parts = [IDENTITY, f"{RULES_DIR}/{UNSCOPED_RULES[0]}", CONTEXT, f"{ws}/{CONTEXT}"]
    scoped = f"{RULES_DIR}/{Path(ws).name}.md"
    if (ROOT / scoped).is_file():
        parts.insert(2, scoped)
    total = sum((ROOT / part).stat().st_size for part in parts)
    root_always, root_problems = _always_bytes(CONTEXT)
    own, own_problems = _always_bytes(f"{ws}/{CONTEXT}")
    return total + root_always + own, root_problems + own_problems


def test_always_read_budget_per_workspace() -> None:
    problems: list[str] = []
    report = []
    over = []
    for ws in workspaces():
        if not (ROOT / ws / CONTEXT).is_file():
            continue
        total, own_problems = _always_set_bytes(ws)
        problems += own_problems
        report.append(f"{ws}: {total:,} bytes")
        if total > ALWAYS_BUDGET_BYTES:
            over.append(ws)
    assert not problems, "\n".join(problems)
    assert not over, (
        f"The always-read set (CLAUDE.md + the karpathy rule + the workspace rule + root "
        f"CONTEXT.md + workspace CONTEXT.md + every 'always' row) is over "
        f"{ALWAYS_BUDGET_BYTES:,} bytes for {', '.join(over)}. Point 'always' rows at smaller "
        "sections or make them conditional.\n" + "\n".join(report)
    )


# ---------------------------------------------------------------------------------------------
# The root routes to every workspace


def test_root_routes_to_every_workspace() -> None:
    targets = {row.target for row in read_first_rows(CONTEXT)}
    missing = [ws for ws in workspaces() if f"{ws}/{CONTEXT}" not in targets]
    assert not missing, (
        "The root CONTEXT.md routing table (## Read first) has no row linking to these "
        "workspaces' CONTEXT.md:\n" + "\n".join(missing)
    )


# ---------------------------------------------------------------------------------------------
# The staged pipeline (delivery): numbered stages, each routed from <pipeline>/CONTEXT.md


@pytest.mark.parametrize("pipeline", PIPELINES)
def test_stage_folders_are_numbered_and_each_has_a_context_file(pipeline: str) -> None:
    stages_dir = f"{pipeline}/{STAGES}"
    folders = sorted(p for p in (ROOT / stages_dir).iterdir() if p.is_dir())
    assert folders, f"{stages_dir} has no stage folders"
    problems = [
        f"{stages_dir}/{p.name}: name a stage NN-word (for example 03-build)"
        for p in folders
        if not _STAGE_NAME.match(p.name)
    ]
    problems += [f"{rel} is missing" for rel in stage_files(pipeline) if not (ROOT / rel).is_file()]
    numbers = [int(p.name[:2]) for p in folders if _STAGE_NAME.match(p.name)]
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append(
            f"{stages_dir}: stages must be numbered 01, 02, ... without gaps: {numbers}"
        )
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("pipeline", PIPELINES)
def test_pipeline_routing_links_every_stage(pipeline: str) -> None:
    text = _text(f"{pipeline}/{CONTEXT}")
    missing = [rel for rel in stage_files(pipeline) if rel.removeprefix(f"{pipeline}/") not in text]
    assert not missing, f"{pipeline}/{CONTEXT} must link every stage: {missing}"


def test_every_pipeline_is_a_routed_workspace() -> None:
    missing = [name for name in PIPELINES if name not in EXTRA_WORKSPACES]
    assert not missing, (
        f"add these pipelines to EXTRA_WORKSPACES so the root routes them: {missing}"
    )


# ---------------------------------------------------------------------------------------------
# Outputs: task folders under docs/work/ (only while their pull request is open)


def _task_folders() -> list[Path]:
    root = ROOT / WORK_DIR
    return sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


def test_task_folders_hold_a_plan_and_only_stage_files() -> None:
    folders = _task_folders()
    problems = []
    for folder in folders:
        rel = folder.relative_to(ROOT).as_posix()
        if not _TASK_NAME.match(folder.name):
            problems.append(f"{rel}: name a task folder yyyy-mm-dd-<lowercase-slug>")
        if not (folder / TASK_PLAN).is_file() and not (folder / "brief.md").is_file():
            problems.append(f"{rel}: has no {TASK_PLAN} or brief.md; commit it with one of them")
        allowed = STAGE_OUTPUTS | BUILD_OUTPUTS
        problems += [
            f"{rel}/{child.name}: not a task file; allowed: {', '.join(sorted(allowed))}"
            for child in sorted(folder.iterdir())
            if child.name not in allowed
        ]
    assert not problems, "\n".join(problems)


def test_work_folder_holds_only_task_folders() -> None:
    root = ROOT / WORK_DIR
    files = sorted(root.iterdir()) if root.is_dir() else []
    stray = [p.relative_to(ROOT).as_posix() for p in files if p.is_file() and p.name != CONTEXT]
    assert not stray, f"{WORK_DIR} holds only task folders; move: {stray}"


# ---------------------------------------------------------------------------------------------
# One home per fact


def _paragraphs(text: str) -> list[str]:
    body = text
    if text.startswith("---\n"):
        body = text.split("\n---\n", 1)[1] if "\n---\n" in text else ""
    blocks, current = [], []
    for line in body.splitlines():
        if line.strip():
            current.append(" ".join(line.split()))
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return ["\n".join(block) for block in blocks if len(block) >= 3]


def test_no_paragraph_is_repeated_across_files() -> None:
    seen: dict[str, list[str]] = defaultdict(list)
    for rel in [*context_files(), *reference_files()]:
        if (ROOT / rel).is_file():
            for paragraph in set(_paragraphs(_text(rel))):
                seen[paragraph].append(rel)
    repeated = [
        f"{', '.join(files)}:\n  {paragraph.splitlines()[0][:100]}..."
        for paragraph, files in seen.items()
        if len(files) > 1
    ]
    assert not repeated, (
        "A paragraph of three or more lines appears in more than one file. Keep it in one home "
        "and link to it from the others:\n" + "\n".join(repeated)
    )


# ---------------------------------------------------------------------------------------------
# The checker itself


def test_section_bytes_stops_at_the_next_heading_of_same_or_higher_level(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "# T\n## A\nx\n### A1\ny\n```\n## not a heading\n```\n## B\nz\n", encoding="utf-8"
    )
    assert section_bytes(doc, "A") == len("## A\nx\n### A1\ny\n```\n## not a heading\n```\n")
    assert section_bytes(doc, "B") == len("## B\nz\n")
    assert section_bytes(doc, "Missing") is None


@pytest.mark.parametrize(
    ("owner", "ok"),
    [("data layer", True), ("command line research", True), ("Jane Smith", False), ("x", False)],
)
def test_owner_is_a_role_phrase(owner: str, ok: bool) -> None:
    assert bool(_OWNER.match(owner)) is ok


# ---------------------------------------------------------------------------------------------
# Layer 0: CLAUDE.md and AGENTS.md


def _links(rel: str) -> list[str]:
    return re.findall(r"\]\(([^)\s]+)\)", _text(rel))


@pytest.mark.parametrize(
    ("rel", "max_lines"), [(IDENTITY, IDENTITY_MAX_LINES), (AGENT_POINTER, AGENT_POINTER_MAX_LINES)]
)
def test_identity_files_are_small_and_their_links_resolve(rel: str, max_lines: int) -> None:
    problems = _shape_problems(rel, max_lines) + broken_links(rel)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("rel", [IDENTITY, AGENT_POINTER])
def test_identity_files_send_the_reader_to_the_root_context(rel: str) -> None:
    targets = {target.split("#", 1)[0] for target in _links(rel)}
    assert CONTEXT in targets, f"{rel} must link to the root {CONTEXT} (the routing table)"


def test_research_integrity_rules_stay_stated_in_their_home() -> None:
    """The rules CLAUDE.md summarises must not silently disappear from their one home."""
    home = "docs/reference/invariants/research-integrity.md"
    text = _text(home)
    sections = {github_slug(title) for _, _, title in headings(text)}
    for slug in (
        "point-in-time-reads",
        "decide-at-close-fill-at-next-open",
        "invalid-data-fails-loud",
        "immutable-hash-bound-artefacts",
        "deterministic-seeds-and-identity",
        "research-before-strategy",
        "owner-authority",
        "no-live-capital",
        "protected-and-hidden-tests",
    ):
        assert slug in sections, f"{home}: section #{slug} is gone; CLAUDE.md links to it"
    for phrase in (
        "as_of",
        "future-poison",
        "t+1",
        "not proof of an edge",
        "explicit local confirmation",
    ):
        assert phrase in text, f"{home}: the rule stated with {phrase!r} is gone"


# ---------------------------------------------------------------------------------------------
# Loading: workspace CLAUDE.md imports and thin rule pointers


def test_every_workspace_loads_its_context_through_a_one_line_claude_md() -> None:
    problems = []
    for ws in workspaces():
        loader = ROOT / ws / IDENTITY
        if not loader.is_file() or loader.read_text(encoding="utf-8") != WORKSPACE_LOADER:
            problems.append(f"{ws}/{IDENTITY} must contain exactly {WORKSPACE_LOADER!r}")
    assert not problems, "\n".join(problems)


def _rule_globs(text: str) -> list[str] | None:
    if not text.startswith("---\n"):
        return None
    head = text.split("---\n", 2)[1]
    return [m.group(1) for m in re.finditer(r'^\s*-\s*"([^"]+)"\s*$', head, re.M)]


def rule_files() -> list[str]:
    return sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / RULES_DIR).glob("*.md"))


@pytest.mark.parametrize("rel", rule_files(), ids=lambda rel: Path(rel).name)
def test_rule_files_are_thin_pointers_with_live_globs(rel: str) -> None:
    text = _text(rel)
    problems = _shape_problems(rel, RULE_MAX_LINES) + broken_links(rel)
    globs = _rule_globs(text)
    if Path(rel).name in UNSCOPED_RULES:
        assert globs is None, f"{rel} is the always-loaded rule and has no paths: front matter"
    else:
        if not globs:
            problems.append(f"{rel}: a scoped rule declares paths: globs")
        problems += [
            f"{rel}: glob {pattern!r} matches no tracked file"
            for pattern in globs or []
            if not fs_stale.tracked_matches(ROOT, pattern)
        ]
        targets = [target.split("#", 1)[0] for target in _links(rel)]
        if not any(t.endswith(CONTEXT) or "/reference/invariants/" in t for t in targets):
            problems.append(f"{rel}: must link to a workspace CONTEXT.md or an invariants file")
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------------------------
# Model routing: one home for who builds and reviews, kept in step with scripts/handoff.py

ROUTING = "docs/reference/model-routing.md"


def test_model_routing_has_its_home_and_matches_the_handoff_tool() -> None:
    import handoff

    home = "docs/README.md"  # the One home per fact table moved here from the root
    assert f"](reference/{Path(ROUTING).name})" in _text(home), (
        f"{home}: add {ROUTING} to One home per fact"
    )
    text = _text(ROUTING)
    problems = [
        f"{ROUTING}: class {name!r} must name model {p.model!r} and effort {p.effort!r}"
        for name, p in handoff.PROFILES.items()
        if not re.search(rf"`{name}`.*`{re.escape(p.model)}`, `{p.effort}`", text)
    ]
    assert handoff.RECORD_NAME == BUILD_RECORD, "scripts/handoff.py writes the task's build record"
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------------------------
# The project layer: what each part is for, kept apart from how to change it
#
# ``docs/reference/project/`` is Layer 3 reference material about purpose (the paper's "configure
# the factory": identity and decisions set once, stable across tasks). ``overview.md`` routes to
# one component file per major part; each has fixed sections and claims, in its "Where it lives"
# section, the workspaces and the capability ids (``docs/roadmap/capabilities.toml``) it owns.
# Every capability and every workspace is claimed exactly once, every workspace's Read first table
# links up to its component, and ``owner-decisions.md`` is the one home for the owner's intent.

PROJECT_DIR = "docs/reference/project"
COMPONENTS_DIR = f"{PROJECT_DIR}/components"
OVERVIEW = f"{PROJECT_DIR}/overview.md"
OWNER_DECISIONS = f"{PROJECT_DIR}/owner-decisions.md"
CAPABILITY_MAP = "docs/roadmap/capabilities.toml"
COMPONENT_SECTIONS = (
    "Why it exists",
    "Its job in the research loop",
    "Intended design",
    "What is real today",
    "Where it lives",
    "Decisions and open questions",
    "Never",
)
_CLAIM = re.compile(r"^- \*\*(Workspaces|Capabilities):\*\*\s*(.*)$")
_DATED = re.compile(r"^\d{4}-\d{2}-\d{2} \S")
FIRST_STAGE = f"workflow/{STAGES}/01-shape/{CONTEXT}"


def component_files() -> list[str]:
    return sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / COMPONENTS_DIR).glob("*.md"))


def _section_lines(rel: str, title: str) -> list[str]:
    text = _text(rel)
    lines = text.splitlines()
    found = headings(text)
    start = next((i for i, level, t in found if level == 2 and t == title), None)
    if start is None:
        return []
    end = next((i for i, level, _ in found if i > start and level <= 2), len(lines))
    return lines[start + 1 : end]


def component_claims(rel: str) -> dict[str, list[str]]:
    """``{"Workspaces": [...], "Capabilities": [...]}`` from the "Where it lives" bullets.

    A bullet may wrap onto indented lines; a value starting with "none" claims nothing.
    """
    claims: dict[str, list[str]] = {}
    key, parts = None, []
    for line in [*_section_lines(rel, "Where it lives"), "- end"]:
        if line.startswith("- ") or not line.strip():
            if key is not None:
                value = " ".join(parts).strip()
                claims[key] = (
                    [] if value.lower().startswith("none") else re.findall(r"`([^`]+)`", value)
                )
                key, parts = None, []
            match = _CLAIM.match(line)
            if match:
                key, parts = match.group(1), [match.group(2)]
        elif key is not None:
            parts.append(line.strip())
    return claims


def _claim_owners(kind: str) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = defaultdict(list)
    for rel in component_files():
        for item in component_claims(rel).get(kind, []):
            owners[item].append(rel)
    return owners


def test_component_files_have_the_fixed_sections_and_claim_lines() -> None:
    files = component_files()
    assert files, f"{COMPONENTS_DIR} has no component files"
    problems = []
    for rel in files:
        titles = [title for _, level, title in headings(_text(rel)) if level == 2]
        if titles != list(COMPONENT_SECTIONS):
            problems.append(
                f"{rel}: needs exactly the sections {', '.join(COMPONENT_SECTIONS)}, in that "
                f"order; found {titles}"
            )
        claims = component_claims(rel)
        problems += [
            f"{rel}: 'Where it lives' needs a '- **{kind}:**' line (backticked ids, or 'none')"
            for kind in ("Workspaces", "Capabilities")
            if kind not in claims
        ]
        if OWNER_DECISIONS.rsplit("/", 1)[1] not in "".join(_links(rel)):
            problems.append(f"{rel}: link the owner decisions log ({OWNER_DECISIONS})")
    assert not problems, "\n".join(problems)


def test_every_capability_is_claimed_by_exactly_one_component() -> None:
    import tomllib

    ids = [c["id"] for c in tomllib.loads(_text(CAPABILITY_MAP))["capability"]]
    owners = _claim_owners("Capabilities")
    problems = [
        f"capability {cid!r} ({CAPABILITY_MAP}) is claimed by no component: add it to the "
        f"'Capabilities' line of the file in {COMPONENTS_DIR}/ for the part it belongs to"
        for cid in ids
        if cid not in owners
    ]
    problems += [
        f"capability {cid!r} is claimed by more than one component: {', '.join(files)}"
        for cid, files in owners.items()
        if len(files) > 1
    ]
    problems += [
        f"{', '.join(files)}: claims {cid!r}, which is not a capability id in {CAPABILITY_MAP}"
        for cid, files in owners.items()
        if cid not in ids
    ]
    assert not problems, "\n".join(problems)


def test_every_workspace_is_claimed_once_and_links_up_to_its_component() -> None:
    owners = _claim_owners("Workspaces")
    known = workspaces()
    problems = [
        f"{', '.join(files)}: claims {ws!r}, which is not a workspace"
        for ws, files in owners.items()
        if ws not in known
    ]
    for ws in known:
        files = owners.get(ws, [])
        if len(files) != 1:
            problems.append(
                f"workspace {ws} must be claimed by exactly one component file in "
                f"{COMPONENTS_DIR}/ ('Workspaces' line); found {files or 'none'}"
            )
            continue
        targets = {row.target for row in read_first_rows(f"{ws}/{CONTEXT}")}
        if files[0] not in targets:
            problems.append(
                f"{ws}/{CONTEXT}: add a Read first row linking up to {files[0]} (what this part "
                "is for, and whether to keep, change or remove it)"
            )
    assert not problems, "\n".join(problems)


def test_the_project_layer_is_routed_from_the_root_and_the_shape_stage() -> None:
    problems = []
    overview_links = {
        (ROOT / OVERVIEW).parent.joinpath(t.split("#", 1)[0]).resolve().relative_to(ROOT).as_posix()
        for t in _links(OVERVIEW)
    }
    problems += [
        f"{OVERVIEW}: list and link {rel}" for rel in component_files() if rel not in overview_links
    ]
    if OVERVIEW not in {row.target for row in read_first_rows(CONTEXT)}:
        problems.append(f"root {CONTEXT}: add a Read first row for {OVERVIEW} (what a part is for)")
    if not any(
        (row.target or "").startswith(PROJECT_DIR + "/") for row in read_first_rows(FIRST_STAGE)
    ):
        problems.append(f"{FIRST_STAGE}: add a Read first row for the component file of the part")
    if not any(OVERVIEW.rsplit("/", 1)[1] in t for t in _links(IDENTITY)):
        problems.append(f"{IDENTITY}: name the project layer ({OVERVIEW})")
    assert not problems, "\n".join(problems)


def owner_decision_volumes() -> list[str]:
    """The log and its continuation volumes (``owner-decisions-2.md``, ...)."""
    stem = OWNER_DECISIONS.removesuffix(".md")
    more = sorted(p.relative_to(ROOT).as_posix() for p in ROOT.glob(f"{stem}-*.md"))
    return [OWNER_DECISIONS, *more]


@pytest.mark.parametrize("volume", owner_decision_volumes())
def test_owner_decisions_are_dated_quoted_and_say_what_they_govern(volume: str) -> None:
    lines = _section_lines(volume, "Entries")
    entries: list[tuple[str, list[str]]] = []
    for line in lines:
        if line.startswith("### "):
            entries.append((line[4:], []))
        elif entries:
            entries[-1][1].append(line)
    assert entries, f"{volume}: '## Entries' has no '### yyyy-mm-dd <title>' entries"
    problems = []
    for title, body in entries:
        text = "\n".join(body)
        if not _DATED.match(title):
            problems.append(f"{volume}: entry {title!r} must start with its date yyyy-mm-dd")
        quoted = '"' in text or "exact words not recorded" in text
        if "**Said" not in text or not quoted:
            problems.append(
                f"{volume}: entry {title!r} needs a '**Said' line quoting the owner, "
                "or saying 'exact words not recorded'"
            )
        if "**Governs:**" not in text:
            problems.append(f"{volume}: entry {title!r} needs a '**Governs:**' line")
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------------------------
# Routing-only root, invariants router, measurement page off the route

ROOT_MAX_BYTES = 2_200
ROOT_MAX_LINES = 40
ROOT_SECTIONS = ("Purpose", "Read first", "How to change it", "Outputs")
INVARIANTS_DIR = "docs/reference/invariants"
INVARIANTS_ROUTER = f"{INVARIANTS_DIR}/README.md"
INVARIANTS_ROUTER_MAX_LINES = 54
MEASUREMENT_PAGE = "file-system-measurement.md"


def test_root_is_routing_only() -> None:
    path = ROOT / CONTEXT
    size = path.stat().st_size
    lines = len(_text(CONTEXT).splitlines())
    titles = [title for _, level, title in headings(_text(CONTEXT)) if level == 2]
    problems = []
    if size > ROOT_MAX_BYTES:
        problems.append(f"{size} bytes; the limit is {ROOT_MAX_BYTES}")
    if lines > ROOT_MAX_LINES:
        problems.append(f"{lines} lines; the limit is {ROOT_MAX_LINES}")
    if titles != list(ROOT_SECTIONS):
        problems.append(f"level-2 sections must be exactly {list(ROOT_SECTIONS)}; found {titles}")
    assert not problems, (
        f"root {CONTEXT} is routing only: " + "; ".join(problems) + ". Move facts to "
        "docs/README.md (One home per fact) or the owning workspace file."
    )


def test_invariants_router_lists_every_invariants_file() -> None:
    router = _text(INVARIANTS_ROUTER)
    lines = len(router.splitlines())
    assert lines <= INVARIANTS_ROUTER_MAX_LINES, (
        f"{INVARIANTS_ROUTER}: {lines} lines; the limit is {INVARIANTS_ROUTER_MAX_LINES}"
    )
    files = sorted(p.name for p in (ROOT / INVARIANTS_DIR).glob("*.md") if p.name != "README.md")
    missing = [name for name in files if f"[{name}]({name})" not in router]
    assert not missing, f"{INVARIANTS_ROUTER} has no row for: {missing}. Add one row per file."


def test_measurement_page_is_not_routed() -> None:
    linking = [
        rel for rel in (IDENTITY, AGENT_POINTER, *context_files()) if MEASUREMENT_PAGE in _text(rel)
    ]
    assert not linking, f"These files route to {MEASUREMENT_PAGE}; remove the link: {linking}"


# ---------------------------------------------------------------------------------------------
# Section-level always rows and small invariant sections

INVARIANT_SECTION_MAX_BYTES = 4_096
# Sections written before the limit. Each ceiling is the section's size when the limit began and may
# only go down. Split the section by sub-headings, then delete its entry.
INVARIANT_SECTION_CEILINGS: dict[tuple[str, str], int] = {
    ("cli-results-check.md", "Draft checks and run comparisons"): 5_156,
    ("cli-investigation-tools.md", "Rules"): 4_103,
}


def test_always_rows_per_workspace_stay_small_and_name_only_small_whole_files() -> None:
    problems: list[str] = []
    for ws in workspaces():
        rel = f"{ws}/{CONTEXT}"
        if not (ROOT / rel).is_file():
            continue
        total, section_problems = _always_bytes(rel)
        problems += section_problems
        if total > ALWAYS_ROWS_MAX_BYTES:
            problems.append(
                f"{rel}: the always rows total {total:,} bytes; the limit is "
                f"{ALWAYS_ROWS_MAX_BYTES:,}. Point rows at sections or make them conditional."
            )
        for row in read_first_rows(rel):
            if row.when != "always" or row.target is None or row.section != NONE_MARK:
                continue
            size = (ROOT / row.target).stat().st_size
            if size > ALWAYS_WHOLE_FILE_MAX_BYTES:
                problems.append(
                    f"{rel}: the always row for {row.target} names the whole file ({size:,} bytes; "
                    f"the limit is {ALWAYS_WHOLE_FILE_MAX_BYTES:,}). Name its sections instead."
                )
    assert not problems, "\n".join(problems)


def _invariant_section_sizes() -> dict[tuple[str, str], int]:
    sizes: dict[tuple[str, str], int] = {}
    for path in sorted((ROOT / INVARIANTS_DIR).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        found = headings(text)
        for position, (index, level, title) in enumerate(found):
            if level != 2:
                continue
            end = next((i for i, lvl, _ in found[position + 1 :] if lvl <= 2), len(lines))
            sizes[(path.name, title)] = len("".join(lines[index:end]).encode("utf-8"))
    return sizes


def test_invariant_sections_are_small_enough_for_a_row_to_name() -> None:
    sizes = _invariant_section_sizes()
    problems = []
    for (name, title), size in sizes.items():
        limit = INVARIANT_SECTION_CEILINGS.get((name, title), INVARIANT_SECTION_MAX_BYTES)
        if size > limit:
            problems.append(
                f"{INVARIANTS_DIR}/{name} § {title}: {size:,} bytes; the limit is {limit:,}. "
                "Add sub-headings so a Read first row can name a part."
            )
    for (name, title), ceiling in INVARIANT_SECTION_CEILINGS.items():
        found = sizes.get((name, title))
        if found is None:
            problems.append(f"ceiling for {name} § {title} names a missing section; remove it")
        elif found <= INVARIANT_SECTION_MAX_BYTES:
            problems.append(f"{name} § {title} is {found:,} bytes; remove its ceiling")
        elif found < ceiling:
            problems.append(f"{name} § {title} is {found:,} bytes; lower its ceiling to {found:,}")
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------------------------
# Cramming: a line cap is a split trigger, not a target

CRAM_LOW = MAX_LINE_CHARS - 10
CRAM_MAX_SHARE = 0.20
CRAM_MIN_PROSE_LINES = 10
# Files written before this check. Each ceiling is the file's count of prose lines of 150 to 160
# characters when the check began and may only go down. Split the file by heading (or summarise and
# link), then delete its entry.
CRAM_CEILINGS: dict[str, int] = {
    "docs/reference/invariants/cli-runs.md": 51,
    "docs/reference/invariants/cli-setups.md": 9,
    "docs/reference/invariants/data-crypto.md": 12,
    "docs/reference/invariants/web-frontend.md": 31,
    "docs/reference/invariants/web-run-detail.md": 18,
    "docs/reference/project/file-system-measurement.md": 14,
}


def prose_lines(text: str) -> list[str]:
    """Lines of prose: no front matter, code, headings, tables, link definitions or blank lines."""
    if text.startswith("---\n") and "\n---\n" in text:
        text = text.split("\n---\n", 1)[1]
    found = []
    for _, line in _body_lines(text):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "|", "http")):
            continue
        if re.match(r"^\[[^\]]+\]:", stripped):
            continue
        found.append(line)
    return found


def cram_count(text: str) -> tuple[int, int]:
    """(prose lines of 150 to 160 characters, prose lines)."""
    prose = prose_lines(text)
    return sum(CRAM_LOW <= len(line) <= MAX_LINE_CHARS for line in prose), len(prose)


def _crammed_files() -> dict[str, int]:
    crammed: dict[str, int] = {}
    for rel in reference_files():
        text = _text(rel)
        if "generated_by" in (fs_stale.front_matter(text) or {}):
            continue
        near_cap, total = cram_count(text)
        if total >= CRAM_MIN_PROSE_LINES and near_cap > CRAM_MAX_SHARE * total:
            crammed[rel] = near_cap
    return crammed


def test_cram_counts_only_prose_lines_near_the_cap() -> None:
    near = "x" * 155
    text = f"---\nowner: a\n---\n# {near}\n\n| {near} |\n```\n{near}\n```\n{near}\n- short\n"
    assert cram_count(text) == (1, 2)
    assert prose_lines("[ref]:\n  https://example.org/" + "a" * 150) == []


def test_reference_files_are_not_crammed_under_the_line_cap() -> None:
    crammed = _crammed_files()
    problems = [
        f"{rel}: {count} prose lines are 150 to 160 characters long; the limit is "
        f"{CRAM_MAX_SHARE:.0%}. Split the file by heading into a sibling file, or summarise and "
        "link; never drop words to fit."
        for rel, count in crammed.items()
        if count > CRAM_CEILINGS.get(rel, -1)
    ]
    for rel, ceiling in CRAM_CEILINGS.items():
        found = crammed.get(rel)
        if found is None:
            problems.append(f"{rel} is no longer crammed (or is gone); remove its ceiling")
        elif found < ceiling:
            problems.append(f"{rel} has {found} crammed lines; lower its ceiling to {found}")
    assert not problems, "\n".join(problems)


# These project pages keep a plain summary; builder detail lives in the rule pages.
COMPONENT_SIZE_LIMITS: dict[str, tuple[int, int]] = {  # lines, bytes
    "rd-agent.md": (100, 7_000),
    "data-layer.md": (112, 7_200),
    "toolbox.md": (100, 7_000),
}
TOOLBOX_REAL_TODAY_MAX_BYTES = 1_000


def test_the_long_component_pages_stay_summaries() -> None:
    problems = []
    for name, (max_lines, max_bytes) in COMPONENT_SIZE_LIMITS.items():
        rel = f"{COMPONENTS_DIR}/{name}"
        text = _text(rel)
        lines, size = len(text.splitlines()), len(text.encode("utf-8"))
        if lines > max_lines or size > max_bytes:
            problems.append(
                f"{rel}: {lines} lines, {size:,} bytes; the limits are {max_lines} and "
                f"{max_bytes:,}. Move builder detail to the rule page and link to it."
            )
    real_today = section_bytes(ROOT / COMPONENTS_DIR / "toolbox.md", "What is real today")
    if real_today is None or real_today > TOOLBOX_REAL_TODAY_MAX_BYTES:
        problems.append(
            f"toolbox.md § What is real today is {real_today} bytes; the limit is "
            f"{TOOLBOX_REAL_TODAY_MAX_BYTES:,}. Keep a summary; the list lives in cli-toolbox.md."
        )
    assert not problems, "\n".join(problems)


ROUTED_PAGES = (
    "docs/reference/project/reserved-period.md",
    "docs/reference/project/decisions-by-topic.md",
    "docs/reference/project/components/setup-lab.md",
    "docs/reference/project/components/toolbox.md",
    "docs/reference/project/components/monte-carlo.md",
    "research/tools/data-health.md",
)


def _two_hop_targets() -> set[str]:
    """Pages a root row names, and the pages those link to."""
    seen = {r.target for r in read_first_rows(CONTEXT) if r.target}
    found = set(seen)
    for page in seen:
        try:
            links = [r.target for r in read_first_rows(page) if r.target]
        except StopIteration:
            links = [
                (ROOT / page)
                .parent.joinpath(t.split("#", 1)[0])
                .resolve()
                .relative_to(ROOT)
                .as_posix()
                for t in _links(page)
                if not t.startswith(("http", "#"))
            ]
        found.update(links)
    return found


@pytest.mark.parametrize("rel", ROUTED_PAGES)
def test_each_routed_page_is_two_hops_from_the_root(rel: str) -> None:
    assert rel in _two_hop_targets(), f"{rel}: link it from a root row's page (at most two hops)"
