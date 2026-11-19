"""`forward/` is one-way: only the modules on `READERS` may touch it.

A new reader (the F2 nightly step, a Today page) is added to `READERS` on purpose, in review.
The guard also catches the cheap ways around a plain name search: the store's file names and
constants, a path glued from parts, and a module that lists every folder of the data directory.
The bare word "forward" as a value (an option priced on a forward) is not a path and is allowed.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = "apps/alpha-cli/src/alpha_cli/"
READERS = frozenset(
    CLI + name
    for name in (
        "follow_cmds.py",
        "follow_store.py",
        "follow_chain.py",
        "follow_journal.py",
        "follow_source.py",
    )
)
STORE_IMPORT = re.compile(r"follow_(store|chain|journal|source)\b")
FORWARD_PATH = re.compile(
    r"""/\s*["']forward["']|["']forward/|/forward/|(Path|joinpath)\([^)\n]*["']forward["']"""
    r"""|["']for["']\s*["']ward["']|journal\.jsonl|follow\.toml"""
    r"""|AlphaFollowV1|\bFOLLOW_DIR\b"""
)
DATA_DIR_SWEEP = re.compile(
    r"\b(home|data_dir)\)?\s*\.\s*(iterdir|rglob)\(|\b(home|data_dir)\.glob\(\s*[\"']\*|"
    r"os\.walk\(\s*(home|data_dir)\b|copytree\(\s*(home|data_dir)\b"
)
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
        if name in READERS:
            continue
        if STORE_IMPORT.search(text):
            found.append(f"{name}: names the follow store")
        if FORWARD_PATH.search(text):
            found.append(f"{name}: opens a path under forward/")
        if DATA_DIR_SWEEP.search(text):
            found.append(f"{name}: lists every folder of the data directory")
    return found


def test_no_module_off_the_reader_list_touches_forward() -> None:
    files = sources()
    scanned = set(files)
    assert all(CLI + name in scanned for name in MUST_SCAN)
    assert any(n.startswith("workers/rdagent/") for n in scanned)
    assert scanned >= READERS
    assert violations(files) == []


def test_the_guard_fails_on_a_forbidden_import_in_a_research_module() -> None:
    fixture = {
        f"{CLI}spine/run.py": "from alpha_cli.follow_store import load_follow\n",
        f"{CLI}spine/ledger.py": "path = home / 'forward' / 'x'\n",
        "workers/rdagent/loop.py": 'p = f"{home}/forward/abc"\n',
        f"{CLI}follow_cmds.py": "from alpha_cli.follow_store import load_follow\n",
        f"{CLI}nightly_steps.py": "p = home / 'forward'\n",
        f"{CLI}spine/ok.py": "forward: bool = False\n",
        f"{CLI}today_page.py": "from alpha_cli.follow_chain import read_entries\n",
        f"{CLI}backup.py": "for p in data_dir.iterdir():\n    copy(p)\n",
        f"{CLI}glued.py": 'p = home / "for" "ward"\n',
        f"{CLI}globbed.py": 'p = home.glob("*/journal.jsonl")\n',
        f"{CLI}constant.py": "from x import FOLLOW_DIR\n",
    }
    assert violations(fixture) == [
        f"{CLI}backup.py: lists every folder of the data directory",
        f"{CLI}constant.py: opens a path under forward/",
        f"{CLI}globbed.py: opens a path under forward/",
        f"{CLI}globbed.py: lists every folder of the data directory",
        f"{CLI}glued.py: opens a path under forward/",
        f"{CLI}nightly_steps.py: opens a path under forward/",
        f"{CLI}spine/ledger.py: opens a path under forward/",
        f"{CLI}spine/run.py: names the follow store",
        f"{CLI}today_page.py: names the follow store",
        "workers/rdagent/loop.py: opens a path under forward/",
    ]
