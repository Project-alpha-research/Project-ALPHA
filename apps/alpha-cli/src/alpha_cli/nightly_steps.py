"""One nightly step: run the real `alpha` command in a child process, then classify the result.

No step re-implements what a command does. A step passes, has a minor defect, has a blocking
defect, or was not run. A research verdict such as "not supported" is never a defect.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

PASS = "pass"
MINOR = "defect-minor"
BLOCKING = "defect-blocking"
NOT_RUN = "not-run"
STDERR_LINES = 3
LINE_CHARS = 200


@dataclass(frozen=True)
class Outcome:
    exit_code: int | None  # None: the command timed out or could not start
    stdout: str
    stderr: str
    seconds: float
    timed_out: bool


Runner = Callable[[Sequence[str], float], Outcome]


def _text(raw: str | bytes | None) -> str:
    return raw.decode(errors="replace") if isinstance(raw, bytes) else (raw or "")


def subprocess_runner(argv: Sequence[str], timeout: float) -> Outcome:
    """Run one argument list as a child process. Never raises for a failing command."""
    started = time.monotonic()
    try:
        done = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as error:
        seconds = time.monotonic() - started
        return Outcome(None, _text(error.stdout), _text(error.stderr), seconds, True)
    except OSError as error:
        return Outcome(None, "", str(error), time.monotonic() - started, False)
    return Outcome(done.returncode, done.stdout, done.stderr, time.monotonic() - started, False)


def alpha_argv(tail: Sequence[str]) -> list[str]:
    """The installed command, run through the same interpreter as this process."""
    return [sys.executable, "-m", "alpha_cli.main", *tail]


def command_text(tail: Sequence[str]) -> str:
    return "alpha " + shlex.join(tail)


def stderr_tail(stderr: str) -> str:
    lines = [line.strip()[:LINE_CHARS] for line in stderr.splitlines() if line.strip()]
    return " / ".join(lines[-STDERR_LINES:])


def new_step(step_id: str, scenario: str, name: str, tail: Sequence[str]) -> dict[str, Any]:
    return {
        "id": step_id,
        "scenario": scenario,
        "name": name,
        "command": command_text(tail),
        "state": PASS,
        "exit_code": None,
        "seconds": 0.0,
        "verdict": None,
        "ids": {},
        "note": None,
        "defect": None,
    }


def mark(step: dict[str, Any], state: str, defect: str) -> None:
    """Record a defect. A blocking defect is never downgraded by a later minor one."""
    if step["state"] == BLOCKING and state == MINOR:
        return
    step["state"] = state
    step["defect"] = defect if step["defect"] is None or state == BLOCKING else step["defect"]


def not_run(
    step_id: str, scenario: str, name: str, tail: Sequence[str], because: str
) -> dict[str, Any]:
    step = new_step(step_id, scenario, name, tail)
    step["state"] = NOT_RUN
    step["note"] = because
    return step


def _error_words(payload: object) -> str:
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return f" Error {error.get('code')}: {str(error.get('message', ''))[:LINE_CHARS]}"
    return ""


def parse_object(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def run_step(
    runner: Runner,
    step: dict[str, Any],
    tail: Sequence[str],
    timeout: float,
    *,
    required: Sequence[str] = (),
    expect_json: bool = True,
) -> dict[str, Any] | None:
    """Run the command and fill the step. Returns the printed JSON object, if it printed one."""
    outcome = runner(alpha_argv(tail), timeout)
    step["exit_code"] = outcome.exit_code
    step["seconds"] = round(outcome.seconds, 2)
    command = step["command"]
    payload = parse_object(outcome.stdout) if expect_json else None
    if outcome.timed_out:
        mark(step, BLOCKING, f"`{command}` timed out after {timeout:g} seconds.")
    elif outcome.exit_code != 0:
        words = _error_words(payload) or f" {stderr_tail(outcome.stderr)}"
        mark(step, BLOCKING, f"`{command}` exited {outcome.exit_code}.{words}".rstrip())
    elif expect_json and payload is None:
        mark(step, BLOCKING, f"`{command}` printed no valid JSON object.")
    elif payload is not None:
        missing = [name for name in required if name not in payload]
        if missing:
            mark(step, BLOCKING, f"`{command}` left out: {', '.join(missing)}.")
        elif payload.get("warnings"):
            mark(step, MINOR, f"`{command}` printed a warning: {payload['warnings']}"[:400])
    return payload
