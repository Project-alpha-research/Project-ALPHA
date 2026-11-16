"""Smoke and contract tests for the installed ``alpha-afml-worker`` program, run as a process."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import polars as pl
import pytest
from shared_fixtures import synthetic_daily_bars


@pytest.fixture
def bars_file(tmp_path: Path) -> Path:
    path = tmp_path / "bars.parquet"
    synthetic_daily_bars().write_parquet(path)
    return path


def run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    program = shutil.which("alpha-afml-worker")
    assert program, "the worker's console script is not installed in this environment"
    return subprocess.run(
        [program, *map(str, args)], capture_output=True, text=True, check=False, timeout=300
    )


def test_capabilities_names_the_pinned_libraries() -> None:
    result = run("capabilities")
    assert result.returncode == 0, result.stderr
    caps = json.loads(result.stdout)
    assert caps["libraries"]["RiskLabAI"] == "3.2.0"
    assert caps["libraries"]["quantowl"] == "0.1.6"
    assert caps["label_bases"] == ["high_low", "close"]


def test_labels_then_uniqueness_end_to_end(tmp_path: Path, bars_file: Path) -> None:
    events = tmp_path / "events.parquet"
    labelled = run("labels", bars_file, "--out", events)
    assert labelled.returncode == 0, labelled.stderr
    summary = json.loads(labelled.stdout)
    assert summary["basis"] == "high_low" and summary["events"] > 50
    assert set(pl.read_parquet(events).columns) >= {"ts", "end", "outcome", "meta_label"}

    weights = tmp_path / "weights.parquet"
    weighted = run("uniqueness", events, "--bars", bars_file, "--out", weights, "--seed", "7")
    assert weighted.returncode == 0, weighted.stderr
    report = json.loads(weighted.stdout)
    assert 0.0 < report["mean_avg_uniqueness"] <= 1.0
    assert report["max_library_gap"] <= 1e-10
    frame = pl.read_parquet(weights)
    assert frame.columns == ["start", "end", "bars", "avg_uniqueness", "decay"]

    close = run("labels", bars_file, "--out", tmp_path / "close.parquet", "--basis", "close")
    assert close.returncode == 0, close.stderr


def test_bad_input_exits_two_with_one_line(tmp_path: Path, bars_file: Path) -> None:
    bad = tmp_path / "bad.parquet"
    pl.read_parquet(bars_file).reverse().write_parquet(bad)
    result = run("labels", bad, "--out", tmp_path / "x.parquet")
    assert result.returncode == 2
    assert result.stderr.startswith("alpha-afml-worker: ContractError")
    assert not (tmp_path / "x.parquet").exists()


def test_weights_up_to_train_end_ignore_every_later_bar(tmp_path: Path, bars_file: Path) -> None:
    """Reviewer finding: decay and uniqueness over the whole file leak later labels into earlier
    weights. With ``train_end`` the weights use only labels that ended by then, so corrupting
    every later bar must leave them unchanged."""
    from alpha_afml_worker.__main__ import run_labels, run_uniqueness
    from alpha_afml_worker.labels import LabelParams

    bars = pl.read_parquet(bars_file)
    k = 300
    train_end = bars["ts"][k]
    corrupted = bars.with_columns(
        pl.when(pl.int_range(bars.height) > k).then(pl.col(c) * 1.37).otherwise(pl.col(c)).alias(c)
        for c in ("open", "high", "low", "close")
    )
    frames = []
    for name, frame in (("full", bars), ("corrupted", corrupted)):
        bars_path, events, weights = (tmp_path / f"{name}-{s}.parquet" for s in "bew")
        frame.write_parquet(bars_path)
        run_labels(bars_path, events, "high_low", LabelParams())
        summary = run_uniqueness(events, bars_path, weights, 0.5, 0, 7, train_end=train_end)
        assert summary["weights_scope"].startswith("labels ending on or before")
        frames.append(pl.read_parquet(weights))
    assert frames[0].height > 20
    assert (frames[0]["end"] <= train_end).all()
    assert frames[0].equals(frames[1])
    whole = run_uniqueness(
        tmp_path / "full-e.parquet", tmp_path / "full-b.parquet", tmp_path / "w.parquet", 0.5, 0, 7
    )
    assert whole["weights_scope"].startswith("every finished label")
