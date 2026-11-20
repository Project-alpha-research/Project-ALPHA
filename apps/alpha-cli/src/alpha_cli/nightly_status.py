"""`alpha nightly status`: read the records and say, with reasons, whether the run is ready.

`readiness` is the one place that decides. A partial run (`--only`) is never counted and never
breaks the streak. Reads only; nothing is written.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

from alpha_cli.nightly_record import ALL, SCENARIOS
from alpha_cli.nightly_steps import COMPUTED, REUSED, UNKNOWN

RULE = (
    "Ready needs the two latest full-attempt runs to be on two different dates, each with no "
    "blocking defect, all three paths run, a rule test that was computed (a recheck: computed "
    "again and compared with the stored result, and the two matched; or the first run of the "
    "test) and a computed setup step. "
    "When any idea is followed, the follow update (N4) is a fourth path and must run too; "
    "when nothing is followed it is not run and not required."
)
NEED_DATA = (
    "The run does not need new bars to count: the rule test is the same test every night, so the "
    "run computes it again and compares it with the stored result. To pull new bars for the "
    "assets of followed ideas only, set `refresh_followed = true` (step N0)."
)
TIMING = (
    "Timing: for a daily stock follow to be on time, the nightly run must start after the "
    "exchange close and after your data provider has that day's bar, and before the next open. "
    "The crontab time above (02:17 on this computer's clock) may be wrong for your timezone: "
    "check it against that rule. Crypto bars close at 00:00 UTC; a night run writes after the "
    "next one opens."
)
CRON_TIME = "17 2 * * *"
FOLDER = re.compile(r"(\d{4}-\d{2}-\d{2})-(\d+)")
RECENT = 5
SETUP_STEPS = ("N2.find", "N2.study", "N2.trade")


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


def _partial(record: dict[str, Any]) -> bool:
    """A `--only` run. Records from before `paths_run` say so with `full: false`. A record that
    has `follows` must also have selected N4; older ones need N1, N2 and N3 only."""
    if "paths_run" not in record:
        return record.get("full") is not True
    need = {*ALL, *(("N4",) if "follows" in record else ())}
    return not need <= set(record.get("scenarios") or [])


def _evidence(record: dict[str, Any], ids: tuple[str, ...]) -> list[str]:
    steps = [s for s in record.get("steps") or [] if isinstance(s, dict) and s.get("id") in ids]
    return [str(s.get("evidence", UNKNOWN)) for s in steps]


def _row(record: dict[str, Any]) -> dict[str, Any]:
    marks = [
        str(s.get("evidence", UNKNOWN)) for s in record.get("steps") or [] if isinstance(s, dict)
    ]
    ran = record.get("paths_run")
    rule, setup = _evidence(record, ("N1.test",)), _evidence(record, SETUP_STEPS)
    follows = record.get("follows")
    return {
        "follows": follows if isinstance(follows, int) else None,
        "run": f"{record.get('date')}-{record.get('run_number')}",
        "date": record.get("date"),
        "paths_run": ran if isinstance(ran, list) else None,
        "computed": marks.count(COMPUTED),
        "reused": marks.count(REUSED),
        "unknown": len(marks) - marks.count(COMPUTED) - marks.count(REUSED),
        "blocking": record.get("blocking"),
        "rule_test": rule[0] if rule else UNKNOWN,
        "setup": COMPUTED if COMPUTED in setup else (REUSED if REUSED in setup else UNKNOWN),
        "reused_only": COMPUTED not in marks and REUSED in marks,
    }


def _why_not(row: dict[str, Any]) -> list[tuple[str, str]]:
    """The reasons (b), (c) and (d) one run fails, each as (letter, plain words)."""
    name, found = row["run"], []
    if row["blocking"] != 0:
        found.append(("b", f"Run {name} has a blocking defect."))
    ran = row["paths_run"]
    if ran is None or not set(ALL) <= set(ran):
        left = [SCENARIOS[n] for n in ALL if n not in (ran or [])]
        say = (
            "was written before paths were recorded"
            if ran is None
            else f"left off: {', '.join(left)}"
        )
        found.append(("c", f"Run {name} did not run all three paths ({say})."))
    if row["follows"] and "N4" not in (ran or []):
        found.append(
            (
                "c",
                f"Run {name} did not run the follow update (N4) "
                f"while {row['follows']} idea(s) are followed.",
            )
        )
    if row["rule_test"] != COMPUTED:
        why = {
            REUSED: "the engine did not run: the rule test was answered from the stored result "
            "and not computed again"
        }
        kind = "reused only" if row["reused_only"] else "has no computed rule test"
        how = why.get(row["rule_test"], "the rule test evidence is unknown")
        found.append(("d", f"Run {name} {kind}: {how}."))
    elif row["setup"] != COMPUTED:
        found.append(("d", f"Run {name} has no computed setup step (it is {row['setup']})."))
    return found


def readiness(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Decide if the nightly run is ready, and say exactly what is missing.

    READY needs the two most recent non-partial runs to satisfy all four:
    (a) they fall on two different UTC dates; (b) neither has a blocking defect;
    (c) both ran all three paths N1, N2 and N3 (an N3 stub is not run), and N4 (the follow
    update) too when the record says an idea was followed. N4 is a fourth path required only if
    follows exist; with none it is "not run: nothing is followed" and does not count against it;
    (d) both have a `computed` rule-test step and a `computed` setup step. `computed` means the
    engine ran and either the first run of the test finished or a recheck (computed again and
    compared with the stored result) matched; a mismatch is a blocking defect, so (b) fails. A run
    where everything was reused is "reused only" and does not qualify. Old records with no
    `evidence` read as `unknown` and never qualify. Partial `--only` runs are ignored.
    """
    last = [r for r in records if not _partial(r)][-2:]
    rows = [_row(r) for r in last]
    missing: list[tuple[str, str]] = []
    if len(rows) < 2:
        missing.append(("a", f"Two runs on two different dates are needed; {len(rows)} found."))
    elif rows[0]["date"] == rows[1]["date"]:
        missing.append(("a", f"Both latest runs are on the same date ({rows[0]['date']})."))
    for row in rows:
        missing.extend(_why_not(row))
    letters = sorted({letter for letter, _ in missing})
    return {
        "ready": not missing,
        "missing": letters,
        "reasons": [f"({letter}) {words}" for letter, words in sorted(missing)],
        "recent": [_row(r) for r in [x for x in records if not _partial(x)][-RECENT:]],
    }


def crontab_line(home: Path, config: Path) -> str:
    alpha = Path(sys.executable).with_name("alpha")
    lock = home / "nightly" / ".lock"
    command = f"{alpha} nightly run --config {config.resolve()}"
    env = f"ALPHA_DATA_DIR={shlex.quote(str(home.resolve()))}"
    return f"{CRON_TIME} {env} flock -n {shlex.quote(str(lock))} {command}"


def _known_config(records: list[dict[str, Any]], fallback: Path) -> Path:
    """The config of the last run that ran all three paths, so its RD-Agent setting is kept."""
    for record in reversed(records):
        if record.get("full") is True and record.get("config_path"):
            return Path(str(record["config_path"]))
    return fallback


def status_facts(home: Path, config: Path) -> dict[str, Any]:
    records = read_records(home)
    full = [r for r in records if not _partial(r)]
    return {
        "last": records[-1] if records else None,
        "records": len(records),
        **readiness(records),
        "rule": RULE,
        "open_defects": full[-1]["defects"] if full else [],
        "crontab_line": crontab_line(home, _known_config(records, config)),
    }


def last_night_line(home: Path) -> str | None:
    records = read_records(home)
    return str(records[-1]["summary_line"]) if records else None


def _row_text(row: dict[str, Any]) -> str:
    ran = "unknown (old record)" if row["paths_run"] is None else ", ".join(row["paths_run"])
    tail = " reused only." if row["reused_only"] else ""
    return (
        f"  {row['run']}: paths run {ran}; computed {row['computed']}, reused {row['reused']}, "
        f"unknown {row['unknown']}; blocking defects {row['blocking']}.{tail}"
    )


def status_text(facts: dict[str, Any]) -> str:
    last = facts["last"]
    if last is None:
        lines = ["No nightly run is recorded yet. Start one with `alpha nightly run`."]
    else:
        lines = [f"{last['summary_line']} (run {last['date']}-{last['run_number']})"]
    lines.append("Latest full-attempt runs (up to 5):")
    lines.extend(_row_text(row) for row in facts["recent"] or [])
    lines.append(f"Ready: {'yes' if facts['ready'] else 'no'}.")
    lines.extend(f"  Missing {reason}" for reason in facts["reasons"])
    lines.append(RULE)
    defects = facts["open_defects"]
    lines.append("Open defects (last full-attempt run): " + ("none." if not defects else ""))
    lines.extend(
        f"  {d['severity']} in {d['step']}: {d['text']}  To reproduce: {d['reproduce']}"
        for d in defects
    )
    lines += [
        "Schedule it yourself. This command installs nothing. One crontab line:",
        f"  {facts['crontab_line']}",
        NEED_DATA,
        TIMING,
    ]
    return "\n".join(lines)
