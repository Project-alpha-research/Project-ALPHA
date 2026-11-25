"""The Kronos MC calibration answer reports coverage over rolling origins only (bug fix)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import polars as pl
import pytest

from alpha_cli.figures import builders_mcregimes

_PATHS = 123456


def _answer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    rdir = tmp_path / "run"
    rdir.mkdir()
    pl.DataFrame(
        {
            "origin_index": [0, 1, 2, 3],
            "crps": [0.010, 0.012, 0.011, 0.013],
            "crps_rw": [0.015, 0.014, 0.016, 0.015],
            "crps_bootstrap": [0.014, 0.013, 0.015, 0.014],
            "cover50": [True, False, True, False],
            "cover80": [True, True, True, False],
            "cover90": [True, True, True, True],
        }
    ).write_parquet(rdir / "calibration_origins.parquet")
    monkeypatch.setattr(builders_mcregimes, "_mc_path_count", lambda ctx: _PATHS, raising=False)
    captured: dict[str, Any] = {}

    def spec(figure_id: str, **kwargs: Any) -> dict[str, Any]:
        captured["figure_id"] = figure_id
        captured.update(kwargs)
        return captured

    ctx = SimpleNamespace(rdir=rdir, spec=spec)
    builders_mcregimes.kronos_monte_carlo_calibration(ctx)  # type: ignore[arg-type]
    assert captured["figure_id"] == "kronos_monte_carlo_calibration"
    return str(captured["answer"])


def test_coverage_answer_reports_realised_80_coverage_over_rolling_origins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = _answer(tmp_path, monkeypatch)
    assert "80% coverage" in answer
    assert "75" in answer
    assert "4 rolling origins" in answer


def test_coverage_answer_does_not_tie_path_count_to_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = _answer(tmp_path, monkeypatch)
    assert "123,456" not in answer
    assert "123456" not in answer
    assert "paths" not in answer
