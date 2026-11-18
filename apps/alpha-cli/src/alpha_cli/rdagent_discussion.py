"""Run-folder commands for choosing what RD-Agent will build."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpha_core.atomic import write_text


def summary_fields(raw: Any) -> dict[str, Any]:
    result = {"plain_summary": raw}
    if raw is None or isinstance(raw, str) and not raw.strip():
        result["plain_summary_status"] = "missing"
    elif not isinstance(raw, str) or len(raw.split()) > 30 or set(raw) & set(r"()=_{}\/*^$"):
        result["plain_summary_status"] = "rejected"
    return result


USER_TEXT_LIMIT = 500  # characters in any one piece of user-written text


def validate_reply(reply: Any, names: list[str]) -> None:
    def text(value: Any) -> bool:
        if isinstance(value, str) and len(value) > USER_TEXT_LIMIT:
            raise ValueError(f"Keep each note, reason and idea to {USER_TEXT_LIMIT} characters.")
        return isinstance(value, str) and bool(value.strip())

    if not isinstance(reply, dict) or reply.keys() - {
        "author",
        "ideas",
        "user_ideas",
        "note_to_agent",
    }:
        raise ValueError("Unexpected reply fields.")
    if reply.get("author") not in ("owner", "stand-in user, not the owner"):
        raise ValueError("Choose owner or stand-in user, not the owner.")
    ideas = reply.get("ideas")
    if not isinstance(ideas, dict) or set(ideas) != set(names):
        raise ValueError("Expected one decision for each of: " + ", ".join(names))
    for name, choice in ideas.items():
        if not isinstance(choice, dict):
            raise ValueError(f"Expected a decision for {name}.")
        action = choice.get("action")
        if action == "accept" and choice.keys() == {"action"}:
            continue
        if action == "drop" and (
            choice.keys() == {"action"}
            or choice.keys() == {"action", "reason"}
            and text(choice["reason"])
        ):
            continue
        if action == "revise" and choice.keys() == {"action", "note"} and text(choice["note"]):
            continue
        raise ValueError(f"Invalid decision for {name}. A revision needs a note.")
    extra = reply.get("user_ideas", [])
    if not isinstance(extra, list) or len(extra) > 2 or not all(text(item) for item in extra):
        raise ValueError("Supply at most two non-empty user ideas.")
    if "note_to_agent" in reply and not text(reply["note_to_agent"]):
        raise ValueError("The note to the agent must contain text.")


def newest(run: Path) -> Path:
    folders = [
        path.parent
        for path in (run / "discussion").glob("round-*/proposal.json")
        if re.fullmatch(r"round-[0-9]+", path.parent.name)
    ]
    if not folders:
        raise ValueError("This run has no proposal from RD-Agent yet.")
    return max(folders, key=lambda folder: int(folder.name[6:]))


def closed(run: Path, folder: Path) -> str | None:
    """Why this round takes no answer, or None while it is still waiting."""
    number = folder.name[6:]
    if (folder / "reply.json").exists():
        return f"Round {number} already has an answer. A second answer is refused."
    if (folder / "decision.json").exists():
        return f"Round {number} is closed: the wait ended and building has started."
    if (run / "receipt.json").exists():
        return "This run has ended."
    return None


def ideas_line(label: str, names: list[str]) -> str:
    return f"{label}: {', '.join(names) if names else 'none'}."


def proposal_text(run: Path) -> str:
    from alpha_cli.rdagent_journey_words import CLOCK, DIRECTION

    folder = newest(run)
    if reason := closed(run, folder):
        raise ValueError(reason + " Nothing is waiting for your answer.")
    proposal = json.loads((folder / "proposal.json").read_bytes())
    count = len(proposal["ideas"])
    lines = [
        f"RD-Agent proposes {count} idea{'s' if count != 1 else ''} for round {proposal['round']}.",
        "It builds nothing until you answer or the wait ends.",
    ]
    for number, item in enumerate(proposal["ideas"], 1):
        status = item.get("plain_summary_status")
        summary = {
            None: item.get("plain_summary"),
            "missing": "The agent gave no plain sentence for this idea.",
        }.get(status, "The agent's plain sentence broke the rules, so it is not shown.")
        direction = DIRECTION.get(item["declared_direction"], "unrecorded")
        clock = CLOCK.get(item["primary_clock"], item["primary_clock"])
        lines += [
            "",
            f"{number}. {item['name']}",
            f"   {summary}",
            f"   It expects coins with {direction} numbers to earn more over the next {clock}.",
            f"   Idea family: {item['family']}.",
            f"   The agent's reason: {item['reason']}",
        ]
        if columns := item.get("input_columns"):
            lines.append("   Data it plans to read: " + ", ".join(c.lstrip("$") for c in columns))
    deadline = datetime.fromisoformat(proposal["deadline"]).astimezone(UTC)
    later = (
        "it builds every idea as proposed."
        if proposal.get("on_timeout", "proceed") == "proceed"
        else "the run stops before building anything."
    )
    lines += ["", f"It waits until {deadline:%Y-%m-%d %H:%M} UTC. If you do not answer, {later}"]
    if budget := proposal.get("remaining"):
        lines.append(
            f"Model budget left in this run: {budget['calls']} calls, ${budget['usd']:.2f}."
        )
    if families := proposal.get("families"):
        lines.append(families)
    lines += [
        "",
        "To answer, run:",
        f"  alpha ledger reply --run-dir {shlex.quote(str(run))} --as owner",
        "Ideas you do not name are built as proposed. Add --drop NAME to skip one,",
        '--revise "NAME=what to change" to ask for a change, or --idea "your idea" to add',
        "your own (two at most). A stand-in answers with --as stand-in instead.",
    ]
    return "\n".join(lines)


def submit(
    run: Path,
    author: str,
    accept: list[str],
    drop: list[str],
    revise: list[str],
    ideas: list[str],
    note: str | None,
) -> str:
    folder = newest(run)
    names = [item["name"] for item in json.loads((folder / "proposal.json").read_bytes())["ideas"]]
    choices: dict[str, dict[str, str]] = {}
    for action, args in (("accept", accept), ("drop", drop), ("revise", revise)):
        for arg in args:
            name, sep, detail = arg.partition("=") if action != "accept" else (arg, "", "")
            if name not in names:
                raise ValueError(
                    f"There is no idea called {name}. The ideas are: " + ", ".join(names)
                )
            if name in choices:
                raise ValueError(f"{name} is named more than once. Give each idea one choice.")
            choice = {"action": action}
            if sep:
                choice["note" if action == "revise" else "reason"] = detail
            choices[name] = choice
    chosen = {name: choices.get(name, {"action": "accept"}) for name in names}
    reply = {
        "author": "stand-in user, not the owner" if author == "stand-in" else author,
        "ideas": chosen,
        **({"user_ideas": ideas} if ideas else {}),
        **({"note_to_agent": note} if note is not None else {}),
    }
    validate_reply(reply, names)
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)  # the worker reads the reply under the same lock
        if reason := closed(run, folder):
            k = 1 + len(list(folder.glob("refused-reply-*.json")))
            record = {"refused": reason, "reply": reply}
            write_text(folder / f"refused-reply-{k}.json", json.dumps(record, indent=2) + "\n")
            raise ValueError(f"{reason} Your answer was kept as refused-reply-{k}.json.")
        write_text(folder / "reply.json", json.dumps(reply, indent=2) + "\n")
    finally:
        os.close(fd)
    lines = [
        f"Your answer for round {folder.name[6:]} is saved. RD-Agent reads it within seconds.",
        f"Answered by: {'the owner' if author == 'owner' else 'a stand-in user, not the owner'}.",
        ideas_line("Build as proposed", [n for n in names if chosen[n]["action"] == "accept"]),
        ideas_line("Drop", [n for n in names if chosen[n]["action"] == "drop"]),
        ideas_line(
            "Ask the agent to change", [n for n in names if chosen[n]["action"] == "revise"]
        ),
        f"Your own ideas: {len(ideas)}.",
    ]
    if note is not None:
        lines.append("Your note goes to the agent with the next round.")
    lines.append(f"Saved in {(folder / 'reply.json').relative_to(run)}.")
    return "\n".join(lines)
