"""CI on main runs backend-tests in six shards, combines six for coverage, and loses no test."""

import re
from collections import Counter
from pathlib import Path

import gate_components

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"

# `--shard I/N` where I is either a literal or a GitHub expression such as
# `${{ matrix.shard }}` (spaces inside the braces are allowed), optionally quoted.
SHARD_ARG = re.compile(r"""--shard[ =]+["']?(?:\$\{\{[^}]*\}\}|[^\s/"']+)/(\d+)""")
# Any "<matrix.shard>/N" reference, e.g. the job name "backend-tests (${{ matrix.shard }}/N)".
MATRIX_TOTAL = re.compile(r"matrix\.shard\s*\}\}\s*/\s*(\d+)")
COMBINE = re.compile(r"--shards[ =]+(\d+)")
MATRIX = re.compile(r"shard:\s*\[([^\]]*)\]")


def test_ci_main_runs_backend_tests_in_six_shards_and_combines_six() -> None:
    text = CI.read_text(encoding="utf-8")

    matrices = MATRIX.findall(text)
    assert matrices, "ci.yml has no shard matrix"
    for matrix in matrices:
        assert [int(x) for x in matrix.split(",")] == [1, 2, 3, 4, 5, 6], matrix

    shard_totals = SHARD_ARG.findall(text)
    assert shard_totals, "ci.yml never passes --shard I/N"
    assert set(shard_totals) == {"6"}, shard_totals

    combined = COMBINE.findall(text)
    assert combined, "ci.yml never combines shard coverage"
    assert set(combined) == {"6"}, combined

    totals = MATRIX_TOTAL.findall(text)
    assert totals, "ci.yml never names <matrix.shard>/N"
    assert set(totals) == {"6"}, totals
    assert "four shards" not in text.lower()


def test_six_shards_cover_every_test_file_exactly_once() -> None:
    every = gate_components.shard_paths(ROOT, 1, 1)
    assert every
    counts = Counter(
        path for index in range(1, 7) for path in gate_components.shard_paths(ROOT, index, 6)
    )
    assert set(counts) == set(every)
    assert all(n == 1 for n in counts.values()), [p for p, n in counts.items() if n != 1]
