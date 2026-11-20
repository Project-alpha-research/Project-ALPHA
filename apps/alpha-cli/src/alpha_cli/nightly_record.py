"""The dated nightly record: `<home>/nightly/<UTC date>-<n>/record.json` and `summary.txt`.

Append-only. A new run takes the next free folder and never edits an old one. A record holds
commands, ids, durations, verdict words and defect text. It holds no bar values and no key
material.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from alpha_cli.nightly_steps import BLOCKING, COMPUTED, MINOR, NOT_RUN, PASS, REUSED

SCENARIOS = {
    "N1": "rule path",
    "N2": "setup path",
    "N3": "RD-Agent path",
    "N0": "bar refresh for followed assets",
    "N4": "follow update",
}
ALL = (
    "N1",
    "N2",
    "N3",
)  # the three golden paths; N4 is a fourth path only when an idea is followed
ORDER = ("N1", "N2", "N3", "N0", "N4")
PATHS = (*ALL, "N4")
THREE = {1: "one", 2: "two", 3: "all three"}
N3_STUB = (
    "not run: needs the owner's key file and a spend cap; enabled by `rdagent_config = <file>`."
)


def selected(only: tuple[str, ...] | None, refresh: bool) -> tuple[str, ...]:
    """The scenarios to run: all of them (N0 only when `refresh_followed` is on), or `--only`."""
    default = (*ALL, *(("N0",) if refresh else ()), "N4")
    return tuple(n for n in ORDER if n in (default if only is None else only))


def is_partial(wanted: tuple[str, ...]) -> bool:
    """A full attempt selects N1, N2, N3 and N4. N0 is optional."""
    return not {*ALL, "N4"} <= set(wanted)


def new_folder(home: Path, day: date) -> tuple[Path, int]:
    """Create the next free `<date>-<n>` folder. `mkdir` without `exist_ok` never reuses one."""
    root = home / "nightly"
    root.mkdir(parents=True, exist_ok=True)
    number = 1
    while True:
        folder = root / f"{day.isoformat()}-{number}"
        try:
            folder.mkdir()
        except FileExistsError:
            number += 1
            continue
        return folder, number


def _paths(steps: list[dict[str, Any]], wanted: tuple[str, ...]) -> tuple[int, int]:
    worked = total = 0
    for scenario in (n for n in wanted if n in PATHS):
        mine = [s for s in steps if s["scenario"] == scenario]
        if not any(s["state"] != NOT_RUN for s in mine):
            continue
        total += 1
        worked += not any(s["state"] == BLOCKING for s in mine)
    return worked, total


def paths_run(steps: list[dict[str, Any]]) -> list[str]:
    """The paths that really ran: at least one step not marked not-run. The N3 stub is not run."""
    return [n for n in PATHS if any(s["scenario"] == n and s["state"] != NOT_RUN for s in steps)]


def completeness(wanted: tuple[str, ...], ran: list[str]) -> str:
    if is_partial(wanted):
        return f"partial run ({', '.join(wanted)} only)"
    three = [n for n in ran if n in ALL]
    follow = " plus the follow update" if "N4" in ran else ""
    if len(three) == len(ALL):
        return "all three paths" + follow
    off = ", ".join(f"{SCENARIOS[n]} off" for n in ALL if n not in three)
    return f"{THREE.get(len(three), 'no')} of three paths ({off}){follow}"


def summary_line(steps: list[dict[str, Any]], wanted: tuple[str, ...]) -> str:
    worked, total = _paths(steps, wanted)
    line = f"Last night: {worked} of {total} paths worked"
    return line + ("." if not is_partial(wanted) else f" (partial run: {', '.join(wanted)} only).")


def build_record(
    steps: list[dict[str, Any]],
    wanted: tuple[str, ...],
    day: date,
    number: int,
    config_path: Path | None = None,
    follows: int | None = None,
    heads: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    defects = [
        {
            "step": s["id"],
            "severity": "blocking" if s["state"] == BLOCKING else "minor",
            "text": s["defect"],
            "reproduce": s["command"],
        }
        for s in steps
        if s["state"] in (BLOCKING, MINOR)
    ]
    ran = paths_run(steps)
    return {
        "schema": 2,
        "date": day.isoformat(),
        "run_number": number,
        "full": not is_partial(wanted) and all(n in ran for n in ALL),
        "follows": follows,
        "follow_heads": heads or {},
        "complete": completeness(wanted, ran),
        "paths_run": ran,
        "config_path": str(config_path) if config_path else None,
        "scenarios": list(wanted),
        "summary_line": summary_line(steps, wanted),
        "blocking": sum(d["severity"] == "blocking" for d in defects),
        "minor": sum(d["severity"] == "minor" for d in defects),
        "steps": steps,
        "defects": defects,
    }


def _step_line(step: dict[str, Any]) -> str:
    if step["state"] == NOT_RUN:
        return f"  {step['id']}: {step['note']}"
    word = {PASS: "worked", MINOR: "worked with a warning", BLOCKING: "FAILED"}[step["state"]]
    verdict = f" Verdict word: {step['verdict']}." if step["verdict"] else ""
    reused = ", no new bar" if step["scenario"] == "N0" else ", reused the stored result (repeat)"
    how = {COMPUTED: ", computed", REUSED: reused}
    mode = how.get(str(step.get("evidence")), "")
    return f"  {step['id']}: {word}{mode} ({step['seconds']} s).{verdict}"


def summary_text(record: dict[str, Any]) -> str:
    lines = [record["summary_line"]]
    lines.append(
        f"Run {record['date']}-{record['run_number']}: {record['complete']}. "
        f"Blocking defects: {record['blocking']}. Minor defects: {record['minor']}."
    )
    for scenario in record["scenarios"]:
        lines.append(f"{scenario} ({SCENARIOS[scenario]})")
        mine = [s for s in record["steps"] if s["scenario"] == scenario]
        lines.extend(_step_line(s) for s in mine)
    if record["defects"]:
        lines.append("Defects")
        for defect in record["defects"]:
            lines.append(f"  {defect['severity']} defect in {defect['step']}: {defect['text']}")
            lines.append(f"  To reproduce: {defect['reproduce']}")
    lines.append("This run judges the system. It says nothing about whether an idea is good.")
    return "\n".join(lines) + "\n"


def write_record(folder: Path, record: dict[str, Any]) -> None:
    """Write both files with exclusive creation: an existing record is never overwritten."""
    with (folder / "record.json").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(record, indent=1, sort_keys=True) + "\n")
    with (folder / "summary.txt").open("x", encoding="utf-8") as handle:
        handle.write(summary_text(record))
