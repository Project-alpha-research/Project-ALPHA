"""A full rule test gives the same stored numbers with one worker and with three.

The null paths, the price-noise copies and the variants are drawn in the parent from fixed seeds
and scored in order, so neither the worker count nor the order the workers finish in may move a
number.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from alpha_cli import _gauntlet
from alpha_cli.spine import run
from alpha_cli.spine.recheck_compare import compare_runs
from alpha_cli.spine.spec import load_spec
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store


def _run(root: Path, workers: int, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = root / f"home-{workers}"
    seed_store(home, symbol="SPY", n=900)
    ParquetStore(home / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    small = replace(
        _gauntlet.GauntletParams(seed=7),
        tier1_paths=40,
        tier2_paths=6,
        tier3_paths=6,
        n_resamples=60,
        max_workers=workers,
    )
    monkeypatch.setattr(run, "gauntlet_knobs", lambda seed, quick: small)
    idea = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    result = run.run_idea(idea, home=home)["results"][0]
    assert result["error"] is None, result["error"]
    return Path(result["run_dir"])


def test_one_and_three_workers_store_byte_identical_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    serial = _run(tmp_path, 1, monkeypatch)
    pooled = _run(tmp_path, 3, monkeypatch)
    assert serial.name == pooled.name  # the worker count is not part of a run's identity
    compared = compare_runs(serial, pooled)
    assert compared.differences == []
    assert compared.bit_identical
    for name in ("diagnostics.json", "spec.json"):
        # The only allowed difference is the home folder named in a "not installed" note.
        pooled_text = (pooled / name).read_text().replace("home-3", "home-1")
        assert (serial / name).read_text() == pooled_text
