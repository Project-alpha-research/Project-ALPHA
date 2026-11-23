"""CLI stored projections and stable error envelopes."""

import json
import re
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from alpha_cli import data_cmds
from alpha_cli.results_cmds import diagnose_run, results_app
from alpha_cli.spine.ledger import append_trial


def app() -> typer.Typer:
    root = typer.Typer()
    root.add_typer(results_app, name="results")
    root.command("diagnose")(diagnose_run)
    return root


@pytest.mark.parametrize(
    "args,code",
    [
        (["results", "--json"], "EMPTY_LEDGER"),
        (["results", "show", "missing", "--json"], "UNKNOWN_RUN"),
        (["results", "cite", "missing", "nonsense", "--json"], "UNKNOWN_METRIC"),
    ],
)
def test_structured_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str], code: str
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(app(), args)
    assert result.exit_code != 0
    error = json.loads(result.stdout)["error"]
    assert error["code"] == code
    assert "known" in error
    assert "alpha " in error["next"]
    if code == "UNKNOWN_METRIC":
        assert "oos_sharpe" in error["known"]


def test_cite_and_no_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    run_id = "0123456789abcdef"
    rdir = tmp_path / "runs" / run_id
    rdir.mkdir(parents=True)
    (rdir / "manifest.json").write_text(
        json.dumps({"command": "validate", "oos_metrics": {"sharpe": 1.23456789}})
    )
    append_trial(tmp_path, {"run_id": run_id, "test_id": "test", "labels": []})
    result = CliRunner().invoke(app(), ["results", "cite", run_id, "oos_sharpe"])
    assert result.exit_code == 0, result.output
    assert (
        result.stdout == f"1.23456789 [{run_id}:oos_sharpe] (walk-forward out-of-sample returns)\n"
    )
    result = CliRunner().invoke(app(), ["diagnose", run_id, "--json"])
    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "NO_DIAGNOSTICS"
    assert "alpha test" in error["next"]


@pytest.mark.parametrize(
    "args,code,known",
    [
        (
            ["--rule", "nonsense", "--asset", "SPY"],
            "UNKNOWN_RULE",
            ["ma_cross", "breakout", "tsmom"],
        ),
        (
            ["--rule", "breakout", "--param", "window=20", "--asset", "MISSING"],
            "UNKNOWN_ASSET",
            ["home"],
        ),
    ],
)
def test_test_command_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str], code: str, known: list[str]
) -> None:
    from alpha_cli.test_cmds import test_rule

    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    root = typer.Typer()
    root.command()(test_rule)
    result = CliRunner().invoke(root, [*args, "--json"])
    assert result.exit_code != 0
    error = json.loads(result.stdout)["error"]
    assert error["code"] == code
    assert error["known"] == known
    assert "alpha test" in error["next"]


def test_too_few_bars_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alpha_cli.test_cmds import test_rule
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=40)
    # Strict pull provenance: bar reads reject a partial provenance file.
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="synthetic", adapter_version="1", parser_version="1"
    )
    root = typer.Typer()
    root.command()(test_rule)
    result = CliRunner().invoke(
        root, ["--rule", "breakout", "--param", "window=20", "--asset", "SPY", "--json"]
    )
    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "TOO_FEW_BARS"
    assert error["known"] is None
    assert "alpha test" in error["next"]


def test_list_filters_newest_first_and_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    for name, symbol in [("first", "SPY"), ("second", "OTHER"), ("third", "SPY")]:
        append_trial(
            tmp_path, {"run_id": name, "name": name, "symbol": symbol, "labels": [], "flags": []}
        )
    result = CliRunner().invoke(app(), ["results", "--symbol", "SPY", "--limit", "1", "--json"])
    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    assert output["total_trials"] == 3
    assert [row["name"] for row in output["items"]] == ["third"]
    result = CliRunner().invoke(app(), ["results", "--name", "first", "--json"])
    assert json.loads(result.stdout)["items"][0]["trial_index"] == 1


def test_show_resolves_test_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    ids = ["0123456789abcdef", "abcdef0123456789"]
    for run_id in ids:
        rdir = tmp_path / "runs" / run_id
        rdir.mkdir(parents=True)
        (rdir / "manifest.json").write_text('{"command":"validate"}')
        append_trial(tmp_path, {"run_id": run_id, "test_id": "test", "labels": []})
    result = CliRunner().invoke(app(), ["results", "show", "test", "--json"])
    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    assert [row["run_id"] for row in output["runs"]] == ids
    assert all(row["facts"] for row in output["runs"])


def test_failed_sensitivity_attempt_is_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Sequence
    from unittest.mock import Mock

    import numpy as np

    from alpha_backtest.results import BacktestResult
    from alpha_cli import _artifacts, _runner
    from alpha_cli._gauntlet import GauntletOutput
    from alpha_cli._identity import RunIdentity
    from alpha_cli.spine import diagnose
    from alpha_cli.spine.run import assemble_run_spec
    from alpha_cli.spine.spec import load_spec
    from alpha_core import Bar, CorporateAction, DataError
    from alpha_validation import GauntletReport
    from alpha_validation.metrics import to_returns
    from tests.fixtures.cli_fixtures import seed_store

    seed_store(tmp_path, symbol="SPY", n=100)
    bars, _ = _runner.load_bars("SPY", data_dir=tmp_path)
    idea = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    spec = assemble_run_spec(idea, "SPY", 365, 100)
    equity = [(bar.ts, float(bar.close)) for bar in bars]
    full = BacktestResult(0, 0, [], equity)
    values = np.array([v for _, v in equity])
    out = GauntletOutput(
        report=Mock(spec=GauntletReport),
        result=full,
        oos=_runner.OOSResult(to_returns(values), values, [ts for ts, _ in equity], ()),
        tier1_null=np.array([]),
        tier2_null=np.array([]),
        tier3_null=np.array([]),
    )
    calls: list[tuple[Sequence[Bar], _runner.RunSpec]] = []

    def rerun(
        bars: Sequence[Bar], spec: _runner.RunSpec, *, dividends: Sequence[CorporateAction] = ()
    ) -> BacktestResult:
        calls.append((bars, spec))
        if len(calls) > 1:
            raise DataError("failed variant")
        return full

    monkeypatch.setattr(_runner, "run_full_backtest", rerun)
    monkeypatch.setattr(_artifacts, "write_run_sidecars", lambda *args, **kwargs: None)
    result = {"run_dir": str(tmp_path / "run"), "variants_evaluated": 0}
    with pytest.raises(DataError, match="failed variant"):
        diagnose.write_diagnostics(
            idea,
            bars,
            [],
            spec,
            out,
            RunIdentity("0123456789abcdef", "a" * 64, None, "b" * 64, None),
            tmp_path,
            result,
        )
    assert result["variants_evaluated"] == 1


def test_null_dsr_does_not_crash_show_or_cite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    run_id = "0123456789abcdef"
    rdir = tmp_path / "runs" / run_id
    rdir.mkdir(parents=True)
    (rdir / "manifest.json").write_text(json.dumps({"command": "validate", "dsr": None}))
    cited = CliRunner().invoke(app(), ["results", "cite", run_id, "dsr", "--json"])
    assert cited.exit_code == 0, cited.output
    fact = json.loads(cited.stdout)
    assert fact["value"] is None
    assert fact["reason"]
    shown = CliRunner().invoke(app(), ["results", "show", run_id, "--json"])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.stdout)["failed"] == []


def test_show_test_id_keeps_completed_assets_and_reports_failed_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    good, bad = "0123456789abcdef", "fedcba9876543210"
    rdir = tmp_path / "runs" / good
    rdir.mkdir(parents=True)
    (rdir / "manifest.json").write_text(json.dumps({"command": "validate"}))
    append_trial(tmp_path, {"run_id": good, "test_id": "t1", "symbol": "SPY", "labels": []})
    append_trial(tmp_path, {"run_id": bad, "test_id": "t1", "symbol": "QQQ", "labels": ["error"]})
    append_trial(tmp_path, {"run_id": None, "test_id": "t1", "symbol": "NOPE", "labels": ["error"]})
    append_trial(
        tmp_path,
        {"kind": "tool:regimes", "run_id": good, "test_id": "t1", "tool_output": "x", "labels": []},
    )
    result = CliRunner().invoke(app(), ["results", "show", "t1", "--json"])
    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    assert [run["run_id"] for run in output["runs"]] == [good]
    assert [(item["symbol"], item["run_id"], item["trial_index"]) for item in output["failed"]] == [
        ("QQQ", bad, 2),
        ("NOPE", None, 3),
    ]
    assert all("did not complete" in item["reason"] for item in output["failed"])
    append_trial(tmp_path, {"run_id": bad, "test_id": "t2", "symbol": "QQQ", "labels": ["error"]})
    only_failed = CliRunner().invoke(app(), ["results", "show", "t2", "--json"])
    assert only_failed.exit_code == 0
    assert json.loads(only_failed.stdout)["runs"] == []
    assert len(json.loads(only_failed.stdout)["failed"]) == 1


def test_show_test_id_reports_an_unreadable_asset_and_keeps_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    good, broken = "0123456789abcdef", "fedcba9876543210"
    for run_id in (good, broken):
        (tmp_path / "runs" / run_id).mkdir(parents=True)
        append_trial(
            tmp_path, {"run_id": run_id, "test_id": "t3", "symbol": run_id[:3], "labels": []}
        )
    (tmp_path / "runs" / good / "manifest.json").write_text(json.dumps({"command": "validate"}))
    (tmp_path / "runs" / broken / "manifest.json").write_text("{not json")
    result = CliRunner().invoke(app(), ["results", "show", "t3", "--json"])
    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    assert [run["run_id"] for run in output["runs"]] == [good]
    (failed,) = output["failed"]
    assert failed["run_id"] == broken
    assert failed["reason"].startswith("stored run could not be read")
    # Naming the broken run directly still fails loud.
    direct = CliRunner().invoke(app(), ["results", "show", broken, "--json"])
    assert direct.exit_code != 0


def test_rule_run_publishes_diagnostics_and_reads_them_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli.spine.run import run_idea
    from alpha_cli.spine.spec import load_spec
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=150)
    # Strict pull provenance: bar reads reject a partial provenance file.
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    idea = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    result = run_idea(idea, home=tmp_path, quick=True)["results"][0]
    assert result["error"] is None, result
    rdir = Path(result["run_dir"])
    manifest = json.loads((rdir / "manifest.json").read_text())
    assert "diagnostics.json" in manifest["artifacts"]
    stored = json.loads((rdir / "diagnostics.json").read_text())
    # fast=4, fast=6, slow=16, slow=24 and doubled costs.
    assert stored["variants_evaluated"] == result["variants_evaluated"] == 5
    assert [v["name"] for v in stored["sensitivity"]["variants"]][0] == "costs_x2"
    assert result["flags"] == stored["flags"]
    assert result["benchmark_sharpe"] == stored["benchmark"]["sharpe"]
    intact = next(item for item in stored["audit"] if item["check"] == "artifacts-intact")
    assert intact["status"] == "PASS"
    assert stored["macro_window"]["available"] is False
    assert stored["macro_window"]["reason"]
    run_id = result["run_id"]
    read = CliRunner().invoke(app(), ["diagnose", run_id, "--json"])
    assert read.exit_code == 0, read.output
    read_back = json.loads(read.stdout)
    assert read_back.pop("reading")["schema"] == "AlphaReadingV1"
    assert read_back == stored
    shown = CliRunner().invoke(app(), ["results", "show", run_id, "--json"])
    assert shown.exit_code == 0, shown.output
    (run,) = json.loads(shown.stdout)["runs"]
    assert run["run_id"] == run_id
    assert run["audit"] == stored["audit"]
    assert run["diagnostics_reason"] is None
    fact = next(item for item in run["facts"] if item["metric"] == "variants_evaluated")
    assert fact["value"] == 5


def test_diagnose_unknown_and_corrupt_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    unknown = CliRunner().invoke(app(), ["diagnose", "missing", "--json"])
    assert unknown.exit_code == 1
    error = json.loads(unknown.stdout)["error"]
    assert error["code"] == "UNKNOWN_RUN"
    assert "alpha results" in error["next"]
    run_id = "0123456789abcdef"
    rdir = tmp_path / "runs" / run_id
    rdir.mkdir(parents=True)
    (rdir / "manifest.json").write_text('{"command":"validate"}')
    (rdir / "diagnostics.json").write_text("[]")
    corrupt = CliRunner().invoke(app(), ["diagnose", run_id, "--json"])
    assert corrupt.exit_code == 1
    error = json.loads(corrupt.stdout)["error"]
    assert error["code"] == "INVALID_ARTIFACT"
    assert "diagnostics.json must contain an object" in error["message"]


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


def test_list_hides_tool_rows_and_shows_clean_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    base = {"test_id": "t", "labels": [], "symbol": "SPY", "name": "r", "flags": []}
    append_trial(tmp_path, {**base, "run_id": "a" * 16, "verdict": "B"})
    append_trial(tmp_path, {**base, "run_id": "b" * 16, "kind": "tool:deflated_sharpe"})
    shown = CliRunner().invoke(app(), ["results"]).output
    assert "tool:deflated_sharpe" not in shown
    assert "rule_test" in shown
    assert "flags (count)" in shown
    assert re.search(r"\d{4}-\d\d-\d\d \d\d:\d\d(?!:)", shown)
    assert not re.search(r"\.\d{6}", shown)
    with_tools = CliRunner().invoke(app(), ["results", "--tools"]).output
    assert "tool:deflated_sharpe" in with_tools
    assert "fault" not in with_tools
