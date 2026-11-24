"""``fs.py see``: print a capability card's see_it lines; run those that are alpha commands."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path

import capabilities

_METACHARACTERS = frozenset("|&;<>()$`\\*?{}[]~!#\n")
_PLACEHOLDERS = ("…", "—", "...")
_TAIL_LINES = 40
Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def command_of(line: str) -> list[str] | None:
    """The argument list when ``line`` is one runnable alpha command, else None (manual step)."""
    if any(ch in _METACHARACTERS for ch in line) or any(p in line for p in _PLACEHOLDERS):
        return None
    try:
        words = shlex.split(line)
    except ValueError:
        return None
    if words[:3] == ["uv", "run", "alpha"] or words[:1] == ["alpha"]:
        # A trailing comma means prose follows ("alpha a, alpha b"); that is not one command.
        return None if any(w.endswith(",") for w in words) else words
    return None


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)  # env unchanged


def see(root: Path, capability_id: str, *, run: bool, runner: Runner = _run) -> tuple[str, int]:
    """The text to print and the exit code (non-zero when a command ran and failed)."""
    cards = {c.id: c for c in capabilities.load(root).capabilities}
    if capability_id not in cards:
        raise ValueError(f"unknown capability {capability_id!r}; ids are in {capabilities.MAP}")
    out, failed = [f"{capability_id}: {cards[capability_id].name}"], 0
    for line in cards[capability_id].see_it:
        argv = command_of(line)
        if not run or argv is None:
            out.append(f"  {line}" if not run else f"  manual step: {line}")
            continue
        done = runner(argv)
        failed += done.returncode != 0
        tail = (done.stdout + done.stderr).splitlines()[-_TAIL_LINES:]
        out += [f"  $ {shlex.join(argv)}", f"  exit {done.returncode}", *(f"    {t}" for t in tail)]
    return "\n".join(out), 1 if failed else 0
