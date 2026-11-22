"""Parameter and specification robustness: checks that re-run the engine, and the tries they add."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from numpy.random import default_rng

from alpha_cli import _runner
from alpha_cli.spine.diagnose import full_sample, variant_specs
from alpha_cli.spine.diagnostics import performance
from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.ledger import read_trials
from alpha_cli.toolbox import inputs
from alpha_cli.toolbox.contract import Result, ToolSpec
from alpha_cli.toolbox.families import parameter_robustness_common as common
from alpha_cli.toolbox.families import parameter_robustness_signals as signals
from alpha_cli.toolbox.families.parameter_robustness import CHECKS
from alpha_cli.toolbox.registry import get
from alpha_cli.toolbox.runner import run
from tests.unit.parameter_robustness_support import RUN, synthetic_series

REL, ABS = 1e-9, 1e-12
BY_ID = {spec.id: spec for spec in CHECKS}


def _compute(spec: ToolSpec, series: inputs.RunSeries, seed: int = 7, **params: Any) -> Result:
    settings = {p.name: p.default for p in spec.params} | params
    rng = default_rng(seed) if spec.seeded else None
    assert spec.compute is not None
    return spec.compute(inputs.Inputs(series, None, seed, series.home), settings, rng)


def _tries(home: Path) -> list[dict[str, Any]]:
    return [row for row in read_trials(home) if row["kind"] == "screen_trial"]


def _direct(series: inputs.RunSeries, spec: _runner.RunSpec, **kwargs: Any) -> dict[str, Any]:
    bars = list(kwargs.pop("bars", series.bars))
    result = _runner.run_full_backtest(bars, spec, dividends=[], **kwargs)
    return performance([v for _, v in result.equity_curve], series.ppy, "direct")


@pytest.fixture
def series(tmp_path: Path) -> inputs.RunSeries:
    return synthetic_series(tmp_path)


@pytest.fixture
def flat_engine(monkeypatch: pytest.MonkeyPatch, series: inputs.RunSeries) -> None:
    """Every re-run gives the rule's own equity: a rule that no setting changes."""
    monkeypatch.setattr(
        common, "engine", lambda tasks, pool: [(list(series.equity), 9) for _ in tasks]
    )


# The signal changes, on a scripted signal sequence.
RAW = [0, 1, 1, 1, 1, 0, 1, 0, 1, 1]


def _signals(change: signals.SignalChange, raw: list[int]) -> list[int]:
    strategy = SimpleNamespace(_signal=iter(raw).__next__)
    change.attach(strategy)
    return [strategy._signal() for _ in raw]


def test_signal_changes_on_a_known_sequence() -> None:
    assert _signals(signals.EntryDelay(0), RAW) == RAW
    assert _signals(signals.EntryDelay(1), RAW) == [0, 0, 1, 1, 1, 0, 0, 0, 0, 1]
    assert _signals(signals.EntryDelay(3), RAW) == [0, 0, 0, 0, 1, 0, 0, 0, 0, 0]
    assert _signals(signals.ExitDelay(1), RAW) == [0, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    assert _signals(signals.ExitDelay(0), RAW) == RAW
    assert _signals(signals.SkipEntries(0.0, 3), RAW) == RAW
    assert _signals(signals.SkipEntries(1.0, 3), RAW) == [0] * len(RAW)


def test_signal_changes_read_no_later_signal() -> None:
    for change in (signals.EntryDelay(2), signals.ExitDelay(2), signals.SkipEntries(0.5, 1)):
        for cut in range(1, len(RAW)):
            changed = [*RAW[:cut], *(1 - v for v in RAW[cut:])]
            assert _signals(change, changed)[:cut] == _signals(change, RAW)[:cut]


# Known answers, one per check.


def test_flat_rule_gives_a_flat_sensitivity(series: inputs.RunSeries, flat_engine: None) -> None:
    result = _compute(BY_ID["parameters.one_at_a_time"], series)
    values = result.values
    assert values["sharpe_min"] == values["sharpe_max"] == values["sharpe"]
    assert values["return_min"] == values["return_max"]
    # fast 5 and slow 20 at 0.5, 0.8, 1.2 and 1.5 times: fast 2 (2.5 rounds to 2), 4, 6, 8; slow
    # 10, 16, 24, 30. All keep fast below slow.
    names = [row["name"] for row in result.details["variants"]]
    assert names == [
        "fast=2",
        "fast=4",
        "fast=6",
        "fast=8",
        "slow=10",
        "slow=16",
        "slow=24",
        "slow=30",
    ]
    assert values["engine_runs"] == values["tries_added"] == 8


def test_one_at_a_time_rows_are_engine_runs_of_each_setting(series: inputs.RunSeries) -> None:
    result = _compute(BY_ID["parameters.one_at_a_time"], series)
    assert series.idea is not None and series.spec is not None
    named = {n: s for n, k, s in variant_specs(series.idea, series.spec, factors=(0.5, 1.5))}
    for row in result.details["variants"]:
        if row["name"] in named:
            direct = _direct(series, named[row["name"]])
            assert row["total_return"] == pytest.approx(direct["total_return"], rel=REL, abs=ABS)


def test_plateau_of_a_flat_rule_is_whole(series: inputs.RunSeries, flat_engine: None) -> None:
    quick = _compute(BY_ID["parameters.plateau"], series)
    assert quick.values["within_share"] == 1.0
    assert quick.values["grid_points"] == 8
    full = _compute(BY_ID["parameters.plateau"], series, grid="full")
    assert full.values["grid_points"] == 24
    assert full.details["settings_moved"] == 2


def test_plateau_counts_points_within_a_fifth(
    series: inputs.RunSeries, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Half the grid gives the rule's equity, half gives a flat line (no defined Sharpe ratio).
    flat = [1e6] * len(series.equity)
    monkeypatch.setattr(
        common,
        "engine",
        lambda tasks, pool: [
            (list(series.equity) if i % 2 else flat, 1) for i in range(len(tasks))
        ],
    )
    values = _compute(BY_ID["parameters.plateau"], series).values
    assert values["within_share"] == 0.5
    assert values["sharpe_min"] == values["sharpe"]


def test_neighbours_of_a_flat_rule_agree(series: inputs.RunSeries, flat_engine: None) -> None:
    values = _compute(BY_ID["parameters.neighbour_stability"], series).values
    assert values["same_sign_share"] == 1.0
    assert values["neighbours"] == 4


def test_worst_neighbour_is_the_lowest_return(
    series: inputs.RunSeries, monkeypatch: pytest.MonkeyPatch
) -> None:
    equity = np.asarray(series.equity)
    curves = [list(equity * np.linspace(1.0, 1.0 + k / 10, len(equity))) for k in (3, -2, 1, 4)]
    monkeypatch.setattr(common, "engine", lambda tasks, pool: [(c, 1) for c in curves])
    result = _compute(BY_ID["parameters.worst_neighbour"], series)
    assert result.values["worst_setting"] == "fast=6"
    expected = curves[1][-1] / curves[1][0] - 1
    assert result.values["worst_return"] == pytest.approx(expected, rel=REL, abs=ABS)


def _trades(series: inputs.RunSeries, change: signals.SignalChange | None) -> list[Any]:
    assert series.spec is not None
    kwargs = {"signal_filter": change} if change else {}
    return list(_runner.run_full_backtest(list(series.bars), series.spec, **kwargs).trades)


def test_entry_delay_enters_later_and_leaves_on_time(series: inputs.RunSeries) -> None:
    dates = list(series.dates)
    original, delayed = _trades(series, None), _trades(series, signals.EntryDelay(1))
    assert original and delayed
    # Each delayed trade is an original trade entered one bar later, with the same exit.
    pairs = {(t.entry_ts, t.exit_ts) for t in original}
    for trade in delayed:
        earlier = dates[dates.index(trade.entry_ts) - 1]
        assert (earlier, trade.exit_ts) in pairs
    values = _compute(BY_ID["parameters.entry_delay"], series).values
    assert series.spec is not None
    direct = _direct(series, series.spec, signal_filter=signals.EntryDelay(1))
    assert values["return_1"] == pytest.approx(direct["total_return"], rel=REL, abs=ABS)


def test_exit_delay_leaves_later(series: inputs.RunSeries) -> None:
    dates = list(series.dates)
    original, delayed = _trades(series, None), _trades(series, signals.ExitDelay(1))
    entries = {t.entry_ts: t.exit_ts for t in original}
    for trade in delayed:
        # Each trade starts as the rule says and ends one bar after an exit of the rule.
        assert trade.entry_ts in entries
        assert dates[dates.index(trade.exit_ts) - 1] in set(entries.values())
    values = _compute(BY_ID["parameters.exit_delay"], series).values
    assert values["sharpe_1"] is not None


def test_cost_ladder_lowers_the_return(series: inputs.RunSeries) -> None:
    values = _compute(BY_ID["parameters.cost_ladder"], series).values
    assert series.spec is not None
    doubled = replace(
        series.spec, fee_bps=series.spec.fee_bps * 2, slippage_bps=series.spec.slippage_bps * 2
    )
    direct = _direct(series, doubled)
    assert values["return_2"] == pytest.approx(direct["total_return"], rel=REL, abs=ABS)
    base = series.equity[-1] / series.equity[0] - 1
    assert base > values["return_2"] > values["return_3"] > values["return_5"]


def test_start_date_starts_later(series: inputs.RunSeries) -> None:
    values = _compute(BY_ID["parameters.start_date"], series).values
    assert series.spec is not None
    # 2020-01-01 plus 3 months is 2020-04-01: bar 91 of a calendar-day series.
    _, _, equity = full_sample(list(series.bars[91:]), [], series.spec)
    expected = equity[-1] / equity[0] - 1
    assert values["return_3"] == pytest.approx(expected, rel=REL, abs=ABS)


def test_inversion_matches_the_stored_control(series: inputs.RunSeries) -> None:
    from alpha_cli.spine.controls import run_inverted_backtest

    values = _compute(BY_ID["parameters.inversion"], series).values
    assert series.spec is not None
    control = run_inverted_backtest(list(series.bars), series.spec, series.full)
    curve = [v for _, v in control.equity_curve]
    assert values["return_opposite"] == pytest.approx(curve[-1] / curve[0] - 1, rel=REL, abs=ABS)
    assert values["engine_runs"] == values["tries_added"] == 1


def test_skipping_no_entry_reproduces_the_rule(series: inputs.RunSeries) -> None:
    assert series.spec is not None
    kept = _runner.run_full_backtest(
        list(series.bars), series.spec, signal_filter=signals.SkipEntries(0.0, 11)
    )
    assert [v for _, v in kept.equity_curve] == list(series.equity)
    none = _runner.run_full_backtest(
        list(series.bars), series.spec, signal_filter=signals.SkipEntries(1.0, 11)
    )
    assert not none.trades
    values = _compute(BY_ID["parameters.skip_entries"], series, copies=2).values
    assert values["engine_runs"] == 6
    assert values["sharpe_low_10"] <= values["sharpe_high_10"]


def test_price_noise_spreads_around_the_rule(series: inputs.RunSeries) -> None:
    from alpha_cli.spine.price_noise import noisy_bars

    result = _compute(BY_ID["parameters.price_noise"], series, seed=3)
    values = result.values
    assert values["p05_sharpe"] <= values["median_sharpe"] <= values["p95_sharpe"]
    assert values["engine_runs"] == 50
    assert series.spec is not None
    copy = noisy_bars(list(series.bars), f"{RUN}:3", 0)
    direct = _direct(series, series.spec, bars=copy)
    assert result.details["runs"][0]["sharpe"] == pytest.approx(direct["sharpe"], rel=REL, abs=ABS)


# Every check: too little data, a repeat is identical, and tries are counted once.


@pytest.mark.parametrize("spec", CHECKS, ids=lambda spec: spec.id)
def test_too_little_data_runs_nothing(spec: ToolSpec, series: inputs.RunSeries) -> None:
    sparse = replace(series, full=SimpleNamespace(trades=[object()] * 3))
    result = _compute(spec, sparse)
    assert result.values["engine_runs"] == result.values["tries_added"] == 0
    shown = {k for k, v in result.values.items() if v is not None}
    assert shown == {"engine_runs", "tries_added"}
    assert all("closed 3 trades" in result.reasons[k] for k in result.values if k not in shown)
    assert not _tries(series.home)


@pytest.mark.parametrize("spec", CHECKS, ids=lambda spec: spec.id)
def test_repeat_is_identical_and_adds_no_try(
    spec: ToolSpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def engine(tasks: list[Any], pool: int) -> list[tuple[Any, int]]:
        # A stand-in engine whose answer depends on the task's costs and its first bar.
        return [
            (
                list(
                    np.linspace(1.0, 1.1 + task[1].fee_bps / 100, len(task[0]))
                    * (1 + 0.01 * np.sin(np.arange(len(task[0])) + task[0][0].close))
                ),
                5,
            )
            for task in tasks
        ]

    monkeypatch.setattr(common, "engine", engine)
    homes = [tmp_path / "a", tmp_path / "b"]
    first, second = (_compute(spec, synthetic_series(home)) for home in homes)
    assert first == second
    again = _compute(spec, synthetic_series(homes[0]))
    assert again.values == {**first.values, "tries_added": 0}
    assert len(_tries(homes[0])) == first.values["engine_runs"]


def test_tries_are_counted_once_and_seen_by_the_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from alpha_cli.spine.deflation import same_asset_tests
    from alpha_cli.spine.trial_reader import spine_snapshot

    series = synthetic_series(tmp_path)
    monkeypatch.setattr(inputs, "load_rerun", lambda home, target: series)
    doc = run(tmp_path, "parameters.neighbour_stability", RUN)
    assert "This check makes 4 engine runs" in capsys.readouterr().err
    tries = _tries(tmp_path)
    assert len(tries) == doc["values"]["tries_added"] == 4
    assert all(row["of_run"] == RUN and "repeat" not in row["labels"] for row in tries)
    # The same check again is the stored reading; the ledger gets no new try.
    assert run(tmp_path, "parameters.neighbour_stability", RUN) == doc
    assert len(_tries(tmp_path)) == 4
    # Another check that re-runs the same settings adds them as repeats, not as new tries.
    worst = run(tmp_path, "parameters.worst_neighbour", RUN)
    assert worst["values"]["tries_added"] == 0
    assert len(_tries(tmp_path)) == 4
    tests, repeats, _ = same_asset_tests(spine_snapshot(tmp_path), "SPY")
    assert (tests, repeats) == (4, 0)


def test_progress_lines_while_engine_runs_go_on(
    series: inputs.RunSeries, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import time

    def slow(tasks: list[Any], pool: int) -> list[tuple[Any, int]]:
        time.sleep(0.2)
        return [(list(series.equity), 1) for _ in tasks]

    monkeypatch.setattr(common, "PROGRESS_EVERY", 0.05)
    monkeypatch.setattr(common, "engine", slow)
    _compute(BY_ID["parameters.cost_ladder"], series)
    err = capsys.readouterr().err
    assert "This check makes 3 engine runs; about 1 seconds." in err
    assert "Still running:" in err and "Done: 3 engine runs" in err


# The loader: a stored rule test re-read for re-runs.


@pytest.fixture(scope="module")
def stored(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    from alpha_cli.spine.run import run_idea
    from alpha_cli.spine.spec import IdeaSpec
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    home = tmp_path_factory.mktemp("stored") / "home"
    seed_store(home, symbol="SPY", n=900)
    ParquetStore(home / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    idea = IdeaSpec.model_validate(
        {"assets": ["SPY"], "rule": {"kind": "ma_cross", "fast": 5, "slow": 20}}
    )
    result = run_idea(idea, home=home, quick=True)["results"][0]
    assert result["error"] is None
    return home, result["run_id"]


def test_load_rerun_gives_what_the_run_used(stored: tuple[Path, str]) -> None:
    home, run_id = stored
    target = inputs.resolve(home, run_id)
    rerun, replay = inputs.load_rerun(home, target), inputs.load_run(home, target)
    assert rerun.equity == replay.equity and rerun.bars == replay.bars
    assert rerun.idea is not None and rerun.idea.rule.params == {"fast": 5, "slow": 20}
    assert rerun.spec is not None and rerun.full is not None
    _, hashes = target.prepare(home, ("run_rerun",), {})
    assert hashes["data_fingerprint"] == target.manifest["source_fingerprint"]


def test_future_bars_do_not_enter_a_rerun(
    stored: tuple[Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, run_id = stored
    target = inputs.resolve(home, run_id)
    baseline = inputs.load_rerun(home, target)
    original, cuts = _runner.load_bars, []

    def poisoned(symbol: str, *, data_dir: Path, as_of: Any) -> tuple[list[Any], Any]:
        cuts.append(as_of)
        bars, snapshot = original(symbol, data_dir=data_dir, as_of=as_of)
        later = SimpleNamespace(ts=bars[-1].ts.replace(year=bars[-1].ts.year + 1), open=-1.0)
        return [*bars, later], snapshot

    monkeypatch.setattr(_runner, "load_bars", poisoned)
    assert inputs.load_rerun(home, target) == baseline
    from alpha_cli.spine.reserve import CUTOFF

    assert cuts == [CUTOFF]


def test_changed_data_refuses_in_plain_words(stored: tuple[Path, str], tmp_path: Path) -> None:
    import polars as pl

    from alpha_data.store import ParquetStore

    home, run_id = stored
    copy = tmp_path / "home"
    shutil.copytree(home, copy)
    store = ParquetStore(copy / "store")
    frame = pl.read_parquet(store._bars_path("SPY"))
    store.write_bars(
        "SPY", frame.with_columns(*(pl.col(c) * 1.01 for c in ("open", "high", "low", "close")))
    )
    with pytest.raises(SpineError, match="is not the data run") as caught:
        inputs.load_rerun(copy, inputs.resolve(copy, run_id))
    assert caught.value.payload["code"] == "RUN_DATA_CHANGED"


def test_cost_ladder_on_a_stored_run_matches_its_diagnostics(stored: tuple[Path, str]) -> None:
    home, run_id = stored
    copy = home.parent / "ladder"
    if not copy.exists():
        shutil.copytree(home, copy)
    doc = run(copy, "parameters.cost_ladder", run_id)
    diagnostics = json.loads((copy / "runs" / run_id / "diagnostics.json").read_text())
    stored_x2 = next(v for v in diagnostics["sensitivity"]["variants"] if v["name"] == "costs_x2")
    assert doc["values"]["return_2"] == pytest.approx(stored_x2["total_return"], rel=REL, abs=ABS)
    assert get("parameters.cost_ladder").needs == ("run_rerun",)
