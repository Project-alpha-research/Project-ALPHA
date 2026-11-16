"""ALPHA's PSR, DSR and PBO beside RiskLabAI's and quantowl's, from the AFML worker.

ALPHA's values stay the record. Every difference must be one of the named causes:
RiskLabAI's expected-maximum Sharpe uses the population (ddof=0) spread of the trial Sharpes,
ALPHA and quantowl the sample (ddof=1) spread. Everything else must agree to 1e-8. Skips where
the worker is not installed; runs in the ``afml-worker`` job.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import numpy as np
import pytest

from alpha_validation.dsr import deflated_sharpe, probabilistic_sharpe_ratio
from alpha_validation.overfitting import probability_of_backtest_overfitting

PROGRAM = (
    Path(__file__).resolve().parents[2] / "workers" / "afml" / ".venv" / "bin" / "alpha-afml-worker"
)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_alpha_and_both_libraries(tmp_path: Path, seed: int) -> None:
    if not PROGRAM.is_file():
        pytest.skip("AFML worker not installed; run `uv sync --locked --project workers/afml`")
    rng = np.random.default_rng(seed)
    returns = rng.standard_t(4, 750) * 0.01 + 0.0005  # fat tails, so skew and kurtosis matter
    trials = rng.normal(0.02, 0.03, 25)
    matrix = rng.normal(0.0, 0.01, (803, 8))  # 803 rows: the trailing 3 are dropped by all
    spec = tmp_path / "in.json"
    spec.write_text(json.dumps({"returns": returns.tolist(), "trial_sharpes": trials.tolist(),
                                "matrix": matrix.tolist(), "n_partitions": 16}))  # fmt: skip
    out = tmp_path / "out.json"
    done = subprocess.run([str(PROGRAM), "stats", str(spec), "--out", str(out)],
                          capture_output=True, text=True, timeout=300, check=False)  # fmt: skip
    assert done.returncode == 0, done.stderr
    report = json.loads(out.read_text())
    sharpe, q, r = report["sharpe"], report["sharpe"]["quantowl"], report["sharpe"]["risklabai"]

    alpha = deflated_sharpe(returns, trial_sharpes=trials)
    assert sharpe["sharpe"] == pytest.approx(alpha.sharpe, abs=1e-12)
    assert q["psr"] == pytest.approx(alpha.psr, abs=1e-8)
    assert r["psr"] == pytest.approx(alpha.psr, abs=1e-8)
    assert q["expected_max_sharpe"] == pytest.approx(alpha.expected_max_sharpe, abs=1e-12)
    assert q["dsr"] == pytest.approx(alpha.dsr, abs=1e-8)
    n = trials.size  # RiskLabAI: ddof=0 spread, the one named cause of a different DSR
    assert r["expected_max_sharpe"] == pytest.approx(
        alpha.expected_max_sharpe * math.sqrt((n - 1) / n), rel=1e-12
    )
    assert r["dsr"] == pytest.approx(
        probabilistic_sharpe_ratio(returns, benchmark_sr=r["expected_max_sharpe"]), abs=1e-8
    )

    alpha_pbo = probability_of_backtest_overfitting(matrix, n_blocks=16)
    assert report["pbo"]["rows_used"] == 800
    for library in ("quantowl", "risklabai"):
        assert report["pbo"][library]["pbo"] == pytest.approx(alpha_pbo.pbo, abs=1e-12)
        assert np.allclose(report["pbo"][library]["logits"], alpha_pbo.logits, atol=1e-10)
