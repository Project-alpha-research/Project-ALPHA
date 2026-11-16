"""The file system carries every part's purpose, reasoning, plan and place, and loses no plan.

The owner's test (2026-11-14, ``owner-decisions.md`` "What the file system is for"): for any part,
a newcomer learns from the documents alone what it is for, why, what is planned and where it
lives. ``test_filesystem_contract.py`` fixes the shape of each document; this module checks the
links between them that let a plan or a feature silently fall out:

* every component page states its purpose (an opening paragraph), its reasoning (its "Why it
  exists" section links a decision record or an owner decision), its plan (a ``- **Plan:**``
  line in "Where it lives" linking the roadmap) and its place (the claim lines);
* every capability in ``docs/roadmap/capabilities.toml`` is traced to a checklist row in
  ``docs/roadmap/capability-trace.md``, every row named there exists word for word, and every
  Working row is traced or listed as not a workflow;
* every registered ``alpha`` command group or command is claimed by a capability's entry point;
* every backlog note has its status, size and the three required sections.
"""

from __future__ import annotations

import re
import tomllib

from tests.unit.test_filesystem_contract import (
    CAPABILITY_MAP,
    ROOT,
    _section_lines,
    _text,
    component_files,
    headings,
)

CHECKLIST = (
    "docs/roadmap/production-scope.md",
    "docs/roadmap/production-scope-2.md",
    "docs/roadmap/production-scope-3.md",
)
TRACE = "docs/roadmap/capability-trace.md"
CLI_MAIN = "apps/alpha-cli/src/alpha_cli/main.py"
BACKLOG_DIR = "docs/roadmap/backlog"
BACKLOG_SECTIONS = ("Problem / why", 'What "done" looks like', "Dependencies")
_REASONING = re.compile(r"\]\([^)]*(adr/\d{4}-|owner-decisions[-\d]*\.md)")
_ROADMAP_LINK = re.compile(r"\]\([^)]*roadmap/[^)]+\)")
_STAGE = re.compile(r"^## \d+\. ")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def checklist_rows() -> dict[str, str]:
    """``{first cell: state}`` for every row of every stage table of the checklist."""
    rows: dict[str, str] = {}
    for rel in CHECKLIST:
        in_stage = in_table = False
        for line in _text(rel).splitlines():
            if line.startswith("## "):
                in_stage, in_table = bool(_STAGE.match(line)), False
            elif in_stage and line.startswith("| Capability | State"):
                in_table = True
            elif in_table and line.startswith("|") and not line.startswith("|---"):
                cells = _cells(line)
                rows[cells[0]] = cells[1]
            elif not line.startswith("|"):
                in_table = False
    return rows


def _trace_table(title: str) -> list[list[str]]:
    lines = [line for line in _section_lines(TRACE, title) if line.startswith("|")]
    return [_cells(line) for line in lines[2:]]


def test_component_pages_state_purpose_reasoning_plan_and_place() -> None:
    problems = []
    for rel in component_files():
        text = _text(rel)
        first = next(i for i, level, _ in headings(text) if level == 2)
        lines = text.splitlines()
        title = next(i for i, line in enumerate(lines) if line.startswith("# "))
        if not any(line.strip() for line in lines[title + 1 : first]):
            problems.append(f"{rel}: say what the part is, in a paragraph under the title")
        why = "\n".join(_section_lines(rel, "Why it exists"))
        if not why.strip() or not _REASONING.search(why):
            problems.append(
                f"{rel}: 'Why it exists' must give the reason and link the decision record "
                "(docs/adr/) or owner decision it rests on"
            )
        where = _section_lines(rel, "Where it lives")
        plan = [i for i, line in enumerate(where) if line.startswith("- **Plan:**")]
        block = ""
        if plan:
            end = next(
                (i for i in range(plan[0] + 1, len(where)) if not where[i].startswith("  ")),
                len(where),
            )
            block = " ".join(where[plan[0] : end])
        if not _ROADMAP_LINK.search(block):
            problems.append(
                f"{rel}: 'Where it lives' needs a '- **Plan:**' line linking the checklist rows "
                "(docs/roadmap/production-scope*.md) or backlog notes that plan this part"
            )
    assert not problems, "\n".join(problems)


def test_capabilities_and_checklist_rows_are_traced_both_ways() -> None:
    ids = [c["id"] for c in tomllib.loads(_text(CAPABILITY_MAP))["capability"]]
    rows = checklist_rows()
    traced = _trace_table("Capability to row")
    not_workflows = _trace_table("Working rows that are not a workflow")
    traced_ids = {cells[0].strip("`") for cells in traced}
    named = {cells[1] for cells in traced} | {cells[0] for cells in not_workflows}
    problems = [
        f"capability {cid!r} ({CAPABILITY_MAP}) is not in {TRACE}: add a row naming the "
        "checklist row it serves"
        for cid in ids
        if cid not in traced_ids
    ]
    problems += [
        f"{TRACE}: {cid!r} is not a capability id in {CAPABILITY_MAP}"
        for cid in sorted(traced_ids - set(ids))
    ]
    problems += [
        f"{TRACE}: no checklist row reads exactly {row!r}; copy its first cell"
        for row in sorted(named - set(rows))
    ]
    problems += [
        f"checklist row {row!r} is Working but in neither table of {TRACE}"
        for row, state in rows.items()
        if state == "Working" and row not in named
    ]
    assert not problems, "\n".join(problems)


def test_every_alpha_command_is_claimed_by_a_capability() -> None:
    registered = set(re.findall(r'^\s*\("([a-z-]+)", "alpha_cli\.', _text(CLI_MAIN), re.M))
    claimed = {
        entry.split()[2]
        for cap in tomllib.loads(_text(CAPABILITY_MAP))["capability"]
        for entry in cap["entry_points"]
        if entry.startswith("cli: alpha ")
    }
    missing = sorted(registered - claimed)
    assert not missing, (
        f"these `alpha` commands are in {CLI_MAIN} but no capability's entry_points in "
        f"{CAPABILITY_MAP} names them: {missing}; add 'cli: alpha <command> ...' to the "
        "capability they serve, or a new capability"
    )


def test_every_backlog_note_has_status_size_and_sections() -> None:
    problems = []
    for path in sorted((ROOT / BACKLOG_DIR).glob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        head = "\n".join(text.splitlines()[:8])
        if not re.search(r"^\*\*Status:\*\* (Idea|Scoped)\b", head, re.M):
            problems.append(f"{rel}: '**Status:** Idea|Scoped' within the first 8 lines")
        if not re.search(r"^\*\*Rough size:\*\* (S|M|L|XL)\b", head, re.M):
            problems.append(f"{rel}: '**Rough size:** S|M|L|XL' within the first 8 lines")
        titles = [title for _, level, title in headings(text) if level == 2]
        problems += [
            f"{rel}: needs a '## {section}' section (the purpose and reasoning, the finish line, "
            "what it waits on)"
            for section in BACKLOG_SECTIONS
            if section not in titles
        ]
    assert not problems, "\n".join(problems)
