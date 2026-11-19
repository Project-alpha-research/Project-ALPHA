"""`forward/` is one-way: only the follow, today and nightly modules may touch it."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = "apps/alpha-cli/src/alpha_cli/"
ALLOWED = re.compile(r"^apps/alpha-cli/src/alpha_cli/(follow|today|nightly)_[a-z_]*\.py$")
STORE_IMPORT = re.compile(r"follow_(store|journal|source)\b")
FORWARD_PATH = re.compile(r"""["']forward["'/]|/forward/""")
MUST_SCAN = (
    "spine/run.py",
    "spine/ledger.py",
    "spine/diagnose.py",
    "spine/trial_reader.py",
    "spine/setup_trade.py",
    "spine/setup_study.py",
    "tool_cmds.py",
    "scan_cmds.py",
    "rdagent_cmds.py",
)


def sources() -> dict[str, str]:
    roots = [*ROOT.glob("apps/*/src"), *ROOT.glob("packages/*/src"), ROOT / "workers"]
    found: dict[str, str] = {}
    for root in roots:
        for path in root.rglob("*.py"):
            parts = path.relative_to(ROOT).parts
            if any(p in {".venv", "__pycache__", "tests"} for p in parts):
                continue
            found[path.relative_to(ROOT).as_posix()] = path.read_text(encoding="utf-8")
    return found


def violations(files: dict[str, str]) -> list[str]:
    found: list[str] = []
    for name, text in sorted(files.items()):
        if ALLOWED.match(name):
            continue
        if STORE_IMPORT.search(text):
            found.append(f"{name}: names the follow store")
        if FORWARD_PATH.search(text):
            found.append(f"{name}: opens a path under forward/")
    return found


def test_no_module_outside_follow_today_nightly_touches_forward() -> None:
    files = sources()
    scanned = set(files)
    assert all(CLI + name in scanned for name in MUST_SCAN)
    assert any(n.startswith("workers/rdagent/") for n in scanned)
    assert violations(files) == []


def test_the_guard_fails_on_a_forbidden_import_in_a_research_module() -> None:
    fixture = {
        f"{CLI}spine/run.py": "from alpha_cli.follow_store import load_follow\n",
        f"{CLI}spine/ledger.py": "path = home / 'forward' / 'x'\n",
        "workers/rdagent/loop.py": 'p = f"{home}/forward/abc"\n',
        f"{CLI}follow_cmds.py": "from alpha_cli.follow_store import load_follow\n",
        f"{CLI}nightly_steps.py": "p = home / 'forward'\n",
        f"{CLI}spine/ok.py": "forward: bool = False\n",
    }
    assert violations(fixture) == [
        f"{CLI}spine/ledger.py: opens a path under forward/",
        f"{CLI}spine/run.py: names the follow store",
        "workers/rdagent/loop.py: opens a path under forward/",
    ]
