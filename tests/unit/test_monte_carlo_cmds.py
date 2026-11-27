"""Command-layer Monte Carlo calibration policy tests."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import typer

import alpha_cli.monte_carlo_cmds as monte_carlo_cmds
from alpha_cli import _artifacts, _monte_carlo_sources
from alpha_cli._monte_carlo_frames import _path_frame
from alpha_cli._monte_carlo_sources import (
    _spec_from_validation,
    _verified_forecast_eval,
    _verified_validation_source,
)
from alpha_cli.monte_carlo_cmds import (
    _calibration_assessment,
    _causal_regime_states,
    _project_forecast_path,
)
from alpha_core import DataError
from tests.fixtures.forecast_fixtures import daily_bars


def _manifest(**overrides: float | int) -> dict[str, object]:
    summary: dict[str, float | int] = {
        "n_origins": 20,
        "skill_vs_rw": 0.1,
        "skill_vs_bootstrap": 0.05,
        "coverage50": 0.5,
        "coverage80": 0.8,
        "coverage90": 0.9,
    }
    summary.update(overrides)
    return {"summary_post_cutoff": summary}


def test_kronos_calibration_requires_skill_and_empirical_coverage() -> None:
    assert _calibration_assessment(_manifest())["status"] == "adequate"

    weak = _calibration_assessment(_manifest(coverage80=0.95))
    assert weak["status"] == "weak_or_insufficient"
    assert "70%-90%" in str(weak["reasons"])


def test_kronos_calibration_rejects_sparse_or_baseline_losing_evidence() -> None:
    weak = _calibration_assessment(_manifest(n_origins=4, skill_vs_rw=0.0, skill_vs_bootstrap=-0.1))
    assert weak["status"] == "weak_or_insufficient"
    assert len(weak["reasons"]) == 3


def test_run_resolution_and_path_frames_reject_missing_or_malformed_inputs(
    tmp_path: Path,
) -> None:
    with pytest.raises(DataError, match="was not found"):
        _verified_validation_source(tmp_path, "missing")
    with pytest.raises(DataError, match="was not found"):
        _verified_forecast_eval(tmp_path, "missing", source_manifest={})
    with pytest.raises(DataError, match="two-dimensional"):
        _path_frame((("iid_empirical", np.array([0.1, 0.2])),))
    with pytest.raises(DataError, match="at least one"):
        _path_frame(())


def test_source_contracts_reject_wrong_run_kinds_and_mismatched_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setattr(_artifacts, "find_run_dir", lambda _data_dir, _run_id: run_dir)

    monkeypatch.setattr(
        _artifacts,
        "read_manifest",
        lambda _run_dir: {"command": "backtest_run", "metadata": {"symbol": "SPY"}},
    )
    with pytest.raises(DataError, match="completed validate run"):
        _verified_validation_source(tmp_path, "source")

    monkeypatch.setattr(
        _artifacts,
        "read_manifest",
        lambda _run_dir: {"command": "validate", "metadata": {}},
    )
    with pytest.raises(DataError, match="invalid validation metadata"):
        _verified_validation_source(tmp_path, "source")

    source_manifest = {
        "metadata": {"symbol": "SPY", "snapshot_id": "snapshot-a"},
        "research_cutoff": "2026-01-01T00:00:00Z",
    }
    monkeypatch.setattr(
        _artifacts,
        "read_manifest",
        lambda _run_dir: {"command": "validate"},
    )
    with pytest.raises(DataError, match="completed forecast_eval run"):
        _verified_forecast_eval(tmp_path, "evaluation", source_manifest=source_manifest)

    monkeypatch.setattr(
        _artifacts,
        "read_manifest",
        lambda _run_dir: {
            "command": "forecast_eval",
            "symbol": "QQQ",
            "snapshot_id": "snapshot-a",
            "research_cutoff": "2026-01-01T00:00:00Z",
        },
    )
    with pytest.raises(DataError, match="symbol 'QQQ' differs from source 'SPY'"):
        _verified_forecast_eval(tmp_path, "evaluation", source_manifest=source_manifest)

    with pytest.raises(DataError, match="strategy_params must be a sequence"):
        _spec_from_validation({"metadata": {"strategy_params": {"lookback": 20}}})


def test_classical_command_translates_short_oos_history_to_cli_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = SimpleNamespace(data_dir=tmp_path, random_seed=7)
    manifest = {"metadata": {"symbol": "SPY"}}
    monkeypatch.setattr(monte_carlo_cmds, "AlphaSettings", lambda: settings)
    monkeypatch.setattr(
        monte_carlo_cmds,
        "_verified_validation_source",
        lambda _data_dir, _run_id: (tmp_path / "source", manifest),
    )
    monkeypatch.setattr(
        _artifacts,
        "read_equity",
        lambda _run_dir: [(daily_bars(2)[index].ts, 100.0 + index) for index in range(2)],
    )

    with pytest.raises(typer.BadParameter, match="at least 20 OOS account returns"):
        monte_carlo_cmds.classical(
            from_run="source",
            paths=10,
            regime_window=2,
            min_state_observations=1,
            min_state_transitions=1,
            confidence=0.95,
            seed=7,
        )


def test_causal_regime_classifier_rejects_unfrozen_or_unavailable_history() -> None:
    bars = daily_bars(20)
    with pytest.raises(DataError, match="regime_window"):
        _causal_regime_states(bars, (bars[-1].ts,), train_size=10, window=1)
    with pytest.raises(DataError, match="cannot freeze"):
        _causal_regime_states(bars, (bars[-1].ts,), train_size=4, window=3)
    with pytest.raises(DataError, match="insufficient causal"):
        _causal_regime_states(bars, (bars[-1].ts,), train_size=4, window=2)
    with pytest.raises(DataError, match="absent from source"):
        _causal_regime_states(
            bars,
            (bars[-1].ts + timedelta(days=100),),
            train_size=10,
            window=2,
        )
    with pytest.raises(DataError, match="lacks 2 prior"):
        _causal_regime_states(bars, (bars[1].ts,), train_size=10, window=2)


def test_kronos_projection_rejects_bad_sequences_and_physical_values() -> None:
    timestamp = daily_bars(2)[-1].ts + timedelta(days=1)
    valid = {
        "open": (100.0,),
        "high": (101.0,),
        "low": (99.0,),
        "close": (100.5,),
        "volume": (1_000.0,),
    }
    missing = SimpleNamespace(**{key: value for key, value in valid.items() if key != "volume"})
    with pytest.raises(DataError, match="no valid volume sequence"):
        _project_forecast_path(symbol="SPY", timestamps=(timestamp,), sample=missing, path_index=0)

    non_numeric = SimpleNamespace(**{**valid, "close": (object(),)})
    with pytest.raises(DataError, match="non-numeric"):
        _project_forecast_path(
            symbol="SPY", timestamps=(timestamp,), sample=non_numeric, path_index=1
        )

    bad_price = SimpleNamespace(**{**valid, "open": (0.0,)})
    with pytest.raises(DataError, match="invalid price"):
        _project_forecast_path(
            symbol="SPY", timestamps=(timestamp,), sample=bad_price, path_index=2
        )

    bad_volume = SimpleNamespace(**{**valid, "volume": (float("inf"),)})
    with pytest.raises(DataError, match="invalid volume"):
        _project_forecast_path(
            symbol="SPY", timestamps=(timestamp,), sample=bad_volume, path_index=3
        )


def test_classical_default_is_2000_paths_and_help_names_10000() -> None:
    from typer.testing import CliRunner

    result = CliRunner().invoke(monte_carlo_cmds.monte_carlo_app, ["classical", "--help"])

    assert "2000" in result.output
    assert "10000" in result.output.replace(",", "").replace("_", "")


def test_classical_prints_time_estimate_before_it_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = SimpleNamespace(data_dir=tmp_path, random_seed=7)
    monkeypatch.setattr(monte_carlo_cmds, "AlphaSettings", lambda: settings)

    def refuse(_data_dir: Path, _run_id: str) -> None:
        raise DataError("stop here")

    monkeypatch.setattr(monte_carlo_cmds, "_verified_validation_source", refuse)

    with pytest.raises(typer.BadParameter):
        monte_carlo_cmds.classical(
            from_run="x",
            paths=2000,
            regime_window=63,
            min_state_observations=20,
            min_state_transitions=10,
            confidence=0.95,
            seed=7,
        )

    out = capsys.readouterr().out
    assert "2000 paths" in out
    assert "about" in out
    assert "10000" in out


def _stored_eval(home: Path, run_id: str, symbol: str, snapshot: str) -> None:
    folder = home / "forecast" / run_id
    folder.mkdir(parents=True)
    manifest = {
        "command": "forecast_eval",
        "symbol": symbol,
        "snapshot_id": snapshot,
        "run_id": run_id,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


SOURCE = {"metadata": {"symbol": "SPY", "snapshot_id": "snap1"}}


def test_kronos_help_says_where_the_evaluation_id_comes_from() -> None:
    from typer.testing import CliRunner

    result = CliRunner().invoke(monte_carlo_cmds.monte_carlo_app, ["kronos", "--help"])

    flat = " ".join(result.output.replace("│", " ").split())
    assert "alpha forecast eval <SYMBOL>` first (a few minutes); it prints the id" in flat


def test_one_fitting_evaluation_is_used_by_default(tmp_path: Path) -> None:
    _stored_eval(tmp_path, "e" * 16, "SPY", "snap1")
    _stored_eval(tmp_path, "f" * 16, "QQQ", "snap1")
    _stored_eval(tmp_path, "9" * 16, "SPY", "other")

    assert _monte_carlo_sources._only_fitting_eval(tmp_path, SOURCE) == "e" * 16


@pytest.mark.parametrize("stored", [0, 2])
def test_no_or_several_fitting_evaluations_say_what_to_do(tmp_path: Path, stored: int) -> None:
    for number in range(stored):
        _stored_eval(tmp_path, f"{number}" * 16, "SPY", "snap1")

    with pytest.raises(DataError) as error:
        _monte_carlo_sources._only_fitting_eval(tmp_path, SOURCE)

    said = str(error.value)
    assert "--forecast-eval-run is missing" in said
    if stored == 0:
        assert "alpha forecast eval SPY" in said and "a few minutes" in said
    else:
        assert "2 stored evaluations fit" in said
