"""ALPHA's cpcv.py against the AFML worker's label-aware splitter on one-day labels.

With labels lasting one bar, purging by label end removes nothing beyond the test rows, so the
worker's purged combinatorial splits must equal ALPHA's ``combinatorial_purged_splits`` fold for
fold. The worker is its own program; this skips where it is not installed and runs in the
``afml-worker`` job.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from alpha_validation.cpcv import combinatorial_purged_splits

PROGRAM = (
    Path(__file__).resolve().parents[2] / "workers" / "afml" / ".venv" / "bin" / "alpha-afml-worker"
)


@pytest.mark.parametrize(
    ("n", "n_groups", "k", "embargo"), [(103, 5, 2, 2), (120, 6, 1, 0), (250, 8, 3, 5)]
)
def test_one_day_labels_equal_alpha_cpcv(
    tmp_path: Path, n: int, n_groups: int, k: int, embargo: int
) -> None:
    if not PROGRAM.is_file():
        pytest.skip("AFML worker not installed; run `uv sync --locked --project workers/afml`")
    spans = tmp_path / "spans.parquet"
    pl.DataFrame({"start": np.arange(n), "end": np.arange(n)}).write_parquet(spans)
    out = tmp_path / "splits.json"
    done = subprocess.run(
        [str(PROGRAM), "cv", str(spans), "--out", str(out), "--n-groups", str(n_groups),
         "--test-groups", str(k), "--embargo", str(embargo)],
        capture_output=True, text=True, timeout=300, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    worker = json.loads(out.read_text())["splits"]
    alpha = combinatorial_purged_splits(n, n_groups=n_groups, n_test_groups=k, embargo=embargo)
    assert len(worker) == len(alpha)
    for mine, theirs in zip(worker, alpha, strict=True):
        assert tuple(mine["groups"]) == theirs.test_groups
        assert mine["test"] == theirs.test.tolist()
        assert mine["train"] == theirs.train.tolist()
