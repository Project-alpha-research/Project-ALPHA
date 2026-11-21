"""`alpha forecast eval` holds the reserved period back; `forecast run` is forward use."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import _runner, forecast_cmds
from alpha_cli.control_store import ControlStore
from alpha_cli.main import app
from alpha_core import Bar
from alpha_core.reserve import RESERVED_DAY, RESERVED_INSTANT, RESERVED_START
from alpha_data.snapshot import create_snapshot
from alpha_data.store import ParquetStore
from alpha_research import MarketStateContractV1
from alpha_validation import ForecastCalibrationContractV1
from tests.fixtures.cli_fixtures import seed_store
from tests.fixtures.control_store_fixtures import mark_project_as_migrated_legacy

runner = CliRunner()
START = date(2020, 1, 1)
CUT_N = (RESERVED_DAY - START).days  # the first bars stamped before the reserved day
EXTRA = 60
SENTENCE = f"Held back {EXTRA} bars from {RESERVED_START} on"
EVAL = ["forecast", "eval", "SPY", "--model", "fake", "--context", "8", "--horizon", "4"]
EVAL += ["--stride", "40", "--samples", "8"]


class Spy:
    """The latest bar each stored-bar read returned."""

    def __init__(self) -> None:
        self.latest: list[datetime] = []


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    seen = Spy()
    load_bars = _runner.load_bars

    def bars(*args: Any, **kwargs: Any) -> tuple[list[Bar], str | None]:
        result = load_bars(*args, **kwargs)
        seen.latest.append(max(bar.ts for bar in result[0]))
        return result

    monkeypatch.setattr(forecast_cmds, "_load_bars", bars)
    return seen


def _plain(home: Path, n: int, *, poisoned: bool) -> None:
    seed_store(home, symbol="SPY", n=n)
    if not poisoned:
        return
    store = ParquetStore(home / "store")
    late = pl.col("ts").dt.date() >= RESERVED_DAY
    frame = store.read_bars("SPY")
    store.write_bars(
        "SPY",
        frame.with_columns(
            [
                pl.when(late).then(pl.col(c) * 1000.0).otherwise(pl.col(c)).alias(c)
                for c in ("open", "high", "low", "close")
            ]
        ),
    )


def _eval(home: Path, monkeypatch: pytest.MonkeyPatch, *extra: str) -> tuple[str, dict[str, Any]]:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    result = runner.invoke(app, [*EVAL, *extra])
    assert result.exit_code == 0, result.output
    run_id = result.output.split("-> run ")[1].split(":")[0]
    manifest: dict[str, Any] = json.loads(
        (home / "forecast" / run_id / "manifest.json").read_text()
    )
    return result.output, manifest


def _origins(home: Path, manifest: dict[str, Any]) -> pl.DataFrame:
    return pl.read_parquet(home / "forecast" / manifest["run_id"] / "origins.parquet")


def test_a_poisoned_store_scores_like_a_store_cut_at_the_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spy: Spy
) -> None:
    _plain(tmp_path / "held", CUT_N + EXTRA, poisoned=True)
    _plain(tmp_path / "cut", CUT_N, poisoned=False)
    _, held = _eval(tmp_path / "held", monkeypatch)
    _, plain = _eval(tmp_path / "cut", monkeypatch)
    assert _origins(tmp_path / "held", held).equals(_origins(tmp_path / "cut", plain))
    assert held["summary"] == plain["summary"]
    assert held["origins"] == plain["origins"]


def test_no_bar_on_or_after_the_boundary_is_read_and_the_sentence_is_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spy: Spy
) -> None:
    _plain(tmp_path, CUT_N + EXTRA, poisoned=True)
    output, manifest = _eval(tmp_path, monkeypatch)
    assert spy.latest and max(spy.latest) < RESERVED_INSTANT
    assert SENTENCE in output
    assert manifest["research_cutoff"] == "2023-12-31"
    assert manifest["reserve"] == {"reserved_start": RESERVED_START, "held_back_bars": EXTRA}
    assert "reserved-period-held-back" in manifest["labels"]


def test_a_store_with_no_held_back_bar_keeps_its_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spy: Spy
) -> None:
    _plain(tmp_path, CUT_N, poisoned=False)
    output, manifest = _eval(tmp_path, monkeypatch)
    assert "Held back" not in output
    assert manifest["research_cutoff"] is None
    assert "reserve" not in manifest and "labels" not in manifest
    # The run id also hashes the code, so it cannot be pinned across commits; the identity payload
    # is the old one when no bar is held back (research_cutoff None, no hold-back record).
    assert max(spy.latest) == datetime(2023, 12, 31, tzinfo=UTC)


def test_an_earlier_user_cutoff_works_and_a_later_one_is_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spy: Spy
) -> None:
    _plain(tmp_path, CUT_N + EXTRA, poisoned=True)
    output, manifest = _eval(tmp_path, monkeypatch, "--as-of", "2023-06-30")
    assert "Held back" not in output
    assert manifest["research_cutoff"] == "2023-06-30"
    assert max(spy.latest) <= datetime(2023, 6, 30, 23, 59, 59, tzinfo=UTC)
    spy.latest.clear()
    output, manifest = _eval(tmp_path, monkeypatch, "--as-of", "2024-02-01")
    held = (date(2024, 2, 1) - RESERVED_DAY).days + 1
    assert f"Held back {held} bars" in output
    assert manifest["research_cutoff"] == "2023-12-31"
    assert max(spy.latest) < RESERVED_INSTANT


def _sessions(extra: int) -> list[datetime]:
    """Weekday stamps from 2020-01-01: all those before the reserved day, then `extra` more."""
    days = [START + timedelta(days=i) for i in range((RESERVED_DAY - START).days + 4 * extra)]
    weekdays = [d for d in days if d.weekday() < 5]
    before = sum(1 for d in weekdays if d < RESERVED_DAY)
    return [
        datetime.combine(d, datetime.min.time(), tzinfo=UTC) for d in weekdays[: before + extra]
    ]


def _governed_world(root: Path, extra: int) -> tuple[str, str]:
    stamps = _sessions(extra)
    total = len(stamps)
    poison_from = sum(1 for stamp in stamps if stamp.date() < RESERVED_DAY) if extra else None
    store = ParquetStore(root / "store")
    for offset, symbol in enumerate(("AAPL", "SPY")):
        rng = np.random.default_rng(10 + offset)
        closes = 100.0 * np.cumprod(1.0 + 0.001 + rng.normal(0.0, 0.01, total))
        if poison_from is not None:
            closes[poison_from:] *= 1000.0
        store.write_bars(
            symbol,
            pl.DataFrame(
                {
                    "ts": stamps,
                    "open": closes,
                    "high": closes * 1.01,
                    "low": closes * 0.99,
                    "close": closes,
                    "volume": [1_000_000.0] * total,
                }
            ),
        )
    create_snapshot(
        store,
        root / "snapshots",
        "governed-forecast",
        ["AAPL", "SPY"],
        source="fixture",
        adapter_version="1",
        parser_version="1",
        created_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    control = ControlStore(root)
    project = control.create_project(
        name="Governed Kronos calibration",
        hypothesis="Calibrated forecasts conditionally clear their frozen hurdle.",
        falsification_criterion="Reject when calibrated OOS skill or coverage misses its floor.",
        at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    project_id = str(project["project_id"])
    mark_project_as_migrated_legacy(control, project_id)
    version = control.create_strategy_version(
        project_id,
        strategy_name="kronos_calibrated",
        source_fingerprint="git:test",
        definition={"authority": "research_candidate_only"},
        parameter_space={},
    )
    market = MarketStateContractV1(
        universe=("AAPL", "SPY"),
        benchmark="SPY",
        calendar="equity",
        volatility_window=3,
        trend_window=3,
        correlation_window=3,
        annualization_sessions=252,
        volatility_thresholds=(0.10, 0.25),
        trend_threshold=0.01,
        breadth_thresholds=(0.25, 0.75),
        correlation_thresholds=(0.25, 0.75),
        minimum_state_samples=3,
    )
    calibration = ForecastCalibrationContractV1(
        coverage_level=0.8,
        residual_window=4,
        blend_weights=(0.0, 0.5, 1.0),
        minimum_validation_origins=8,
        minimum_empirical_coverage=0.5,
        minimum_edge=0.0,
        maximum_interval_width=1.0,
        minimum_state_samples=3,
    )
    experiment = control.create_experiment_spec(
        project_id,
        strategy_version_id=str(version["version_id"]),
        snapshot_id="governed-forecast",
        universe=["AAPL", "SPY"],
        split_policy={"validation": 16, "test": 32},
        costs={"fee_bps": 1.0, "slippage_bps": 2.0},
        seeds={"master": 7},
        stage_config={
            "market_state": market.to_dict(),
            "kronos_calibration": calibration.to_dict(),
        },
    )
    return project_id, str(experiment["experiment_id"])


def test_the_governed_path_cuts_every_universe_symbol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spy: Spy
) -> None:
    held_ids = _governed_world(tmp_path / "held", EXTRA)
    plain_ids = _governed_world(tmp_path / "cut", 0)
    outputs: list[tuple[str, dict[str, Any]]] = []
    for name, (project_id, experiment_id) in (("held", held_ids), ("cut", plain_ids)):
        spy.latest.clear()
        outputs.append(
            _eval(
                tmp_path / name,
                monkeypatch,
                "--project-id",
                project_id,
                "--experiment-id",
                experiment_id,
            )
        )
        assert len(spy.latest) == 3  # the symbol, then AAPL and SPY for the market state
        if name == "held":
            assert max(spy.latest) < RESERVED_INSTANT
    (held_out, held), (_, plain) = outputs
    assert f"Held back {EXTRA * 2} bars from {RESERVED_START} on" in held_out
    for key in ("calibration_fit_sha256", "market_state_artifact_sha256", "oos_origins"):
        assert held["governed_calibration"][key] == plain["governed_calibration"][key]
    assert held["summary"] == plain["summary"]


def test_forecast_run_is_forward_use_and_still_reads_the_latest_bar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spy: Spy
) -> None:
    _plain(tmp_path, CUT_N + EXTRA, poisoned=False)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    result = runner.invoke(
        app,
        ["forecast", "run", "SPY", "--model", "fake", "--context", "8", "--horizon", "4"]
        + ["--samples", "8"],
    )
    assert result.exit_code == 0, result.output
    assert max(spy.latest) >= RESERVED_INSTANT
    (rdir,) = (p for p in (tmp_path / "forecast").iterdir() if p.is_dir())
    manifest = json.loads((rdir / "manifest.json").read_text())
    assert manifest["research_cutoff"] is None
