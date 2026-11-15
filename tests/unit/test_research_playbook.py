"""The research instructions cannot drift from the tool they describe.

The playbook (``research/PLAYBOOK.md``), the tool cards (``research/tools/``) and the six research
skills (``.agents/skills/<name>/SKILL.md``) are prose an AI follows. This test keeps that prose
honest mechanically: the files exist and stay small; every ``alpha ...`` command and ``--option``
they name is registered in the CLI; every metric they cite is a stored metric; and every flag,
audit check, label, error code and JSON field they name in a code span occurs in the program.
Wording is reviewed in the pull request, not pinned here.
"""

from __future__ import annotations

import re
import shlex
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import typer

from alpha_cli.spine import diagnostics
from alpha_cli.spine.audit import audit
from alpha_cli.spine.facts import METRICS

ROOT = Path(__file__).parents[2]
PLAYBOOK = "research/PLAYBOOK.md"
ROUTING = "research/CONTEXT.md"
TOOLS_DIR = "research/tools"
TOOLS_INDEX = f"{TOOLS_DIR}/README.md"
LESSONS_INDEX = "research/lessons/README.md"
SKILLS = (
    "test-idea",
    "review-result",
    "investigate-surprise",
    "report-to-owner",
    "answer-from-records",
    "record-lesson",
)
PLAYBOOK_MAX_LINES = 120
CARD_MAX_LINES = 40
SKILL_BODY_MAX_LINES = 40
INDEX_MAX_LINES = 60
MAX_LINE_CHARS = 160
SYMPTOMS = (
    "looks too good",
    "big drawdown in a short period",
    "works in some years only",
    "few trades",
    "profit from a handful of trades",
    "fragile to costs",
    "need the macro picture",
)
PLANNED = ("regime detection", "attribution", "change-point detection", "capacity")
CLI_SRC = ROOT / "apps/alpha-cli/src/alpha_cli"
# Strict vocabulary (playbook, routing, skills): the rule-test spine and its three commands.
SPINE_SOURCES = (*sorted((CLI_SRC / "spine").glob("*.py")), CLI_SRC / "results_cmds.py")
SPINE_SOURCES = (*SPINE_SOURCES, CLI_SRC / "test_cmds.py")
# Tool cards and the routing file also describe older commands: names from the wider program.
WIDE_SOURCES = (CLI_SRC, ROOT / "packages/alpha-validation/src", ROOT / "packages/alpha-core/src")

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_SPAN = re.compile(r"`([^`\n]+)`")
_COMMAND = re.compile(r"^(?:\$ )?(?:uv run )?alpha(?: |$)")
_NAME = re.compile(r"[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)+")
_CITE_TAG = re.compile(r"\[<[^>]+>:([a-z0-9_]+)\]")
_PLACEHOLDER = re.compile(r"<[^<>]*>")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LITERAL = re.compile(r"[\"']([A-Za-z0-9_-]+)[\"']")


def skill_file(name: str) -> str:
    return f".agents/skills/{name}/SKILL.md"


def card_files() -> list[str]:
    cards = sorted(p for p in (ROOT / TOOLS_DIR).glob("*.md") if p.name != "README.md")
    return [p.relative_to(ROOT).as_posix() for p in cards]


def instruction_files() -> list[str]:
    return [PLAYBOOK, ROUTING, TOOLS_INDEX, LESSONS_INDEX, *card_files(), *map(skill_file, SKILLS)]


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _body(text: str) -> list[str]:
    """Lines after the front matter."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        return lines[lines.index("---", 1) + 1 :]
    return lines


def _parts(rel: str) -> tuple[list[str], list[str]]:
    """(inline code spans, lines inside fenced blocks)."""
    spans: list[str] = []
    fenced: list[str] = []
    inside = False
    prose: list[str] = []
    for line in _body(_text(rel)):
        if _FENCE.match(line):
            inside = not inside
        elif inside:
            fenced.append(line.strip())
        else:
            prose.append(line)
    # A span may wrap across a line break inside a paragraph.
    for paragraph in "\n".join(prose).split("\n\n"):
        spans += [" ".join(s.split()) for s in _SPAN.findall(" ".join(paragraph.split()))]
    return spans, fenced


def commands_in(rel: str) -> list[str]:
    spans, fenced = _parts(rel)
    return [text for text in (*spans, *fenced) if _COMMAND.match(text)]


@cache
def cli() -> Any:
    """The full command tree, built the way ``test_cli_entry_lazy_groups`` inspects it."""
    from alpha_cli.main import app

    return typer.main.get_command(app)


def _tokens(text: str) -> list[str]:
    """Shell words, with each ``<placeholder>`` (which may hold spaces or quotes) as one word."""
    return shlex.split(_PLACEHOLDER.sub("<x>", text.replace("...", " ")))


def command_problem(text: str) -> str | None:
    """Why ``text`` (an ``alpha ...`` invocation written in a document) is not a real command."""
    command = cli()
    path = ["alpha"]
    takes_value = False
    for token in _tokens(_COMMAND.sub("", text, count=1)):
        subcommands = getattr(command, "commands", None)
        if token.startswith("--"):
            option, _, inline = token.partition("=")
            param = next(
                (p for p in command.params if option in (*p.opts, *p.secondary_opts)), None
            )
            if param is None and option != "--help":
                return f"{' '.join(path)} has no option {option}"
            takes_value = param is not None and not getattr(param, "is_flag", False) and not inline
        elif takes_value:
            takes_value = False  # the value of the option before it
        elif subcommands is not None:
            if token.startswith("<"):
                continue  # a placeholder argument
            if token not in subcommands:
                return f"{' '.join(path)} has no command {token!r}"
            command, path = subcommands[token], [*path, token]
    return None


@cache
def _source_text(wide: bool) -> str:
    roots = WIDE_SOURCES if wide else SPINE_SOURCES
    files = [f for root in roots for f in (sorted(root.rglob("*.py")) if root.is_dir() else [root])]
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


@cache
def program_names(wide: bool) -> frozenset[str]:
    """Names the program really uses: identifiers and quoted literals in its source."""
    text = _source_text(wide)
    return frozenset(_WORD.findall(text)) | frozenset(_LITERAL.findall(text))


def audit_checks() -> set[str]:
    lines = audit(
        None,
        None,
        None,
        {},
        fee=1.0,
        slippage=1.0,
        trades=0,
        years=0.0,
        labels=[],
        benchmark=True,
        variants=0,
    )
    return {line["check"] for line in lines}


def flag_names() -> set[str]:
    """Every flag the diagnostic pass can raise, from a document built to raise them all."""
    weak = {"sharpe": -1.0}
    sections = {
        "full_sample": {"sharpe": 1.0},
        "benchmark": {"sharpe": 2.0},
        "drawdowns": {
            "episodes": [{"share_explained": 0.9, "depth": -0.2, "benchmark_return": -0.18}]
        },
        "concentration": {"top_3": 0.9},
        "sensitivity": {"variants": [{"kind": "costs", **weak}, {"kind": "parameter", **weak}]},
        "delay": {"base_sharpe": 2.0, "delayed_sharpe": 0.5},
    }
    return {item["flag"] for item in diagnostics.flags(sections)}


# ---------------------------------------------------------------------------------------------
# The files exist and stay small


def test_playbook_cards_skills_and_lessons_exist() -> None:
    missing = [rel for rel in instruction_files() if not (ROOT / rel).is_file()]
    assert not missing, f"missing research instruction files: {missing}"
    assert card_files(), f"{TOOLS_DIR} has no tool cards"


def test_instruction_files_stay_within_their_limits() -> None:
    limits = {
        PLAYBOOK: PLAYBOOK_MAX_LINES,
        TOOLS_INDEX: INDEX_MAX_LINES,
        LESSONS_INDEX: INDEX_MAX_LINES,
    }
    limits |= dict.fromkeys(card_files(), CARD_MAX_LINES)
    problems = []
    for rel, limit in limits.items():
        lines = _text(rel).splitlines()
        if len(lines) > limit:
            problems.append(f"{rel}: {len(lines)} lines; the limit is {limit}")
    for name in SKILLS:
        body = _body(_text(skill_file(name)))
        while body and not body[0].strip():
            body.pop(0)
        if len(body) > SKILL_BODY_MAX_LINES:
            problems.append(
                f"{skill_file(name)}: body has {len(body)} lines; limit {SKILL_BODY_MAX_LINES}"
            )
    for rel in instruction_files():
        problems += [
            f"{rel}:{number}: line is {len(line)} characters; wrap it at {MAX_LINE_CHARS}"
            for number, line in enumerate(_body(_text(rel)), 1)
            if len(line) > MAX_LINE_CHARS and not line.startswith("description:")
        ]
    assert not problems, "\n".join(problems)


def test_tool_index_is_by_symptom_links_every_card_and_lists_what_is_planned() -> None:
    index = _text(TOOLS_INDEX)
    lowered = index.lower()
    problems = [f"symptom row missing: {s!r}" for s in SYMPTOMS if s not in lowered]
    problems += [
        f"{TOOLS_INDEX} does not link {Path(rel).name}"
        for rel in card_files()
        if f"]({Path(rel).name})" not in index
    ]
    assert "## Not available yet" in index, "the index must list tools that do not exist yet"
    planned = lowered.split("## not available yet", 1)[1]
    problems += [
        f"planned tool not listed as unavailable: {p!r}" for p in PLANNED if p not in planned
    ]
    assert not problems, "\n".join(problems)


def test_routing_sends_every_idea_to_the_playbook_and_the_rule_test() -> None:
    routing = _text(ROUTING)
    assert "](PLAYBOOK.md)" in routing and "alpha test" in routing
    assert f"]({ROUTING})" in _text("CONTEXT.md"), "the root CONTEXT.md must route to research"
    assert PLAYBOOK in _text("CONTEXT.md"), "the root CONTEXT.md must name the playbook"
    missing = [name for name in SKILLS if f"`{name}`" not in routing]
    assert not missing, f"{ROUTING} must name every research skill: {missing}"


# ---------------------------------------------------------------------------------------------
# Every command, option, metric, flag and audit name is real


@pytest.mark.parametrize("rel", instruction_files())
def test_every_alpha_command_and_option_named_is_registered(rel: str) -> None:
    problems = [f"`{text}`: {why}" for text in commands_in(rel) if (why := command_problem(text))]
    assert not problems, f"{rel} names commands the CLI does not have:\n" + "\n".join(problems)


def test_the_command_checker_rejects_unknown_commands_and_options() -> None:
    assert command_problem("uv run alpha results cite <run_id> oos_sharpe --json") is None
    assert command_problem("alpha test --rule ma_cross --param fast=50 --asset SPY") is None
    assert command_problem("alpha results check answer.md") is not None
    assert command_problem("alpha learn search words") is not None
    assert command_problem("alpha results cite <run_id> oos_sharpe --facts") is not None


@pytest.mark.parametrize("rel", instruction_files())
def test_every_cited_metric_is_a_stored_metric(rel: str) -> None:
    spans, fenced = _parts(rel)
    cited = set(_CITE_TAG.findall("\n".join((*spans, *fenced, *_body(_text(rel))))))
    for text in commands_in(rel):
        tokens = _tokens(text)
        if "cite" in tokens and len(tokens) > tokens.index("cite") + 2:
            cited.add(tokens[tokens.index("cite") + 2])
    unknown = sorted(
        m for m in cited if not m.startswith("<") and m != "metric" and m not in METRICS
    )
    assert not unknown, f"{rel} cites metrics that `alpha results cite` does not know: {unknown}"


@pytest.mark.parametrize("rel", instruction_files())
def test_every_name_in_a_code_span_occurs_in_the_program(rel: str) -> None:
    """Names such as `oos_sharpe`, `below-benchmark`, `NOT-CHECKED` and `enough-trades`."""
    wide = rel.startswith(TOOLS_DIR) or rel == ROUTING  # these also describe older commands
    known = program_names(wide) | set(METRICS) | audit_checks() | flag_names() | set(SKILLS)
    spans, _ = _parts(rel)
    named = {span for span in spans if _NAME.fullmatch(span)}
    unknown = sorted(named - known)
    assert not unknown, (
        f"{rel} names things in code spans that the program does not use (a renamed metric, "
        f"flag, audit check, label, error code or field?): {unknown}"
    )


def test_skills_name_only_real_metrics_flags_and_audit_checks() -> None:
    """The exact vocabularies, so a skill cannot keep a check or flag the tool has dropped."""
    checks, flags = audit_checks(), flag_names()
    assert checks and len(flags) == 6, "the fixtures above must exercise every check and flag"
    review = _parts(skill_file("review-result"))[0]
    missing = sorted(checks - set(review))
    assert not missing, f"review-result must walk every audit check; missing: {missing}"
    card = _parts(f"{TOOLS_DIR}/diagnose-and-audit.md")[0]
    missing = sorted((checks | flags) - set(card))
    assert not missing, f"the diagnose card must explain every check and flag; missing: {missing}"
    card = _parts(f"{TOOLS_DIR}/results-and-cite.md")[0]
    missing = sorted(set(METRICS) - set(card))
    assert not missing, f"the results card must list every metric; missing: {missing}"
