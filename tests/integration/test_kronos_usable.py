"""The Kronos tools finish on a CPU and explain themselves (synthetic store, stubbed model)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import _forecast, monte_carlo_cmds
from alpha_cli.main import app
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import IdeaSpec
from alpha_core import Bar, DataError
from alpha_data.store import ParquetStore
from alpha_forecast import FakeForecaster, ForecastResult
from tests.fixtures.cli_fixtures import seed_store

runner = CliRunner()
_FAKE = ["--model", "fake"]


def test_estimate_grows_with_rows_and_steps_and_caps_the_window() -> None:
    one = _forecast.estimate_seconds(context=100, horizon=10, rows=1)
    assert one > 0.0
    assert _forecast.estimate_seconds(context=100, horizon=10, rows=4) == pytest.approx(
        4 * one, rel=1e-9, abs=1e-12
    )
    capped = _forecast.estimate_seconds(context=512, horizon=10, rows=1)
    assert capped == pytest.approx(
        _forecast.estimate_seconds(context=600, horizon=10, rows=1), rel=1e-9, abs=1e-12
    )
    assert "minute" in _forecast.say_time(600.0)
    assert "second" in _forecast.say_time(20.0)


def test_fit_context_lowers_a_default_and_names_the_largest_for_an_explicit_value() -> None:
    assert _forecast.fit_context(None, default=400, available=500, what="bars") == (400, None)
    used, note = _forecast.fit_context(None, default=400, available=300, what="bars")
    assert used == 300 and note is not None and "300" in note
    with pytest.raises(DataError, match="largest that works is 300"):
        _forecast.fit_context(400, default=400, available=300, what="bars")


def test_forecast_run_says_the_trading_day_it_used_and_writes_the_picture_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=30)
    args = ["forecast", "run", "SPY", *_FAKE, "--context", "8", "--horizon", "5"]
    result = runner.invoke(app, [*args, "--samples", "20", "--as-of", "2020-03-01"])
    assert result.exit_code == 0, result.output
    assert "2020-03-01 is not a trading day" in result.output
    assert "2020-01-30" in result.output
    pictures = [line for line in result.output.splitlines() if line.strip().startswith("Picture")]
    assert len(pictures) == 2
    for line in pictures:
        assert Path(line.split(": ", 1)[1].strip()).is_file()


def test_forecast_run_with_a_default_context_too_long_uses_the_bars_there_are(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=30)
    result = runner.invoke(app, ["forecast", "run", "SPY", *_FAKE, "--horizon", "3"])
    assert result.exit_code == 0, result.output
    assert "Context lowered from 400 to 30" in result.output
    too_long = runner.invoke(app, ["forecast", "run", "SPY", *_FAKE, "--context", "40"])
    assert too_long.exit_code != 0
    assert "works is 30: use --context 30" in " ".join(too_long.output.split())


def test_forecast_eval_default_is_a_quick_look_and_explains_the_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=200)
    base = ["forecast", "eval", "SPY", *_FAKE, "--context", "8", "--horizon", "4"]
    quick = runner.invoke(app, [*base, "--stride", "4"])
    assert quick.exit_code == 0, quick.output
    assert " 6 origins" in quick.output
    assert "--origins 0" in quick.output
    text = " ".join(quick.output.split())
    assert "Above 0% the model did better" in text
    assert "tomorrow" in text
    full = runner.invoke(app, [*base, "--stride", "4", "--origins", "0"])
    assert full.exit_code == 0, full.output
    assert " 48 origins" in full.output


@pytest.fixture(scope="module")
def stored(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    home = tmp_path_factory.mktemp("kronos_usable") / "home"
    seed_store(home, symbol="SPY", n=700, sigma=0.02)
    ParquetStore(home / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    idea = IdeaSpec.model_validate(
        {"assets": ["SPY"], "rule": {"kind": "ma_cross", "fast": 5, "slow": 20}}
    )
    result = run_idea(idea, home=home, quick=True)["results"][0]
    assert result["error"] is None, result["error"]
    return {"home": str(home), "run": str(result["run_id"])}


@pytest.fixture
def home(stored: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    copy = tmp_path / "home"
    shutil.copytree(stored["home"], copy)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(copy))
    return copy


class _CountingForecaster:
    """The fake model, counting calls: the paths must come from one batched call."""

    def __init__(self) -> None:
        self.calls: list[int] = []
        self._inner = FakeForecaster()

    def forecast(self, bars: Sequence[Bar], **kwargs: Any) -> ForecastResult:
        self.calls.append(int(kwargs["sample_count"]))
        return self._inner.forecast(bars, **kwargs)


def _eval_run(home: Path, *extra: str) -> str:
    evaluation = runner.invoke(
        app,
        [
            "forecast",
            "eval",
            "SPY",
            *_FAKE,
            "--context",
            "8",
            "--horizon",
            "4",
            "--samples",
            "8",
            *extra,
        ],
    )
    assert evaluation.exit_code == 0, evaluation.output
    newest = max((home / "forecast").iterdir(), key=lambda path: path.stat().st_mtime_ns)
    return newest.name


def test_kronos_monte_carlo_batches_paths_over_one_test_window(
    stored: dict[str, str], home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    counting = _CountingForecaster()
    monkeypatch.setattr(monte_carlo_cmds, "_forecaster_factory", lambda **_: counting)
    # The evaluation names a date with no bar after the source's last bar: same bars, accepted.
    eval_run = _eval_run(home, "--as-of", "2023-12-31")
    result = runner.invoke(
        app,
        ["monte-carlo", "kronos", "--from-run", stored["run"], "--forecast-eval-run", eval_run,
         *_FAKE, "--paths", "3"],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert counting.calls == [3]
    assert "Context lowered from 400" in result.output
    assert "--paths 12 takes" in result.output
    manifest = json.loads(
        (
            home / "runs" / result.output.split("-> run ")[1].split(":")[0] / "manifest.json"
        ).read_text()
    )
    source = json.loads((home / "runs" / stored["run"] / "manifest.json").read_text())["metadata"]
    assert manifest["synthetic_tail_horizon"] == source["embargo"] + source["test_size"] + 1
    assert manifest["horizon"] == manifest["built_from"]["n_returns"]
    assert manifest["horizon"] < source["n_bars"] - source["train_size"]


def test_kronos_monte_carlo_explicit_context_too_long_names_the_largest(
    stored: dict[str, str], home: Path
) -> None:
    eval_run = _eval_run(home)
    result = runner.invoke(
        app,
        ["monte-carlo", "kronos", "--from-run", stored["run"], "--forecast-eval-run", eval_run,
         *_FAKE, "--context", "5000"],
    )  # fmt: skip
    assert result.exit_code != 0
    assert ": use --context" in " ".join(result.output.split())
