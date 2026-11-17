"""Regressions from real rule-test runs; no engine or network required."""

import importlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NoReturn

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli import _gauntlet, _runner, data_cmds
from alpha_cli._identity import RunIdentity
from alpha_cli.spine import diagnostics, macro, run
from alpha_cli.spine.audit import audit
from alpha_cli.spine.diagnose import _publish
from alpha_cli.spine.facts import build_facts
from alpha_cli.spine.spec import IdeaSpec, Rule
from alpha_cli.spine.stores import annualisation, periods_per_year
from alpha_cli.spine.trial_reader import LedgerSnapshot
from alpha_core import Bar, CorporateAction
from alpha_data.timeframe import DAILY, parse_timeframe

START = datetime(2024, 1, 1, tzinfo=UTC)
Publication = tuple[Path, IdeaSpec, run.Prepared, dict[str, Any], Path]


@pytest.mark.parametrize("weekends,days", [(False, 252), (True, 365)])
def test_intraday_annualisation_uses_observed_days(weekends: bool, days: int) -> None:
    dates = [
        START + timedelta(days=day, hours=hour)
        for day in range(14)
        if weekends or (START + timedelta(days=day)).weekday() < 5
        for hour in range(6)
    ]
    assert periods_per_year(dates) == 6 * days
    assert periods_per_year(dates, bar_size=parse_timeframe("1h")) == 6 * days


def test_daily_annualisation_keeps_elapsed_years() -> None:
    dates = [START + timedelta(days=day) for day in range(365)]
    assert periods_per_year(dates, bar_size=DAILY) == 365


@pytest.mark.parametrize("ratio", [1.1, 0.6])
def test_drawdown_flag_names_ratio(ratio: float) -> None:
    drawdowns = diagnostics.drawdowns(
        [100, 80, 100],
        [100, 100 * (1 - 0.2 * ratio), 100],
        [START + timedelta(days=i) for i in range(3)],
    )
    assert drawdowns["episodes"][0]["share_explained"] == pytest.approx(ratio)
    sections = {
        "full_sample": {"sharpe": 1},
        "benchmark": {"sharpe": 1},
        "drawdowns": drawdowns,
        "concentration": {"top_3": None},
        "sensitivity": {"variants": []},
        "delay": {"base_sharpe": None, "delayed_sharpe": None},
    }
    detail = diagnostics.flags(sections)[0]["detail"]
    plain = {0.6: "fell 40% less than", 1.1: "fell 10% more than"}[ratio]
    assert f"buy and hold {plain} the rule over the same dates" in detail


@pytest.mark.parametrize("price,status", [(100.02, "PASS"), (99.98, "PASS"), (100.03, "FLAG")])
def test_fill_range_allows_recorded_slippage(price: float, status: str) -> None:
    items = audit(
        None,
        None,
        pl.DataFrame({"ts": [START], "price": [price]}),
        {START: (100, 100)},
        fee=1,
        slippage=2,
        trades=30,
        years=3,
        labels=[],
        benchmark=True,
        variants=0,
    )
    assert next(i for i in items if i["check"] == "fills-inside-bar-range")["status"] == status


def test_fill_range_missing_costs_is_not_checked() -> None:
    items = audit(
        None,
        None,
        pl.DataFrame({"ts": [START], "price": [100.0]}),
        {START: (100, 100)},
        fee=None,
        slippage=None,
        trades=30,
        years=3,
        labels=[],
        benchmark=True,
        variants=0,
    )
    check = next(i for i in items if i["check"] == "fills-inside-bar-range")
    assert check["status"] == "NOT-CHECKED"
    assert "cost settings" in check["detail"]


def test_macro_missing_module_has_plain_reason_and_detail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def absent(name: str) -> NoReturn:
        raise ImportError("No module named alpha_data.context.views")

    monkeypatch.setattr(importlib, "import_module", absent)
    result = macro.macro_window(tmp_path, [])
    assert result["reason"] == "macro data was not installed when this run was made"
    assert "alpha_data.context.views" in result["detail"]


@pytest.mark.parametrize("existing_store", [False, True])
def test_missing_candles_say_not_found_with_path_and_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing_store: bool
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COLUMNS", "240")
    if existing_store:
        (tmp_path / "store").mkdir()
    result = CliRunner().invoke(data_cmds.data_app, ["candles", "SPY", "--json"])
    assert result.exit_code != 0
    assert "not found" in result.output
    assert str(tmp_path / "store" / "bars" / "SPY.parquet") in result.output
    assert "next:" in result.output and "alpha data pull" in result.output
    assert "corrupt" not in result.output


@pytest.fixture
def publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Publication:
    identity = RunIdentity("a" * 16, "b" * 64, None, "c" * 64, None)
    bars = [
        Bar(
            symbol="SPY",
            ts=START + timedelta(days=i),
            open=100,
            high=101,
            low=99,
            close=100,
            volume=10,
        )
        for i in range(100)
    ]
    idea = IdeaSpec(assets=("SPY",), rule=Rule(kind="ma_cross", fast=2, slow=5))
    spec = run.assemble_run_spec(idea, "SPY", 252, len(bars))
    prepared = run.Prepared(bars, [], spec, identity)
    out = SimpleNamespace(
        oos=SimpleNamespace(oos_timestamps=[b.ts for b in bars[10:]]),
        result=SimpleNamespace(resized_entries=0),
    )
    monkeypatch.setattr(_gauntlet, "run_gauntlet", lambda *a, **kw: out)
    final = tmp_path / "runs" / identity.run_id
    result: dict[str, Any] = {
        "run_dir": str(final),
        "source": "test",
        "store": "home",
        "labels": [],
        "variants_evaluated": 0,
        "periods_per_year_basis": "elapsed years; daily snap",
    }

    def diagnose(
        idea: IdeaSpec,
        bars: list[Bar],
        dividends: list[CorporateAction],
        spec: _runner.RunSpec,
        out: SimpleNamespace,
        identity: RunIdentity,
        home: Path,
        result: dict[str, Any],
        *,
        snapshot: LedgerSnapshot | None = None,
    ) -> SimpleNamespace:
        _publish(
            Path(result["run_dir"]),
            {
                "trials": {"total_trials": 1},
                "audit": [{"check": "artifacts-intact"}],
            },
            identity,
        )
        return out

    monkeypatch.setattr(run, "write_diagnostics", diagnose)
    return tmp_path, idea, prepared, result, final


def test_crash_before_manifest_does_not_publish_diagnostics(
    publication: Publication, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, idea, prepared, result, final = publication

    def crash(*args: object, **kwargs: object) -> NoReturn:
        assert not (final / "diagnostics.json").exists()
        raise RuntimeError("simulated manifest failure")

    monkeypatch.setattr(run, "write_validation_run", crash)
    with pytest.raises(RuntimeError, match="simulated manifest failure"):
        run._execute(idea, prepared, home, _gauntlet.GauntletParams(), "test-id", result)
    assert not final.exists()
    assert result["run_dir"] == str(final)


def test_manifest_records_both_periods_and_annualisation_basis(
    publication: Publication, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, idea, prepared, result, final = publication

    def write(
        home: Path,
        bars: list[Bar],
        spec: _runner.RunSpec,
        out: SimpleNamespace,
        identity: RunIdentity,
        *,
        extra_manifest: dict[str, Any],
    ) -> tuple[Path, dict[str, Any]]:
        directory = home / "runs" / identity.run_id
        manifest = {"run_id": identity.run_id, **extra_manifest}
        (directory / "manifest.json").write_text(json.dumps(manifest))
        return directory, manifest

    monkeypatch.setattr(run, "write_validation_run", write)
    run._execute(idea, prepared, home, _gauntlet.GauntletParams(), "test-id", result)
    manifest = json.loads((final / "manifest.json").read_text())
    assert (final / "diagnostics.json").is_file()
    spine = manifest["spine"]
    assert spine["data_period"] == {
        "first_ts": prepared.bars[0].ts.isoformat(),
        "last_ts": prepared.bars[-1].ts.isoformat(),
    }
    assert spine["traded_period"] == {
        "first_ts": prepared.bars[10].ts.isoformat(),
        "last_ts": prepared.bars[-1].ts.isoformat(),
    }
    assert spine["annualisation"] == {
        "periods_per_year": 252,
        "basis": result["periods_per_year_basis"],
    }
    facts = {fact["metric"]: fact for fact in build_facts(final)}
    for name in ("data_period", "traded_period"):
        assert facts[name]["value"] == spine[name]
        assert facts[name]["source"] == f"manifest.json:spine.{name}"


def test_unreadable_candles_are_corrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COLUMNS", "240")
    bars = tmp_path / "store" / "bars" / "SPY.parquet"
    bars.parent.mkdir(parents=True)
    bars.write_bytes(b"broken parquet")
    result = CliRunner().invoke(data_cmds.data_app, ["candles", "SPY", "--json"])
    assert result.exit_code != 0
    assert "corrupt" in result.output
    assert str(bars) in result.output
    assert "not found" not in result.output


def test_crash_after_staged_manifest_leaves_final_run_absent(
    publication: Publication, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, idea, prepared, result, final = publication

    def write(
        home: Path,
        bars: list[Bar],
        spec: _runner.RunSpec,
        out: SimpleNamespace,
        identity: RunIdentity,
        *,
        extra_manifest: dict[str, Any],
    ) -> tuple[Path, dict[str, Any]]:
        directory = home / "runs" / identity.run_id
        (directory / "manifest.json").write_text(json.dumps(extra_manifest))
        return directory, extra_manifest

    def crash(staged: Path, destination: Path) -> NoReturn:
        assert (staged / "manifest.json").is_file()
        assert (staged / "diagnostics.json").is_file()
        assert destination == final and not final.exists()
        raise OSError("simulated rename failure")

    monkeypatch.setattr(run, "write_validation_run", write)
    monkeypatch.setattr(Path, "rename", crash)
    with pytest.raises(OSError, match="simulated rename failure"):
        run._execute(idea, prepared, home, _gauntlet.GauntletParams(), "test-id", result)
    assert not final.exists()
    assert result["run_dir"] == str(final)


def test_one_weekend_bar_does_not_make_a_stock_trade_weekends() -> None:
    stamps = [
        START + timedelta(days=day, hours=hour)
        for day in range(56)
        if (START + timedelta(days=day)).weekday() < 5
        for hour in range(8)
    ]
    stamps.append(stamps[-1] + timedelta(days=1))  # one stray Saturday bar
    stamps = sorted(set(stamps))
    ppy, basis = annualisation(stamps, bar_size=parse_timeframe("1h"))
    assert ppy == 8 * 252
    assert "weekdays" not in basis and "2% of bar dates fall on weekends" in basis


def test_hourly_crypto_stays_365_and_records_weekend_share() -> None:
    stamps = [START + timedelta(hours=i) for i in range(24 * 60)]
    ppy, basis = annualisation(stamps, bar_size=parse_timeframe("1h"))
    assert ppy == 24 * 365
    assert "27% of bar dates fall on weekends" in basis


@pytest.mark.parametrize(
    "profits,wording",
    [
        ([9.0, 8.0, 7.0, -8.0], "made 1.5 times the total profit; the rest lost money overall"),
        ([5.0, 4.0, 3.0, 1.0], "contributed 92% of total profit"),
    ],
)
def test_top_trades_flag_never_calls_a_multiple_a_share(profits: list[float], wording: str) -> None:
    concentration = diagnostics.concentration(profits)
    sections = {
        "full_sample": {"sharpe": 1},
        "benchmark": {"sharpe": 1},
        "drawdowns": {"episodes": []},
        "concentration": concentration,
        "sensitivity": {"variants": []},
        "delay": {"base_sharpe": None, "delayed_sharpe": None},
    }
    detail = diagnostics.flags(sections)[0]["detail"]
    assert wording in detail
    assert concentration["top_3"] == pytest.approx(sum(sorted(profits)[-3:]) / sum(profits))


def test_no_printed_or_stored_path_names_the_staging_folder(
    publication: Publication, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home, idea, prepared, result, final = publication

    def write(
        home: Path,
        bars: list[Bar],
        spec: _runner.RunSpec,
        out: SimpleNamespace,
        identity: RunIdentity,
        *,
        extra_manifest: dict[str, Any],
    ) -> tuple[Path, dict[str, Any]]:
        directory = home / "runs" / identity.run_id
        print(f"HTML report saved to: {directory}/.tearsheet.html.x.tmp")
        manifest = {"run_id": identity.run_id, **extra_manifest}
        (directory / "manifest.json").write_text(json.dumps(manifest))
        return directory, manifest

    monkeypatch.setattr(run, "write_validation_run", write)
    run._execute(idea, prepared, home, _gauntlet.GauntletParams(), "test-id", result)
    printed = capsys.readouterr().out
    assert f"HTML report saved to: {final}/tearsheet.html" in printed
    stored = json.dumps(result) + (final / "manifest.json").read_text()
    assert ".pending-" not in printed + stored
