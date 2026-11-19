"""`alpha nightly status`: read the records, count the clean full runs, say if it is ready.

Ready means two full runs in a row with no blocking defect. A partial run (`--only`) is never
counted and never breaks the streak. Reads only; nothing is written.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

READY_AFTER = 2
RULE = "Ready means two full runs in a row with no blocking defect. Partial runs do not count."
CRON_TIME = "17 2 * * *"
FOLDER = re.compile(r"(\d{4}-\d{2}-\d{2})-(\d+)")


def read_records(home: Path) -> list[dict[str, Any]]:
    """Every readable record, oldest first by date and run number."""
    found: list[tuple[str, int, dict[str, Any]]] = []
    for folder in (home / "nightly").glob("*-*"):
        match = FOLDER.fullmatch(folder.name)
        try:
            body = json.loads((folder / "record.json").read_bytes())
        except (OSError, ValueError):
            continue
        if match and isinstance(body, dict):
            found.append((match[1], int(match[2]), body))
    return [body for _, _, body in sorted(found, key=lambda item: item[:2])]


def readiness(records: list[dict[str, Any]]) -> dict[str, Any]:
    full = [r for r in records if r.get("full") is True]
    streak = 0
    for record in reversed(full):
        if record.get("blocking") != 0:
            break
        streak += 1
    return {"streak": streak, "ready": streak >= READY_AFTER, "needed": READY_AFTER}


def crontab_line(home: Path, config: Path) -> str:
    alpha = Path(sys.executable).with_name("alpha")
    lock = home / "nightly" / ".lock"
    command = f"{alpha} nightly run --config {config.resolve()}"
    env = f"ALPHA_DATA_DIR={shlex.quote(str(home.resolve()))}"
    return f"{CRON_TIME} {env} flock -n {shlex.quote(str(lock))} {command}"


def status_facts(home: Path, config: Path) -> dict[str, Any]:
    records = read_records(home)
    full = [r for r in records if r.get("full") is True]
    return {
        "last": records[-1] if records else None,
        "records": len(records),
        **readiness(records),
        "rule": RULE,
        "open_defects": full[-1]["defects"] if full else [],
        "crontab_line": crontab_line(home, config),
    }


def last_night_line(home: Path) -> str | None:
    records = read_records(home)
    return str(records[-1]["summary_line"]) if records else None


def status_text(facts: dict[str, Any]) -> str:
    last = facts["last"]
    if last is None:
        lines = ["No nightly run is recorded yet. Start one with `alpha nightly run`."]
    else:
        lines = [f"{last['summary_line']} (run {last['date']}-{last['run_number']})"]
    streak = f"{facts['streak']} clean full run{'' if facts['streak'] == 1 else 's'} in a row"
    lines.append(f"Streak: {streak}. Ready: {'yes' if facts['ready'] else 'no'}.")
    lines.append(RULE)
    defects = facts["open_defects"]
    lines.append("Open defects (from the last full run): " + ("none." if not defects else ""))
    lines.extend(
        f"  {d['severity']} in {d['step']}: {d['text']}  To reproduce: {d['reproduce']}"
        for d in defects
    )
    lines += [
        "Schedule it yourself. This command installs nothing. One crontab line:",
        f"  {facts['crontab_line']}",
    ]
    return "\n".join(lines)
