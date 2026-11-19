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

from alpha_cli.nightly_steps import BLOCKING, MINOR, NOT_RUN, PASS

SCENARIOS = {"N1": "rule path", "N2": "setup path", "N3": "RD-Agent path"}
N3_STUB = (
    "not run: needs the owner's key file and a spend cap; enabled by `rdagent_config = <file>`."
)


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
    for scenario in wanted:
        mine = [s for s in steps if s["scenario"] == scenario]
        if not any(s["state"] != NOT_RUN for s in mine):
            continue
        total += 1
        worked += not any(s["state"] == BLOCKING for s in mine)
    return worked, total


def summary_line(steps: list[dict[str, Any]], wanted: tuple[str, ...], full: bool) -> str:
    worked, total = _paths(steps, wanted)
    line = f"Last night: {worked} of {total} paths worked"
    return line + ("." if full else f" (partial run: {', '.join(wanted)} only).")


def build_record(
    steps: list[dict[str, Any]], wanted: tuple[str, ...], day: date, number: int, full: bool
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
    return {
        "schema": 1,
        "date": day.isoformat(),
        "run_number": number,
        "full": full,
        "scenarios": list(wanted),
        "summary_line": summary_line(steps, wanted, full),
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
    return f"  {step['id']}: {word} ({step['seconds']} s).{verdict}"


def summary_text(record: dict[str, Any]) -> str:
    lines = [record["summary_line"]]
    kind = "full" if record["full"] else "partial"
    lines.append(
        f"Run {record['date']}-{record['run_number']} was a {kind} run. "
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
