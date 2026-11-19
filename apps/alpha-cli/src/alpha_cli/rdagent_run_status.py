"""Read one RD-Agent run folder and say, in plain words, where the run is. Read-only."""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from alpha_cli.rdagent_discussion import closed, round_folders

STATE_WORDS = {
    "running": "The run is working.",
    "waiting": "The run is waiting for your answer.",
    "finished": "The run finished.",
    "stopped": "The run stopped.",
}


class NotARunFolder(ValueError):
    """The folder holds no RD-Agent launch record."""


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_bytes())
    return value if isinstance(value, dict) else {}


def _loop_n(run: Path) -> int | None:
    argv = _json(run / "launch-command.json").get("argv", [])
    for index, arg in enumerate(argv[:-1]):
        if arg == "--loop-n" and argv[index + 1].isdigit():
            return int(argv[index + 1])
    return None


def _usage(run: Path, folders: list[Path]) -> tuple[Any, Any, Any]:
    """Calls used, calls cap and dollars spent, from what the run stored; None when not stored."""
    receipt = _json(run / "receipt.json")
    this_run = (receipt.get("gateway_status") or {}).get("this_run") or {}
    used = this_run.get("counted_calls", this_run.get("calls"))
    usage = receipt.get("discussion_usage") or {}
    cap = usage.get("chat_cap")
    spent = this_run.get("usd")
    if used is None and folders:
        left = _json(folders[0] / "proposal.json").get("remaining") or {}
        used = left.get("chat_used")
    return used, cap, spent


def _state(run: Path, status: dict[str, Any], folders: list[Path]) -> tuple[str, str | None]:
    receipt = _json(run / "receipt.json")
    if receipt:
        reason = receipt.get("loop_reason")
        return ("finished" if receipt.get("exit_status") == 0 else "stopped"), reason
    if status.get("state") == "stopped":
        return "stopped", "the wait for your answer ended and the run was set to stop"
    if status.get("state") == "waiting" and folders and closed(run, folders[0]) is None:
        return "waiting", None
    return "running", None


def read_status(run: Path) -> dict[str, Any]:
    """Stable keys; values are None when the run folder does not store them."""
    if not (run / "launch-command.json").is_file():
        raise NotARunFolder(f"{run} is not an RD-Agent run folder (it has no launch record).")
    status = _json(run / "discussion" / "status.json")
    folders = round_folders(run)
    state, reason = _state(run, status, folders)
    number = status.get("round")
    used, cap, spent = _usage(run, folders)
    quoted = shlex.quote(str(run))
    commands = {
        "waiting": f"alpha ledger proposal --run-dir {quoted}",
        "running": f"alpha rdagent status --run-dir {quoted}",
        "finished": f"alpha ledger proposal --run-dir {quoted} --last-decision",
        "stopped": f"alpha ledger proposal --run-dir {quoted}",
    }
    return {
        "run_dir": str(run),
        "state": state,
        "state_words": STATE_WORDS[state],
        "round": number + 1 if isinstance(number, int) else None,
        "rounds_total": status.get("rounds_total") or _loop_n(run),
        "calls_used": used,
        "calls_cap": cap,
        "usd_spent": spent,
        "reason": reason,
        "next_command": commands[state],
    }


def status_text(value: dict[str, Any]) -> str:
    lines = [value["state_words"]]
    if value["reason"]:
        lines.append(f"Why: {value['reason']}")
    if value["round"] is not None:
        lines.append(f"Round {value['round']} of {value['rounds_total'] or 'an unknown number'}.")
    if value["calls_used"] is not None:
        cap = f" of {value['calls_cap']}" if value["calls_cap"] is not None else ""
        spend = f", ${value['usd_spent']:.2f} spent" if value["usd_spent"] is not None else ""
        lines.append(f"Model calls so far: {value['calls_used']}{cap}{spend}.")
    lines += [f"Run folder: {value['run_dir']}", f"Next: {value['next_command']}"]
    return "\n".join(lines)
