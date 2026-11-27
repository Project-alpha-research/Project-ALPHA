"""`alpha monte-carlo` never reads a bar from the reserved day, whatever its source run recorded.

A source run that held nothing back records the user's cut-off, often none. Bars pulled after it
must not become readable here.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from alpha_cli import _monte_carlo_sources, _runner, monte_carlo_cmds, validate_cmds
from alpha_cli.monte_carlo_cmds import monte_carlo_app
from alpha_cli.spine import reserve
from alpha_core import DataError
from tests.fixtures.reserve_read_fixtures import (
    LONG,
    SHORT,
    Spy,
    watch_loaders,
    write_store,
)

SPEC = ["--lookback", "20", "--skip", "1", "--vol-window", "10", "--rebalance-every", "5"]
WALK = ["--train-size", "300", "--test-size", "60", "--embargo", "2"]
VALIDATE = ["SPY", *SPEC, *WALK, "--tier1-paths", "30", "--tier2-paths", "3"]
VALIDATE += ["--tier3-paths", "3", "--n-resamples", "100"]


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    return watch_loaders(monkeypatch)


def _validation_run(home: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A validation run made on a store that holds nothing from the reserved day."""
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    root = typer.Typer()
    root.command("validate")(validate_cmds.validate)
    root.command("other")(lambda: None)
    result = CliRunner().invoke(root, ["validate", *VALIDATE])
    assert result.exit_code == 0, result.output
    (path,) = sorted((home / "runs").glob("*/manifest.json"))
    manifest: dict[str, Any] = json.loads(path.read_text())
    assert manifest.get("research_cutoff") is None and "reserve" not in manifest
    return str(manifest["run_id"])


def test_classical_reads_no_bar_the_source_run_could_not_have_seen(
    tmp_path: Path, spy: Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    write_store(home, SHORT, poisoned=False)
    run_id = _validation_run(home, monkeypatch)
    write_store(home, LONG, poisoned=True)  # a later pull adds bars from the reserved day on
    result = CliRunner().invoke(
        monte_carlo_app, ["classical", "--from-run", run_id, "--paths", "200", "--seed", "7"]
    )
    assert result.exit_code == 0, result.output
    spy.assert_nothing_from_the_reserved_day()


def test_kronos_reads_with_the_reserve_cutoff_when_the_source_recorded_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest: dict[str, Any] = {
        "metadata": {"symbol": "SPY", "snapshot_id": None},
        "research_cutoff": None,
    }
    eval_manifest: dict[str, Any] = {"research_cutoff": None}
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        monte_carlo_cmds, "_verified_validation_source", lambda *_a: (tmp_path, manifest)
    )
    monkeypatch.setattr(
        _monte_carlo_sources, "_verified_forecast_eval", lambda *_a, **_k: (tmp_path, eval_manifest)
    )
    asked: list[datetime | None] = []

    def stop(*_args: Any, **kwargs: Any) -> Any:
        asked.append(kwargs["as_of"])
        raise DataError("stop after the first read")

    monkeypatch.setattr(_runner, "load_bars", stop)
    with pytest.raises(typer.BadParameter, match="stop after the first read"):
        monte_carlo_cmds.kronos(from_run="r", forecast_eval_run="e", seed=7)
    assert asked == [reserve.CUTOFF]


def test_a_source_cutoff_before_the_reserve_cutoff_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest: dict[str, Any] = {"metadata": {"symbol": "SPY", "snapshot_id": None}}
    manifest["research_cutoff"] = "2023-06-30"
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        monte_carlo_cmds, "_verified_validation_source", lambda *_a: (tmp_path, manifest)
    )
    monkeypatch.setattr(
        _monte_carlo_sources,
        "_verified_forecast_eval",
        lambda *_a, **_k: (tmp_path, {"research_cutoff": "2023-06-30"}),
    )
    asked: list[datetime | None] = []

    def stop(*_args: Any, **kwargs: Any) -> Any:
        asked.append(kwargs["as_of"])
        raise DataError("stop")

    monkeypatch.setattr(_runner, "load_bars", stop)
    with pytest.raises(typer.BadParameter):
        monte_carlo_cmds.kronos(from_run="r", forecast_eval_run="e", seed=7)
    assert asked == [_runner.parse_as_of("2023-06-30")]
