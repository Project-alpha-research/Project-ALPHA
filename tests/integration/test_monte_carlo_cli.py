"""The four Monte Carlo families read the run that ``alpha test`` stored (rule and owner rule)."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from numpy.typing import NDArray
from typer.testing import CliRunner

from alpha_cli import _artifacts, _runner
from alpha_cli.main import app
from alpha_cli.spine import reserve
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import IdeaSpec
from alpha_core import Bar
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

runner = CliRunner()

# Small windows: an `alpha test` run trains on its warm-up only (20 bars here).
_REGIME = ["--regime-window", "3", "--min-state-observations", "2", "--min-state-transitions", "1"]
_OWNER_RULE = {
    "long_when": [
        {"left": {"indicator": "rsi", "params": [14]}, "op": "<", "right": {"value": 60}},
        {"left": {"source": "close"}, "op": ">", "right": {"indicator": "sma", "params": [20]}},
    ]
}
_BANNED = ("pass", "fail", "clear", "warning")


@pytest.fixture(scope="module")
def stored(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """One home with a synthetic store, a stored rule test and a stored owner-rule test."""
    home = tmp_path_factory.mktemp("mc_tests") / "home"
    seed_store(home, symbol="SPY", n=700, sigma=0.02)
    ParquetStore(home / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    ideas = {
        "rule": {"kind": "ma_cross", "fast": 5, "slow": 20},
        "owner": {"kind": "owner", "spec": _OWNER_RULE},
    }
    ids = {}
    for name, rule in ideas.items():
        idea = IdeaSpec.model_validate({"assets": ["SPY"], "rule": rule})
        result = run_idea(idea, home=home, quick=True)["results"][0]
        assert result["error"] is None, result["error"]
        ids[name] = str(result["run_id"])
    return {"home": str(home), **ids}


@pytest.fixture
def home(stored: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    copy = tmp_path / "home"
    shutil.copytree(stored["home"], copy)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(copy))
    return copy


def _new_run(home: Path, source: str) -> Path:
    (rdir,) = [
        path
        for path in (home / "runs").iterdir()
        if json.loads((path / "manifest.json").read_text())["command"].startswith("monte_carlo")
        and json.loads((path / "manifest.json").read_text())["source_run_id"] == source
    ]
    return rdir


@pytest.mark.parametrize("kind", ["rule", "owner"])
def test_classical_monte_carlo_publishes_three_auditable_families(
    kind: str, stored: dict[str, str], home: Path
) -> None:
    source = stored[kind]
    result = runner.invoke(
        app,
        [
            "monte-carlo",
            "classical",
            "--from-run",
            source,
            "--paths",
            "32",
            "--seed",
            "19",
            *_REGIME,
        ],
    )
    assert result.exit_code == 0, result.output
    assert "iid_empirical" in result.output
    rdir = _new_run(home, source)
    manifest = json.loads((rdir / "manifest.json").read_text())

    assert manifest["command"] == "monte_carlo_classical"
    assert manifest["source_run_id"] == source
    assert {row["family"] for row in manifest["families"]} == {
        "iid_empirical",
        "regime_switching",
        "student_t",
    }
    regime = next(row for row in manifest["families"] if row["family"] == "regime_switching")
    calm, volatile = manifest["regime_diagnostics"]["state_observations"]
    assert regime["caveats"][0].startswith("Causal states: calm")
    assert f"calm {calm} of {manifest['horizon']} OOS returns" in regime["caveats"][0]
    assert f"volatile {volatile} (" in regime["caveats"][0]
    shares = manifest["regime_diagnostics"]["state_shares"]
    assert sum(shares) == pytest.approx(1.0)
    assert shares == pytest.approx([calm / manifest["horizon"], volatile / manifest["horizon"]])
    for family in manifest["families"]:
        line = next(
            line for line in result.output.splitlines() if line.startswith(f"  {family['family']}:")
        )
        assert "median terminal" in line
        assert "P(ruin" in line
    paths = pl.read_parquet(rdir / "paths.parquet")
    metrics = pl.read_parquet(rdir / "path_metrics.parquet")
    assert paths.columns == ["family", "path_index", "step", "account_return"]
    assert paths.height == 3 * 32 * manifest["horizon"]
    assert metrics.height == 3 * 32
    assert (rdir / "regime_diagnostics.parquet").is_file()
    assert (rdir / "report.md").is_file()
    figures = runner.invoke(app, ["figures", "render", rdir.name, "--json"])
    assert figures.exit_code == 0, figures.output
    figure_payload = json.loads(figures.output)
    assert figure_payload["failed"] == []
    assert {row["figure_id"] for row in figure_payload["figures"]} == {
        "monte_carlo_equity_fans",
        "monte_carlo_terminal_returns",
        "monte_carlo_drawdown_ruin",
        "monte_carlo_regimes",
    }


@pytest.mark.parametrize("kind", ["rule", "owner"])
def test_default_options_work_on_a_test_run(kind: str, stored: dict[str, str], home: Path) -> None:
    """The default 63-session regime window is longer than a test run's 20-bar warm-up."""
    result = runner.invoke(
        app, ["monte-carlo", "classical", "--from-run", stored[kind], "--paths", "16"]
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((_new_run(home, stored[kind]) / "manifest.json").read_text())
    source = json.loads((home / "runs" / stored[kind] / "manifest.json").read_text())
    diagnostics = manifest["regime_diagnostics"]
    assert diagnostics["requested_window"] == 63
    assert diagnostics["causal_window"] == min(63, source["metadata"]["train_size"] - 3)


@pytest.mark.parametrize("kind", ["rule", "owner"])
def test_the_paths_come_from_the_stored_run_and_no_held_back_bar(
    kind: str, stored: dict[str, str], home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[datetime | None] = []
    real = _runner.load_bars

    def watch(symbol: str, **kwargs: Any) -> Any:
        seen.append(kwargs.get("as_of"))
        return real(symbol, **kwargs)

    monkeypatch.setattr("alpha_cli.monte_carlo_cmds._runner.load_bars", watch)
    source = stored[kind]
    result = runner.invoke(
        app, ["monte-carlo", "classical", "--from-run", source, "--paths", "16", *_REGIME]
    )
    assert result.exit_code == 0, result.output
    assert seen and all(as_of is not None and as_of <= reserve.CUTOFF for as_of in seen)
    rdir = _new_run(home, source)
    stored_equity = pl.read_parquet(home / "runs" / source / "equity_curve.parquet")
    observed = pl.read_parquet(rdir / "observed_oos.parquet")
    assert observed["equity"].to_list() == stored_equity["equity"].to_list()
    returns = np.asarray(stored_equity["equity"].to_list())
    returns = returns[1:] / returns[:-1] - 1.0
    emissions = pl.read_parquet(rdir / "regime_emissions.parquet")
    assert emissions["account_return"].to_numpy() == pytest.approx(returns, rel=1e-9, abs=1e-12)


@pytest.mark.parametrize("kind", ["rule", "owner"])
def test_the_output_names_the_run_the_period_and_the_counts_without_a_verdict(
    kind: str, stored: dict[str, str], home: Path
) -> None:
    source = stored[kind]
    result = runner.invoke(
        app, ["monte-carlo", "classical", "--from-run", source, "--paths", "16", *_REGIME]
    )
    assert result.exit_code == 0, result.output
    rdir = _new_run(home, source)
    manifest = json.loads((rdir / "manifest.json").read_text())
    equity = pl.read_parquet(home / "runs" / source / "equity_curve.parquet")
    stamps: list[datetime] = equity["ts"].to_list()
    first, last = min(stamps), max(stamps)
    n_trades = pl.read_parquet(home / "runs" / source / "trades.parquet").height
    built = manifest["built_from"]
    assert built["run_id"] == source and built["period"] == "out-of-sample only"
    assert built["first_ts"] == first.isoformat() and built["last_ts"] == last.isoformat()
    assert built["n_returns"] == manifest["horizon"] == equity.height - 1
    assert built["n_trades"] == n_trades
    sentence = (
        f"Built from run {source}, out-of-sample days only, {first.date()} to {last.date()}: "
        f"{manifest['horizon']} daily returns and {n_trades} trades."
    )
    report = (rdir / "report.md").read_text()
    assert sentence in result.output and sentence in report
    for text in (result.output, report):
        words = {word.strip(".,;:()[]|`*-").lower() for word in text.split()}
        assert not words.intersection(_BANNED), words.intersection(_BANNED)


@pytest.mark.parametrize("kind", ["rule", "owner"])
def test_a_run_with_too_few_returns_is_refused_in_plain_words(
    kind: str, stored: dict[str, str], home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = stored[kind]
    real = _artifacts.read_equity  # stored files are hash-bound: cut the reader, not the file
    monkeypatch.setattr(_artifacts, "read_equity", lambda rdir: real(rdir)[:10])
    result = runner.invoke(app, ["monte-carlo", "classical", "--from-run", source])
    assert result.exit_code == 2, result.output
    flat = " ".join(result.output.replace("│", " ").split())
    assert "at least 20" in flat, flat
    assert "has 9" in flat and source in flat


def test_classical_monte_carlo_discloses_imbalanced_regime(
    stored: dict[str, str], home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def imbalanced_states(
        bars: Sequence[Bar],
        return_timestamps: Sequence[datetime],
        *,
        train_size: int,
        window: int,
    ) -> tuple[NDArray[np.int8], float, NDArray[np.float64]]:
        horizon = len(return_timestamps)
        states = np.ones(horizon, dtype=np.int8)
        states[0] = 0
        return states, 0.01, np.full(horizon, 0.02)

    monkeypatch.setattr("alpha_cli.monte_carlo_cmds._causal_regime_states", imbalanced_states)
    source = stored["rule"]
    result = runner.invoke(
        app,
        [
            "monte-carlo", "classical", "--from-run", source, "--paths", "8",
            "--regime-window", "3", "--min-state-observations", "1",
            "--min-state-transitions", "1",
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    rdir = _new_run(home, source)
    manifest = json.loads((rdir / "manifest.json").read_text())
    regime = next(row for row in manifest["families"] if row["family"] == "regime_switching")
    assert regime["status"] != "not_estimable"
    assert manifest["regime_diagnostics"]["state_observations"] == [1, manifest["horizon"] - 1]
    warning = "rest on few observations"
    assert warning in regime["caveats"][1]
    report = (rdir / "report.md").read_text()
    assert f"Regime states: {regime['caveats'][0]} {regime['caveats'][1]}" in report
    assert warning in result.output.splitlines()[-1]


@pytest.mark.parametrize("kind", ["rule", "owner"])
def test_classical_monte_carlo_is_byte_stable_and_stores_seed_and_settings(
    kind: str, stored: dict[str, str], home: Path
) -> None:
    source = stored[kind]
    args = ["monte-carlo", "classical", "--from-run", source, "--paths", "16", *_REGIME]
    first = runner.invoke(app, [*args, "--seed", "7"])
    assert first.exit_code == 0, first.output
    rdir = _new_run(home, source)
    before = {path.name: path.read_bytes() for path in rdir.iterdir()}
    manifest = json.loads((rdir / "manifest.json").read_text())
    assert manifest["master_seed"] == 7
    assert set(manifest["semantic_seeds"]) == {
        "monte_carlo.iid",
        "monte_carlo.regime",
        "monte_carlo.student_t",
    }
    assert (manifest["paths"], manifest["regime_window"], manifest["confidence"]) == (16, 3, 0.95)
    second = runner.invoke(app, [*args, "--seed", "7"])
    assert second.exit_code == 0, second.output
    assert before == {path.name: path.read_bytes() for path in rdir.iterdir()}
    assert second.output == first.output


def test_classical_non_estimable_regime_publishes_fail_contract(
    stored: dict[str, str], home: Path
) -> None:
    source = stored["rule"]
    result = runner.invoke(
        app,
        [
            "monte-carlo", "classical", "--from-run", source, "--paths", "8",
            "--regime-window", "3", "--min-state-observations", "1000",
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    rdir = _new_run(home, source)
    manifest = json.loads((rdir / "manifest.json").read_text())
    assert manifest["status"] == "fail"
    regime = next(row for row in manifest["families"] if row["family"] == "regime_switching")
    assert regime["status"] == "not_estimable"
    assert regime["n_paths"] == 0
    assert regime["terminal_return_q50"] is None
    assert regime["caveats"][0].startswith("state 0 needs at least 1000 observations")
    assert regime["caveats"][1].startswith("Causal states: calm")
    assert f"  regime_switching: not estimable; {regime['caveats'][0]}" in result.output
    assert pl.read_parquet(rdir / "paths.parquet")["family"].unique().sort().to_list() == [
        "iid_empirical",
        "student_t",
    ]


@pytest.mark.parametrize("kind", ["rule", "owner"])
def test_kronos_monte_carlo_replays_fake_ohlcv_paths_through_engine(
    kind: str, stored: dict[str, str], home: Path
) -> None:
    source = stored[kind]
    evaluation = runner.invoke(
        app,
        [
            "forecast", "eval", "SPY", "--model", "fake", "--context", "8", "--horizon", "4",
            "--stride", "4", "--samples", "8",
        ],
    )  # fmt: skip
    assert evaluation.exit_code == 0, evaluation.output
    eval_dir = next((home / "forecast").iterdir())
    kronos_args = [
        "monte-carlo", "kronos", "--from-run", source, "--forecast-eval-run", eval_dir.name,
        "--model", "fake", "--context", "20", "--paths", "2", "--seed", "23",
    ]  # fmt: skip
    result = runner.invoke(app, kronos_args)
    assert result.exit_code == 0, result.output
    rdir = _new_run(home, source)
    manifest = json.loads((rdir / "manifest.json").read_text())
    assert manifest["command"] == "monte_carlo_kronos"
    assert manifest["forecast_eval_run_id"] == eval_dir.name
    assert manifest["model"]["model_id"] == "fake"
    assert manifest["family"]["family"] == "kronos_synthetic"
    assert manifest["status"] == "warning"  # fixture lies wholly before the pretraining cutoff
    synthetic = pl.read_parquet(rdir / "synthetic_bars.parquet")
    paths = pl.read_parquet(rdir / "paths.parquet")
    metrics = pl.read_parquet(rdir / "path_metrics.parquet")
    source_manifest = json.loads((home / "runs" / source / "manifest.json").read_text())
    n_bars = source_manifest["spine"]["data_period"]
    train = source_manifest["metadata"]["train_size"]
    assert synthetic.height == 2 * (source_manifest["metadata"]["n_bars"] - train)
    assert n_bars["last_ts"] <= reserve.CUTOFF.isoformat()
    assert synthetic.select("path_index").n_unique() == 2
    assert paths.height == 2 * manifest["horizon"]
    assert metrics.height == 2
    assert (rdir / "model_diagnostics.json").is_file()
    assert (rdir / "report.md").is_file()
    figures = runner.invoke(app, ["figures", "render", rdir.name, "--json"])
    assert figures.exit_code == 0, figures.output
    figure_payload = json.loads(figures.output)
    assert figure_payload["failed"] == []
    assert {row["figure_id"] for row in figure_payload["figures"]} == {
        "monte_carlo_equity_fans",
        "monte_carlo_terminal_returns",
        "monte_carlo_drawdown_ruin",
        "kronos_monte_carlo_calibration",
    }
    built = manifest["built_from"]
    assert built["run_id"] == source and built["period"] == "out-of-sample only"
    assert f"Built from run {source}, out-of-sample days only" in (rdir / "report.md").read_text()
    for text in (result.output, (rdir / "report.md").read_text()):
        assert not {w.strip(".,;:()|`*-").lower() for w in text.split()} & set(_BANNED)
    before = {path.name: path.read_bytes() for path in rdir.iterdir()}
    repeated = runner.invoke(app, kronos_args)
    assert repeated.exit_code == 0, repeated.output
    assert {path.name: path.read_bytes() for path in rdir.iterdir()} == before
