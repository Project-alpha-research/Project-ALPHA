"""Search and score commands hold back the reserved period, as rule tests and setups do."""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest
import typer
from typer.testing import CliRunner

from alpha_cli import (
    _backtest_run_inputs,
    _cross_sectional,
    _portfolio,
    _runner,
    backtest_cmds,
    labels_cmds,
    optim_cmds,
    validate_cmds,
)
from alpha_cli.lookalike_cmds import lookalike, unusual
from alpha_cli.rules_cmds import rules_app
from alpha_cli.scan_cmds import scan_app
from alpha_core import Bar
from alpha_core.corporate import ActionType, CorporateAction
from alpha_core.reserve import RESERVED_DAY, RESERVED_START
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

HELD_BACK = "reserved-period-held-back"
# 2020-01-01 plus 1,600 daily bars ends 2024-05-19; the first 1,461 bars are dated before 2024.
LONG, SHORT = 1600, 1461
HELD = LONG - SHORT
SENTENCE = f"Held back {HELD} bars from {RESERVED_START} on"
SPEC = ["--lookback", "20", "--skip", "1", "--vol-window", "10", "--rebalance-every", "5"]
WALK = ["--train-size", "300", "--test-size", "60", "--embargo", "2"]
NAMES = ["AAA", "BBB", "CCC", "DDD"]


class Spy:
    """The latest bar, and any action, each loader call returned."""

    def __init__(self) -> None:
        self.latest: list[datetime] = []
        self.actions: list[date] = []


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    seen = Spy()
    load_bars, load_dividends = _runner.load_bars, _runner.load_dividends

    def bars(*args: Any, **kwargs: Any) -> tuple[list[Bar], str | None]:
        result = load_bars(*args, **kwargs)
        seen.latest.append(max(bar.ts for bar in result[0]))
        return result

    def dividends(*args: Any, **kwargs: Any) -> list[Any]:
        result: list[Any] = load_dividends(*args, **kwargs)
        seen.actions.extend(action.ex_date for action in result)
        return result

    for module in (optim_cmds, validate_cmds, backtest_cmds, _backtest_run_inputs):
        monkeypatch.setattr(module, "_load_bars", bars)
        monkeypatch.setattr(module, "_load_dividends", dividends)
    for module in (_runner, _portfolio):
        monkeypatch.setattr(module, "load_bars", bars)
        monkeypatch.setattr(module, "load_dividends", dividends)
    monkeypatch.setattr(_cross_sectional, "load_bars", bars)
    return seen


def _store(home: Path, n: int, *, poisoned: bool) -> None:
    for index, symbol in enumerate(["SPY", *NAMES]):
        seed_store(home, symbol=symbol, n=n, seed=index)
        store = ParquetStore(home / "store")
        store.write_provenance(symbol, source="alpaca", adapter_version="1", parser_version="1")
        if not poisoned:
            continue
        frame = store.read_bars(symbol)
        late = pl.col("ts").dt.date() >= RESERVED_DAY
        store.write_bars(
            symbol,
            frame.with_columns(
                [
                    pl.when(late).then(pl.col(c) * 1000.0).otherwise(pl.col(c)).alias(c)
                    for c in ("open", "high", "low", "close")
                ]
            ),
        )
        store.write_actions(
            symbol,
            [
                CorporateAction(
                    symbol=symbol,
                    action_type=ActionType.SPLIT,
                    ex_date=date(2024, 2, 15),
                    ratio=4.0,
                ),
                CorporateAction(
                    symbol=symbol,
                    action_type=ActionType.DIVIDEND,
                    ex_date=date(2024, 3, 1),
                    pay_date=date(2024, 3, 5),
                    amount=1.0,
                ),
            ],
        )


def _command(*path: str) -> typer.Typer:
    root = typer.Typer()
    leaf = {
        "optim": optim_cmds.optim_app,
        "backtest": backtest_cmds.backtest_app,
    }
    if path[0] in leaf:
        root.add_typer(leaf[path[0]], name=path[0])
    elif path[0] == "validate":
        root.command("validate")(validate_cmds.validate)
        root.command("other")(lambda: None)
    elif path[0] == "rules":
        root.add_typer(rules_app, name="rules")
    elif path[0] == "scan":
        root.add_typer(scan_app, name="scan")
    else:
        root.command("lookalike")(lookalike)
        root.command("unusual")(unusual)
    return root


def _run(home: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]) -> str:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    result = CliRunner().invoke(_command(args[0]), args)
    assert result.exit_code == 0, result.output
    return result.output


def _manifest(home: Path, folder: str) -> dict[str, Any]:
    paths = sorted((home / folder).glob("*/manifest.json"))
    assert len(paths) == 1, paths
    return cast(dict[str, Any], json.loads(paths[0].read_text()))


def _metric(manifest: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        manifest = manifest[key]
    return manifest


CASES: dict[str, tuple[list[str], str, tuple[str, ...]]] = {
    "optim": (
        ["optim", "grid", "SPY", "--grid", "lookback=10,20", *SPEC[2:], *WALK]
        + ["--pbo-blocks", "4", "--n-resamples", "100"],
        "optim",
        ("best_sharpe",),
    ),
    "optim_mcpt": (
        ["optim", "mcpt", "SPY", "--grid", "lookback=10,20", *SPEC[2:], "--perms", "20"],
        "optim",
        ("percentile",),
    ),
    "validate": (
        ["validate", "SPY", *SPEC, *WALK, "--tier1-paths", "30", "--tier2-paths", "3"]
        + ["--tier3-paths", "3", "--n-resamples", "100"],
        "runs",
        ("oos_metrics", "sharpe"),
    ),
    "backtest_oos": (["backtest", "oos", "SPY", *SPEC, *WALK], "runs", ("oos_metrics", "sharpe")),
    "backtest_run": (["backtest", "run", "SPY", *SPEC], "runs", ("final_equity",)),
    "portfolio": (
        ["backtest", "portfolio", *NAMES, *SPEC, *WALK],
        "portfolio",
        ("metrics", "sharpe"),
    ),
    "cross_sectional": (
        ["backtest", "cross-sectional", *NAMES, *SPEC],
        "cross_sectional",
        ("metrics", "sharpe"),
    ),
}


@pytest.mark.parametrize("name", list(CASES))
def test_command_reads_no_held_back_bar_and_equals_the_cut_store(
    name: str, tmp_path: Path, spy: Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, folder, keys = CASES[name]
    poisoned, cut = tmp_path / "poisoned", tmp_path / "cut"
    _store(poisoned, LONG, poisoned=True)
    _store(cut, SHORT, poisoned=False)
    out = _run(poisoned, monkeypatch, args)
    assert spy.latest and all(ts.date() < RESERVED_DAY for ts in spy.latest), spy.latest
    assert all(day < RESERVED_DAY for day in spy.actions), spy.actions
    manifest = _manifest(poisoned, folder)
    assert manifest["reserve"]["reserved_start"] == RESERVED_START
    assert manifest["reserve"]["held_back_bars"] in (HELD, HELD * len(NAMES))
    assert HELD_BACK in manifest["labels"]
    assert "Held back" in out and RESERVED_START in out
    clean = _run(cut, monkeypatch, args)
    assert "Held back" not in clean
    reference = _manifest(cut, folder)
    assert "reserve" not in reference
    assert _metric(manifest, *keys) == pytest.approx(_metric(reference, *keys), rel=1e-9, abs=1e-12)
    assert manifest["run_id"] != reference["run_id"]


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    poisoned, cut = tmp_path / "poisoned", tmp_path / "cut"
    _store(poisoned, LONG, poisoned=True)
    _store(cut, SHORT, poisoned=False)
    return poisoned, cut


def _save_rule(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alpha_cli.main import app

    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    trend = json.dumps(
        {
            "name": "trend",
            "history": 40,
            "long_when": [
                {
                    "left": {"indicator": "sma", "params": [5]},
                    "op": ">",
                    "right": {"indicator": "sma", "params": [20]},
                }
            ],
        }
    )
    assert CliRunner().invoke(app, ["rules", "save", "trend", "--spec", trend]).exit_code == 0


def test_alpha_scan_and_rules_explain_hold_the_period_back(
    tmp_path: Path, spy: Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli import scan_cmds
    from alpha_cli.rules_cmds import explain_saved_rule

    poisoned, cut = _pair(tmp_path)
    scan = scan_cmds.validate_scan(
        {"name": "s", "rules": "trend", "universe": {"kind": "list", "symbols": NAMES}}
    )
    _save_rule(poisoned, monkeypatch)
    _save_rule(cut, monkeypatch)
    held = scan_cmds.run_scan(scan, data_dir=poisoned, as_of=None)
    plain = scan_cmds.run_scan(scan, data_dir=cut, as_of=None)
    assert held["reserve"]["held_back_bars"] == HELD * len(NAMES) and HELD_BACK in held["labels"]
    assert held["rows"] == plain["rows"] and "reserve" not in plain and "labels" not in plain
    explained = explain_saved_rule("trend", "SPY", data_dir=poisoned)
    reference = explain_saved_rule("trend", "SPY", data_dir=cut)
    assert explained["reserve"]["held_back_bars"] == HELD
    assert explained["bar_ts"] == pytest.approx(reference["bar_ts"], rel=1e-9, abs=1e-12)
    assert explained["signal"] == reference["signal"]
    assert spy.latest and all(ts.date() < RESERVED_DAY for ts in spy.latest)
    assert all(day < RESERVED_DAY for day in spy.actions)


def test_alert_check_is_forward_use_and_still_reads_the_latest_bar(
    tmp_path: Path, spy: Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alpha_cli import scan_cmds

    poisoned, _ = _pair(tmp_path)
    _save_rule(poisoned, monkeypatch)
    scan = scan_cmds.validate_scan(
        {"name": "s", "rules": "trend", "universe": {"kind": "list", "symbols": ["SPY"]}}
    )
    result = scan_cmds.check_scan(scan, data_dir=poisoned)
    assert "reserve" not in result
    assert max(spy.latest).date() >= RESERVED_DAY


@pytest.mark.parametrize("command", ["lookalike", "unusual"])
def test_lookalike_and_unusual_hold_the_period_back(
    command: str, tmp_path: Path, spy: Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    poisoned, cut = _pair(tmp_path)
    args = [command, "--asset", "SPY", "--json"]
    monkeypatch.setenv("ALPHA_DATA_DIR", str(poisoned))
    held = CliRunner().invoke(_command(command), args)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(cut))
    plain = CliRunner().invoke(_command(command), args)
    assert held.exit_code == 0 and plain.exit_code == 0, held.output
    # One behaviour for every covered command: --json carries a reserve field, no sentence.
    held_doc, plain_doc = json.loads(held.output), json.loads(plain.output)
    assert held_doc["reserve"] == {"reserved_start": RESERVED_START, "held_back_bars": HELD}
    assert "reserve" not in plain_doc
    assert HELD_BACK in held_doc["labels"] and HELD_BACK not in plain_doc["labels"]
    monkeypatch.setenv("ALPHA_DATA_DIR", str(poisoned))
    text = CliRunner().invoke(_command(command), args[:-1])
    assert text.exit_code == 0 and SENTENCE in text.output, text.output
    assert [f["value"] for f in held_doc["facts"] if isinstance(f["value"], float)] == [
        pytest.approx(f["value"], rel=1e-9, abs=1e-12)
        for f in plain_doc["facts"]
        if isinstance(f["value"], float)
    ]
    assert spy.latest and all(ts.date() < RESERVED_DAY for ts in spy.latest)


def test_labels_input_holds_the_period_back(
    tmp_path: Path, spy: Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    poisoned, cut = _pair(tmp_path)
    held = labels_cmds._read_bars("SPY", poisoned)
    plain = labels_cmds._read_bars("SPY", cut)
    assert HELD_BACK in held.labels and HELD_BACK not in plain.labels
    assert held.meta["reserve"]["held_back_bars"] == HELD and "reserve" not in plain.meta
    assert held.frame["close"].to_list() == pytest.approx(
        plain.frame["close"].to_list(), rel=1e-9, abs=1e-12
    )
    assert all(ts.date() < RESERVED_DAY for ts in spy.latest)


def test_a_cutoff_the_user_set_before_the_reserved_day_holds_nothing_back(
    tmp_path: Path,
) -> None:
    from alpha_cli.spine import reserve

    poisoned, _ = _pair(tmp_path)
    early = reserve.hold("SPY", data_dir=poisoned, as_of="2023-06-30")
    assert (early.held_back, early.research_cutoff, early.record_fields()) == (0, "2023-06-30", {})
    late = reserve.hold("SPY", data_dir=poisoned, as_of="2024-01-10")
    assert late.held_back == 10 and late.research_cutoff == reserve.CUTOFF_DATE
    assert reserve.hold("SPY", data_dir=poisoned).held_back == HELD
