"""Future poison for the AFML worker's events, triple-barrier labels and weights.

Poisoning every bar after a cutoff ``k`` must leave each event found by ``k`` and each label decided
by ``k`` identical (both bases), and must change at least one later output. Non-finite poison must
fail loud. A leaky twin (barrier widths from the whole sample's volatility) must be rejected by the
same predicate. The worker runs as its own program; the root test job does not install it, so this
guard skips there with the reason and runs in the ``afml-worker`` job, which does.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pytest

pytestmark = pytest.mark.bias_guard

WORKER = Path(__file__).resolve().parents[2] / "workers" / "afml"
PROGRAM = WORKER / ".venv" / "bin" / "alpha-afml-worker"
CUTOFFS = (150, 300, 450)
KEYS = ("ts", "pos", "side", "width", "threshold")


def _bars(n: int = 600, seed: int = 20261116) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.011, n)))
    opens = np.concatenate([[100.0], close[:-1]]) * np.exp(rng.normal(0, 0.003, n))
    high = np.maximum(opens, close) * np.exp(np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(opens, close) * np.exp(-np.abs(rng.normal(0, 0.006, n)))
    start = datetime(2020, 1, 1, tzinfo=UTC)
    ts = pl.Series([start + timedelta(days=i) for i in range(n)], dtype=pl.Datetime("us", "UTC"))
    return pl.DataFrame({"ts": ts, "open": opens, "high": high, "low": low, "close": close})


def _poison(bars: pl.DataFrame, k: int, factor: float) -> pl.DataFrame:
    scale = pl.when(pl.int_range(bars.height) > k).then(pl.lit(factor)).otherwise(pl.lit(1.0))
    return bars.with_columns(pl.col(c) * scale for c in ("open", "high", "low", "close"))


def _run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PROGRAM), *map(str, args)], capture_output=True, text=True, timeout=600, check=False
    )


def _labels(bars: pl.DataFrame, tmp: Path, name: str, basis: str) -> pl.DataFrame:
    source, out = tmp / f"{name}.parquet", tmp / f"{name}-{basis}-events.parquet"
    bars.write_parquet(source)
    done = _run("labels", source, "--out", out, "--basis", basis)
    assert done.returncode == 0, done.stderr
    return pl.read_parquet(out)


def _end(basis: str) -> str:
    return "end_pos" if basis == "high_low" else "close_end_pos"


def _decided_by(frame: pl.DataFrame, k: int, basis: str) -> pl.DataFrame:
    return frame.filter((pl.col(_end(basis)) >= 0) & (pl.col(_end(basis)) <= k))


def _causal_up_to(full: pl.DataFrame, other: pl.DataFrame, k: int, basis: str) -> bool:
    """The predicate: events found by k and labels decided by k are identical."""
    found = [f.filter(pl.col("pos") <= k).select(KEYS) for f in (full, other)]
    return found[0].equals(found[1]) and _decided_by(full, k, basis).equals(
        _decided_by(other, k, basis)
    )


@pytest.fixture(scope="module")
def worker() -> Path:
    if not PROGRAM.is_file():
        pytest.skip("AFML worker not installed; run `uv sync --locked --project workers/afml`")
    return PROGRAM


@pytest.mark.parametrize("basis", ["high_low", "close"])
def test_poison_after_cutoff_leaves_earlier_events_and_labels_identical(
    worker: Path, tmp_path: Path, basis: str
) -> None:
    bars = _bars()
    full = _labels(bars, tmp_path, "full", basis)
    for k in CUTOFFS:
        poisoned = _labels(_poison(bars, k, 1.6), tmp_path, f"poison-{k}", basis)
        assert _decided_by(full, k, basis).height > 10
        assert _causal_up_to(full, poisoned, k, basis), f"cutoff {k}"
        later = full.filter(pl.col("pos") > k).select(KEYS)
        assert not later.equals(poisoned.filter(pl.col("pos") > k).select(KEYS)), (
            f"poison after {k} changed nothing later: the guard has no power"
        )


def test_weights_up_to_cutoff_ignore_poisoned_bars(worker: Path, tmp_path: Path) -> None:
    bars, k = _bars(), 300
    cut = bars["ts"][k].isoformat()
    weights = []
    for name, frame in (("clean", bars), ("poisoned", _poison(bars, k, 1.6))):
        source, events, out = (tmp_path / f"{name}-{s}.parquet" for s in ("b", "e", "w"))
        frame.write_parquet(source)
        assert _run("labels", source, "--out", events).returncode == 0
        done = _run("uniqueness", events, "--bars", source, "--out", out, "--train-end", cut)
        assert done.returncode == 0, done.stderr
        assert json.loads(done.stdout)["weights_scope"].startswith("labels ending on or before")
        weights.append(pl.read_parquet(out))
    assert weights[0].height > 10 and weights[0].equals(weights[1])


def test_non_finite_poison_fails_loud(worker: Path, tmp_path: Path) -> None:
    bad = _bars().with_columns(
        pl.when(pl.int_range(600) == 400)
        .then(float("nan"))
        .otherwise(pl.col("close"))
        .alias("close")
    )
    source = tmp_path / "nan.parquet"
    bad.write_parquet(source)
    done = _run("labels", source, "--out", tmp_path / "x.parquet")
    assert done.returncode == 2 and "ContractError" in done.stderr
    assert not (tmp_path / "x.parquet").exists()


def _leaky_twin(bars: pl.DataFrame, horizon: int = 10, mult: float = 2.0) -> pl.DataFrame:
    """Every fifth bar an event; widths from the WHOLE sample's volatility (a look-ahead)."""
    o, hi, lo, c = (bars[name].to_numpy() for name in ("open", "high", "low", "close"))
    width = float(np.std(np.diff(np.log(c))))
    rows = []
    for t in range(25, bars.height - 1, 5):
        entry, end_pos = o[t + 1], -1
        for j in range(t + 1, min(t + horizon, bars.height - 1) + 1):
            if hi[j] >= entry * (1 + mult * width) or lo[j] <= entry * (1 - mult * width):
                end_pos = j
                break
        rows.append({"ts": bars["ts"][t], "pos": t, "side": 1, "width": width,
                     "threshold": width, "end_pos": end_pos})  # fmt: skip
    return pl.DataFrame(rows)


def test_the_predicate_rejects_a_leaky_twin() -> None:
    bars = _bars()
    full = _leaky_twin(bars)
    poisoned = _leaky_twin(_poison(bars, 300, 1.6).with_columns(
        pl.when(pl.int_range(600) == 301).then(pl.col("close") * 1.5).otherwise(pl.col("close"))
    ))  # fmt: skip
    assert not _causal_up_to(full, poisoned, 300, "high_low")
