"""The file system carries every part's purpose, reasoning, plan and place, and loses no plan.

The owner's test (2026-11-14, ``owner-decisions.md`` "What the file system is for"): for any part,
a newcomer learns from the documents alone what it is for, why, what is planned and where it
lives. ``test_filesystem_contract.py`` fixes the shape of each document; this module checks the
links between them that let a plan or a feature silently fall out:

* every component page states its purpose (an opening paragraph), its reasoning (its "Why it
  exists" section links a decision record or an owner decision), its plan (a ``- **Plan:**``
  line in "Where it lives" linking the roadmap) and its place (the claim lines);
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

CLI_MAIN = "apps/alpha-cli/src/alpha_cli/main.py"
BACKLOG_DIR = "docs/roadmap/backlog"
BACKLOG_SECTIONS = ("Problem / why", 'What "done" looks like', "Dependencies")
_REASONING = re.compile(r"\]\([^)]*(adr/\d{4}-|owner-decisions[-\d]*\.md)")
_ROADMAP_LINK = re.compile(r"\]\([^)]*roadmap/[^)]+\)")


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
