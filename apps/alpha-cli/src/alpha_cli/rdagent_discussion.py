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
    result = {"plain_summary": raw, "plain_summary_status": "ok"}
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


def revision_statements(item: dict[str, Any]) -> dict[str, list[str]]:
    """Keep each list only if it holds short statements; a bad or missing list is left out."""
    explanation = {}
    for key in ("honoured", "not_honoured"):
        values = item.get(key)
        if isinstance(values, list) and all(
            isinstance(v, str) and v.strip() and len(v) <= 200 for v in values
        ):
            explanation[key] = values[:5]
    return explanation


def validate_decision(record: Any) -> None:
    if not isinstance(record, dict) or not isinstance(record.get("selected_tasks"), list):
        raise ValueError("The decision must list the ideas selected to build.")
    for key in ("selected_tasks", "dropped", "replacements"):
        items = record.get(key, [])
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise ValueError(f"The decision field {key} must list ideas.")
        for item in items:
            if key != "dropped" and not isinstance(item.get("name"), str):
                raise ValueError("Expected an idea name in the decision.")
            given = {k: item[k] for k in ("honoured", "not_honoured") if k in item}
            if revision_statements(given) != given:
                raise ValueError("honoured and not_honoured must list up to five short statements.")


def round_folders(run: Path) -> list[Path]:
    folders = [
        path.parent
        for path in (run / "discussion").glob("round-*/proposal.json")
        if re.fullmatch(r"round-[0-9]+", path.parent.name)
    ]
    return sorted(folders, key=lambda folder: int(folder.name[6:]), reverse=True)


def newest(run: Path) -> Path:
    folders = round_folders(run)
    if not folders:
        raise ValueError("This run has no proposal from RD-Agent yet.")
    return folders[0]


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
    return sentence(f"{label}: {', '.join(names) if names else 'none'}")


# Plain names are documented in docs/reference/glossary.md.
FAMILY_NAMES = {
    "futures funding": "futures funding",
    "price near its high / range position": "price within its recent range",
    "intraday return and gaps": "price changes within and between trading days",
    "illiquidity": "ease of trading",
    "return-volume relation": "how price changes with trading volume",
    "skewness and lottery returns": "unusually large gains or losses",
    "drawdown": "fall from a previous high",
    "past return (momentum or reversal)": "whether past price moves continue or reverse",
    "volatility and beta": "price swings and market sensitivity",
    "range and compression": "widening or narrowing price ranges",
    "volume level and trend": "trading volume and its trend",
    "VWAP distance": "distance from the volume-weighted average price",
}


def plain_family(family: str) -> str:
    return ", ".join(
        dict.fromkeys(FAMILY_NAMES.get(f, "not classified") for f in family.split("; "))
    )


def plain_reason(raw: str | None) -> str:
    text = re.sub(r'^\s*[*`"\s]*direction_reason[*`"\s]*[:=][*`"\s]*', "", raw or "", flags=re.I)
    text = re.split(
        r'`{3}|[{}\[\]]|\bproposal_metadata\b|["\']?\b\w+_\w+\b["\']?\s*[:=]|"[^"]+"\s*:',
        text,
        maxsplit=1,
        flags=re.I,
    )[0]
    text = re.sub(r"<[^>]*>|[*`#]|\$(?=[A-Za-z])", "", text)
    # Column names such as funding_rate read as plain words: "funding rate".
    text = re.sub(r"\b[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+\b", lambda m: m[0].replace("_", " "), text)
    return " ".join(text.replace("_", "").split()).strip(' ;:,"') or "not recorded"


def sentence(text: str) -> str:
    return text if text.endswith((".", "?", "!")) else text + "."


def idea_lines(item: dict[str, Any], number: int) -> list[str]:
    from alpha_cli._rdagent_clocks import CLOCKS
    from alpha_cli.rdagent_journey_words import DIRECTION

    fields = summary_fields(item.get("plain_summary"))
    valid = (
        fields["plain_summary_status"] == "ok" and item.get("plain_summary_status", "ok") == "ok"
    )
    summary = (
        sentence(fields["plain_summary"].strip()) if valid else "The agent gave no plain sentence."
    )
    direction = DIRECTION.get(item.get("declared_direction") or 0)
    days = CLOCKS.get(item.get("primary_clock") or "")
    horizon = item.get("horizon_days", days)
    claim = "What it expects: not recorded."
    if direction:
        period = f" over the next {horizon} days" if horizon else ""
        claim = f"It expects coins with {direction} numbers to earn more{period}."
    columns = ", ".join(c.lstrip("$").replace("_", " ") for c in item.get("input_columns") or [])
    count = item.get("instrument_count")
    facts = [
        summary,
        claim,
        f"Holding period: about {horizon} days." if horizon else "Holding period: not recorded.",
        f"Coins ranked each period: {count if count is not None else 'not recorded'}.",
        f"How often positions change: every {days} days."
        if days
        else "How often positions change: not recorded.",
        f"Idea type: {plain_family(item['family']) if item.get('family') else 'not recorded'}.",
        sentence(f"The agent's reason: {plain_reason(item.get('reason'))}"),
        f"Data it plans to read: {columns or 'not recorded'}.",
    ]
    return ["", f"{number}. {item['name']}", *["   " + fact for fact in facts]]


SYSTEM_REASONS = {
    "call cap reached": "the model call limit for this run was reached",
    "revision answer unusable": "the agent's answer could not be read",
    "revision returned a dropped idea": "the changed version brought back an idea you dropped",
}


def decision_text(folder: Path | None) -> str:
    if folder is None:
        return "No decision has been recorded yet."
    record = json.loads((folder / "decision.json").read_bytes())
    validate_decision(record)
    selected = [item["name"] for item in record["selected_tasks"]]
    lines = [f"Last decision, round {folder.name[6:]}:", ideas_line("Built", selected)]
    if record.get("reply") == "none (timed out)":
        proceed = record.get("policy") == "proceed"
        done = "built every idea as proposed" if proceed else "stopped and built nothing"
        lines.append(f"Nobody answered in time, so the run {done}.")
    for item in record.get("refused", []):
        lines.append(
            f"Not offered again: {item['name']}. "
            f"You dropped it in round {item['dropped_in_round']}."
        )
    for item in record.get("dropped", []):
        request = item.get("request", {})
        if not request:
            why = f"Your reason: {item['reason']}" if "reason" in item else "You gave no reason"
            lines.append(sentence(f"You dropped {item['name']}. {why}"))
            continue
        if "user_idea" in request:
            what = f'your idea "{request["user_idea"]}"'
        else:
            what = f"the change you asked for to {request['proposal']['name']}"
        named = f" (the agent named it {item['name']})" if "name" in item else ""
        reason = item["reason"]
        reason = next((v for k, v in SYSTEM_REASONS.items() if reason.startswith(k)), reason)
        lines.append(sentence(f"Not built: {what}{named}. Why: {reason}"))
        if "note" in request and "name" in item:
            lines.extend(explanation_lines(item))
    for item in record.get("replacements", []):
        if source := item.get("revised_from"):
            lines.append(f"Changed {source} into {item['name']}, as you asked.")
            lines.extend(explanation_lines(item))
        else:
            lines.append(sentence(f"Built your idea as {item['name']}: {item['user_idea']}"))
    return "\n".join(lines)


def explanation_lines(item: dict[str, Any]) -> list[str]:
    """What the agent says it did for the note; a missing list is said, never assumed."""
    if "honoured" not in item and "not_honoured" not in item:
        return ["   The agent did not say what it changed."]
    return [
        "   " + sentence(f"{label}: {'; '.join(item[key]) if item[key] else 'nothing'}")
        if key in item
        else f"   {label}: the agent did not say."
        for key, label in (("honoured", "Done as you asked"), ("not_honoured", "Not done"))
    ]


def state_text(run: Path, status: dict[str, Any], folders: list[Path]) -> str:
    if (run / "receipt.json").exists() or status.get("state") == "ended":
        return "This run has ended."
    number = status.get("round")
    state = status.get("state", "")
    if state == "building":
        path = run / "discussion" / f"round-{number}" / "decision.json"
        count = len(json.loads(path.read_bytes())["selected_tasks"])
        estimate = status.get("estimate_minutes")
        wait = (
            f"about {estimate} minute{'s' if estimate != 1 else ''}"
            if estimate
            else "a few minutes"
        )
        return (
            f"Round {number} is being built: {count} idea{'s' if count != 1 else ''}. "
            f"The next proposal usually appears in {wait}."
        )
    if state == "waiting" and folders and (folders[0] / "reply.json").exists():
        return f"Your answer for round {number} is saved."
    return {
        "proposing": f"RD-Agent is preparing round {number}.",
        "reviewing": f"RD-Agent is reviewing round {number}.",
        "evaluating": f"ALPHA is testing round {number}.",
        "applying": f"RD-Agent is applying your answer for round {number}.",
        "nothing-selected": f"Round {number} has no ideas to build.",
        "stopped": f"Round {number} stopped when the wait ended.",
        "waiting": f"RD-Agent is publishing the proposal for round {number}.",
    }.get(state, "The worker has not recorded its current state.")


def proposal_text(run: Path, *, details: bool = False, last_decision: bool = False) -> str:
    folders = round_folders(run)
    last = next((folder for folder in folders if (folder / "decision.json").exists()), None)
    if last_decision:
        return decision_text(last)
    path = run / "discussion/status.json"
    status = json.loads(path.read_bytes()) if path.exists() else {}
    if (
        not folders
        or closed(run, folders[0])
        or (
            status and (status["state"] != "waiting" or status["round"] != int(folders[0].name[6:]))
        )
    ):
        return (
            "No proposal is waiting. "
            + state_text(run, status, folders)
            + "\n"
            + decision_text(last)
        )
    proposal = json.loads((folders[0] / "proposal.json").read_bytes())
    count = len(proposal["ideas"])
    deadline = datetime.fromisoformat(proposal["deadline"]).astimezone(UTC)
    later = (
        "builds every idea as proposed"
        if proposal.get("on_timeout", "proceed") == "proceed"
        else "stops and builds nothing"
    )
    lines = [
        f"RD-Agent proposes {count} idea{'s' if count != 1 else ''} for round {proposal['round']}."
        if count
        else f"RD-Agent has no new ideas for round {proposal['round']}. You can add your own.",
        f"You have until {deadline:%H:%M} UTC ({proposal['wait_minutes']} minutes). "
        f"If you do not answer, the run {later}.",
    ]
    for number, item in enumerate(proposal["ideas"], 1):
        lines.extend(idea_lines(item, number))
    for item in proposal.get("refused", []):
        lines.append(
            f"Not offered again: {item['name']}. You dropped this idea in round "
            f"{item['dropped_in_round']}. To build it, add it as your own idea with --idea."
        )
    lines.append("")
    if budget := proposal.get("remaining"):
        lines.append(
            f"Model budget left in this run: {budget['calls']} calls, ${budget['usd']:.2f}."
        )
    families = proposal.get("families", "")
    match = re.match(r"Closed families: (.*?)\. open families:", families)
    closed_names = match[1].split("; ") if match and match[1] != "none" else []
    plain = list(dict.fromkeys(plain_family(f) for f in closed_names))
    names = plain[:5] + ([f"and {len(plain) - 5} more"] if len(plain) > 5 else [])
    summary = ", ".join(names) or ("none" if match else "not recorded")
    lines.append(f"Idea types closed after repeated failed tries: {summary}.")
    if details and families:
        lines.append(families)
    if caution := proposal.get("caution"):
        lines.append(caution)
    lines += [
        "",
        "To answer, run:",
        f"  alpha ledger reply --run-dir {shlex.quote(str(run))} --as owner",
        "Then add what you want to change. Name an idea by its number or its name:",
        "  --drop 1                      do not build idea 1 (add =reason to say why)",
        '  --revise "1=what to change"   ask the agent to change idea 1',
        '  --idea "your idea"            add your own idea (two at most)',
        '  --note "text"                 tell the agent something for the next round',
        "Ideas you do not name are built as proposed.",
        "A stand-in user answers with --as stand-in instead of --as owner.",
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
            if re.fullmatch(r"[0-9]+", name):
                index = int(name)
                if not 1 <= index <= len(names):
                    listing = ", ".join(f"{i}. {n}" for i, n in enumerate(names, 1))
                    raise ValueError(f"There is no idea numbered {name}. The ideas are: {listing}")
                name = names[index - 1]
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
    ]
    for n, c in chosen.items():
        if c["action"] == "drop":
            why = f" Your reason: {c['reason']}" if "reason" in c else " No reason given"
            lines.append(sentence(f"Drop: {n}.{why}"))
        elif c["action"] == "revise":
            lines.append(sentence(f"Change: {n}. Your note: {c['note']}"))
    lines += [sentence(f"Your own idea: {text}") for text in ideas]
    if note is not None:
        lines.append(sentence("Note to the agent: " + note))
    lines.append(f"Saved in {(folder / 'reply.json').relative_to(run)}.")
    return "\n".join(lines)
