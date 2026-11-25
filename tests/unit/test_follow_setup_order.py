"""Every test in test_follow_setup.py passes alone and in any order.

Runs the real pytest on that file in subprocesses: in file order, reversed,
shuffled with fixed seeds, and each test on its own.
"""

from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = "tests/unit/test_follow_setup.py"
BASE = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly"]


def _pytest(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*BASE, *args], cwd=ROOT, capture_output=True, text=True, timeout=1800, check=False
    )


def _node_ids() -> list[str]:
    done = _pytest("--collect-only", TARGET)
    assert done.returncode == 0, done.stdout + done.stderr
    ids = [
        line.strip() for line in done.stdout.splitlines() if line.strip().startswith(TARGET + "::")
    ]
    assert len(ids) >= 2, done.stdout
    return ids


def _assert_passes(ids: list[str], label: str) -> None:
    done = _pytest(*ids)
    assert done.returncode == 0, f"{label} failed for order {ids}:\n{done.stdout}\n{done.stderr}"


def test_follow_setup_tests_pass_in_file_order() -> None:
    _assert_passes([TARGET], "file order")


def test_follow_setup_tests_pass_in_reverse_order_shuffled_and_alone() -> None:
    ids = _node_ids()
    failures: list[str] = []

    def check(order: list[str], label: str) -> None:
        done = _pytest(*order)
        if done.returncode != 0:
            failures.append(f"{label}: {order}\n{done.stdout[-3000:]}")

    check(list(reversed(ids)), "reversed")
    for seed in (1, 2, 3):
        order = list(ids)
        random.Random(seed).shuffle(order)
        check(order, f"shuffled seed {seed}")
    for node in ids:
        check([node], "alone")
    assert not failures, "\n\n".join(failures)
