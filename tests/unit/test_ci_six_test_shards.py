"""CI on main runs the backend tests in six shards, and coverage combines all six."""

import re
from pathlib import Path

import gate_components

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
SHARDS = 6


def _ci() -> str:
    return CI.read_text(encoding="utf-8")


def test_ci_matrix_runs_six_test_shards() -> None:
    text = _ci()
    lists = re.findall(r"^\s*shard:\s*\[([^\]]*)\]", text, flags=re.MULTILINE)
    assert lists, "ci.yml has no shard matrix"
    for raw in lists:
        values = [int(v.strip()) for v in raw.split(",") if v.strip()]
        assert values == list(range(1, SHARDS + 1)), raw
    assert "four shards" not in text.lower()


def test_ci_shard_argument_and_job_name_name_six() -> None:
    text = _ci()
    totals = re.findall(r"\$\{\{\s*matrix\.shard\s*\}\}\s*/\s*(\d+)", text)
    assert totals, "ci.yml never passes the matrix shard as I/N"
    assert all(int(total) == SHARDS for total in totals), totals
    passed = re.findall(r"--shard\s+\$\{\{\s*matrix\.shard\s*\}\}\s*/\s*(\d+)", text)
    assert passed, "ci.yml does not run backend-tests with --shard I/N"
    assert all(int(total) == SHARDS for total in passed), passed


def test_ci_coverage_step_combines_six_shards() -> None:
    counts = re.findall(r"--shards\s+(\d+)", _ci())
    assert counts, "ci.yml has no coverage --shards step"
    assert all(int(count) == SHARDS for count in counts), counts


def test_six_shards_cover_every_test_file_exactly_once() -> None:
    every = gate_components.shard_paths(ROOT, 1, 1)
    assert every
    shards = [gate_components.shard_paths(ROOT, index, SHARDS) for index in range(1, SHARDS + 1)]
    flat = [path for shard in shards for path in shard]
    assert len(flat) == len(set(flat)), "a test file runs in more than one shard"
    assert set(flat) == set(every), "a test file is missing from the six shards"
