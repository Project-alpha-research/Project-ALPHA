"""N4 (follow update) and the steps around it. Each step is the real `alpha follow` command.

N4 runs only when an idea is followed; when none is, it is recorded "not run: nothing is followed"
and does not count as a path. This module reads no journal itself: it calls `alpha follow list`,
`update --all`, `today` and `verify` as child commands. The third anchor: each night the record
keeps every journal's entry count and chain head (as `verify` reports them). The next night the
journal's entry at the old count must still have the old hash. Else history was rewritten.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from alpha_cli.nightly_config import NightlyConfig
from alpha_cli.nightly_refresh import refresh_assets
from alpha_cli.nightly_status import read_records
from alpha_cli.nightly_steps import (
    BLOCKING,
    MINOR,
    NOT_RUN,
    PASS,
    Runner,
    mark,
    new_step,
    not_run,
    run_step,
)

CHANGED = "journal history changed since the last nightly record"
WAIT = "not run: step N4.list failed"


def _rows(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
    listed = payload.get(key) if payload else None
    return [r for r in listed if isinstance(r, dict)] if isinstance(listed, list) else []


def _list(config: NightlyConfig, runner: Runner) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tail = ["follow", "list", "--json"]
    step = new_step("N4.list", "N4", "follow list", tail)
    payload = run_step(runner, step, tail, config.step_timeout, required=("follows",))
    rows = _rows(payload, "follows") if step["state"] == PASS else []
    if step["state"] == PASS and not [r for r in rows if r.get("state") != "stopped"]:
        step["state"], step["note"] = NOT_RUN, "not run: nothing is followed"
    return step, rows


def previous_heads(home: Path) -> dict[str, dict[str, Any]]:
    """The chain heads of the newest earlier record that has any."""
    for record in reversed(read_records(home)):
        heads = record.get("follow_heads")
        if isinstance(heads, dict) and heads:
            return {str(k): v for k, v in heads.items() if isinstance(v, dict)}
    return {}


def _verify(
    config: NightlyConfig, runner: Runner, row: dict[str, Any], old: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    follow = str(row["follow_id"])
    tail = [
        "follow",
        "verify",
        follow,
        "--json",
        *(["--entry", str(old["entries"])] if old else []),
    ]
    step = new_step(f"N4.verify.{follow}", "N4", f"follow verify {follow}", tail)
    got = run_step(runner, step, tail, config.step_timeout, required=("ok", "entries", "head"))
    if got is not None and got.get("ok") is not True:
        broke = got.get("first_break") or {}
        mark(
            step,
            BLOCKING,
            f"follow {follow} failed verify at entry {broke.get('seq')}: {broke.get('reason')}",
        )
    if got is None or step["state"] == BLOCKING:
        return step, old
    at = got.get("at_entry") or {}
    if old and (got["entries"] < old["entries"] or at.get("entry_hash") != old["head"]):
        mark(
            step,
            BLOCKING,
            f"{CHANGED}: follow {follow} no longer has entry {old['entries']} "
            f"with hash {old['head'][:12]}.",
        )
        return step, old
    return step, {"entries": got["entries"], "head": got["head"]}


def _late(rows: list[dict[str, Any]]) -> str:
    return ", ".join(str(r.get("follow_id")) for r in rows if r.get("group") == "late_or_missed")


def follow_path(
    config: NightlyConfig,
    runner: Runner,
    listed: dict[str, Any],
    rows: list[dict[str, Any]],
    old: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    steps = [listed]
    if listed["state"] == NOT_RUN:
        return steps, {}
    ut, tt = ["follow", "update", "--all", "--json"], ["follow", "today", "--json"]
    if listed["state"] != PASS:
        steps += [
            not_run("N4.update", "N4", "follow update", ut, WAIT),
            not_run("N4.today", "N4", "follow today", tt, WAIT),
        ]
        return steps, {}
    update = new_step("N4.update", "N4", "follow update", ut)
    got = run_step(runner, update, ut, config.step_timeout, required=("follows",))
    results = _rows(got, "follows")
    refused = [
        f"{r.get('follow_id')} {r.get('code')}" for r in results if r.get("status") == "refused"
    ]
    if refused:
        mark(update, BLOCKING, f"`{update['command']}` refused: {', '.join(refused)}.")
    off = [
        str(r.get("follow_id")) for r in results if (r.get("replay") or {}).get("agrees") is False
    ]
    if off:
        mark(update, MINOR, f"The replay check does not agree for follow {', '.join(off)}.")
    today = new_step("N4.today", "N4", "follow today", tt)
    shown = run_step(
        runner, today, tt, config.step_timeout, required=("as_of", "groups", "rows", "behind")
    )
    if late := _late(_rows(shown, "rows")):
        mark(today, MINOR, f"The newest entry is late or missed (or absent) for follow {late}.")
    steps += [update, today]
    heads: dict[str, dict[str, Any]] = {}
    for row in rows:
        step, head = _verify(config, runner, row, old.get(str(row["follow_id"])))
        steps.append(step)
        if head:
            heads[str(row["follow_id"])] = head
    for gone in sorted(set(old) - {str(r["follow_id"]) for r in rows}):
        lost = new_step(
            f"N4.verify.{gone}", "N4", f"follow verify {gone}", ["follow", "verify", gone]
        )
        mark(lost, BLOCKING, f"{CHANGED}: follow {gone} is gone.")
        steps.append(lost)
        heads[gone] = old[gone]
    return steps, heads


def follow_steps(
    config: NightlyConfig, home: Path, runner: Runner, wanted: tuple[str, ...], day: date
) -> tuple[list[dict[str, Any]], int | None, dict[str, dict[str, Any]]]:
    """The N0 and N4 steps, the number of active follows, and this night's chain heads."""
    if not {"N0", "N4"} & set(wanted):
        return [], None, {}
    listed, rows = _list(config, runner)
    active = [r for r in rows if r.get("state") != "stopped"]
    steps: list[dict[str, Any]] = []
    if "N0" in wanted:
        if not config.refresh_followed:
            steps.append(
                not_run(
                    "N0.stub",
                    "N0",
                    "refresh bars",
                    ["data", "pull"],
                    "not run: `refresh_followed` is off",
                )
            )
        elif listed["state"] == PASS:
            assets = list(
                dict.fromkeys(
                    str(a)
                    for r in active
                    if r.get("state") != "broken"
                    for a in r.get("assets", [])
                )
            )
            steps += refresh_assets(config, home, runner, assets, day)
        else:
            steps.append(not_run("N0.stub", "N0", "refresh bars", ["data", "pull"], WAIT))
    heads: dict[str, dict[str, Any]] = {}
    if "N4" in wanted:
        more, heads = follow_path(config, runner, listed, rows, previous_heads(home))
        steps += more
    return steps, (len(active) if listed["state"] in (PASS, NOT_RUN) else None), heads
