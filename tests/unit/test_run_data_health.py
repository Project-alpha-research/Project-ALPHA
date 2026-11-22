"""Health evidence belongs to the exact daily inputs of each immutable run."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import polars as pl
import pytest
from typer.testing import CliRunner

from alpha_cli.main import app
from alpha_cli.spine.check import check_text
from alpha_cli.spine.stores import resolve_asset
from alpha_data.store import ParquetStore

CHECKED = datetime(2024, 1, 4, 23, tzinfo=UTC)


def series(home: Path, symbol: str, prices: tuple[float, float] = (101, 102)) -> ParquetStore:
    store = ParquetStore(home / "store")
    store.write_bars(
        symbol,
        pl.DataFrame(
            {
                "ts": [datetime(2024, 1, d, tzinfo=UTC) for d in (3, 4)],
                **{k: list(prices) for k in ("open", "high", "low", "close")},
                "volume": [200, 205],
            }
        ),
    )
    store.write_provenance(symbol, source="alpaca", adapter_version="1", parser_version="1")
    return store


def test_lookup_and_refresh(tmp_path: Path) -> None:
    from alpha_cli.spine.data_health import HealthRecord, run_health_record

    store = series(tmp_path, "ABC")
    asset = resolve_asset("ABC", data_dir=tmp_path)

    def lookup(check: bool = False, at: datetime = CHECKED) -> HealthRecord:
        return run_health_record([asset], check_data=check, report_time=at)

    missing = lookup()
    assert missing["verdict"] == "unchecked"
    assert "uv run alpha data health ABC@home" in missing["sentence"]
    report = lookup(True)
    assert report["verdict"] == "pass"
    path = store.root / "health/ABC.json"
    before = path.read_bytes()
    assert lookup(True, datetime(2025, 1, 4, tzinfo=UTC)) == report
    assert path.read_bytes() == before
    provenance = store.root / "provenance/ABC.json"
    provenance.write_bytes(provenance.read_bytes() + b" ")
    stale = lookup()
    assert stale["verdict"] == "out-of-date"
    assert stale.guards != report.guards  # the guard still bites on the whole stored file
    late = lookup(True, datetime(2024, 2, 1, tzinfo=UTC))
    assert late["verdict"] == "warn"
    assert late["series"][0]["checks"] and late["sentence"] != missing["sentence"]


def test_stock_peers_worst_and_override(tmp_path: Path) -> None:
    from alpha_cli.spine.data_health import run_health_record
    from alpha_cli.spine.errors import SpineError

    store = series(tmp_path, "SPLIT", (100, 50))
    for i in range(22):
        series(tmp_path, f"P{i:02}")
    series(tmp_path, "BTC/USD")
    for symbol in ("SPLIT", "P00"):
        assert resolve_asset(symbol, data_dir=tmp_path).store_name == "home"
    assets = [resolve_asset(name, data_dir=tmp_path) for name in ("P00", "SPLIT")]
    with pytest.raises(SpineError) as stopped:
        run_health_record(assets, check_data=True, report_time=CHECKED)
    message = str(stopped.value)
    for word in ("SPLIT@home", "2024-01-04", "quiet", "Fix the data", '--accept-bad-data "reason"'):
        assert word in message
    report = run_health_record(assets, accept_bad_data="inspect raw prices")
    assert report["verdict"] == "fail" and report["override_reason"] == "inspect raw prices"
    assert report["series"][1]["peers_used"] == 20
    assert "20" in report["sentence"]
    assert report["series"][0]["status"] == "pass"
    with pytest.raises(SpineError):
        run_health_record(assets)
    path = store._bars_path("P00")
    path.write_bytes(path.read_bytes() + b" ")
    assert run_health_record(assets[1:])["verdict"] == "out-of-date"


def test_cli_stops_before_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alpha_cli import _gauntlet
    from alpha_cli.spine.data_health import run_health_record
    from tests.unit.test_setup_find import seed

    seed(tmp_path, symbol="READY", n=400)
    series(tmp_path, "BAD", (100, 50))
    series(tmp_path, "PEER")
    run_health_record(
        [resolve_asset("BAD", data_dir=tmp_path)],
        check_data=True,
        accept_bad_data="test",
        report_time=CHECKED,
    )
    engine = Mock()
    monkeypatch.setattr(_gauntlet, "run_gauntlet", engine)
    result = CliRunner(env={"ALPHA_DATA_DIR": str(tmp_path)}).invoke(
        app,
        [
            "test",
            "--rule",
            "breakout",
            "--param",
            "window=2",
            "--asset",
            "READY",
            "--asset",
            "BAD",
            "--json",
        ],
    )
    assert result.exit_code == 1, result.output
    message = json.loads(result.stdout)["error"]["message"]
    for words in (
        "BAD@home, check unflagged split",
        "First dates: 2024-01-04",
        "covers all stored",
    ):
        assert words in message
    assert '--accept-bad-data "reason"' in message
    engine.assert_not_called()
    # Nothing is half-written: no run folder and no trial row.
    assert not (tmp_path / "runs").exists()
    assert not (tmp_path / "ledger" / "trials.jsonl").exists()


@pytest.mark.parametrize("reason", ["", "   "])
def test_blank_override_reason_stops_the_rule_test(tmp_path: Path, reason: str) -> None:
    from tests.unit.test_setup_find import seed

    seed(tmp_path, symbol="READY", n=400)
    result = CliRunner(env={"ALPHA_DATA_DIR": str(tmp_path)}).invoke(
        app,
        ["test", "--rule", "breakout", "--param", "window=2", "--asset", "READY"]
        + ["--accept-bad-data", reason, "--json"],
    )
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["error"]["code"] == "BAD_OPTION"
    assert not (tmp_path / "ledger" / "trials.jsonl").exists()


@pytest.mark.parametrize(
    "label", ["data-health-fail", "data-health-overridden", "data-health-unchecked"]
)
def test_citation_requires_health(label: str) -> None:
    def lookup(run_id: str, metric: str) -> dict[str, Any]:
        return dict(run_id=run_id, metric=metric, value=12, labels=[label])

    citation = "12 [aaaaaaaa:total_trials]"
    assert any(row["stored"] == label for row in check_text(citation, lookup)["problems"])
    assert check_text(f"{label}: {citation}", lookup)["ok"]


def test_old_run_sentence(tmp_path: Path) -> None:
    run_id = "a" * 16
    folder = tmp_path / "runs" / run_id
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text('{"command":"validate","spine":{"labels":[]}}')
    response = CliRunner(env={"ALPHA_DATA_DIR": str(tmp_path)}).invoke(
        app, ["results", "show", run_id]
    )
    assert response.exit_code == 0, response.output
    assert response.output.splitlines()[0] == "Data health: not recorded."


def test_setup_override_is_per_invocation(tmp_path: Path) -> None:
    from alpha_cli.setup_cmds import run_find
    from alpha_cli.spine.errors import SpineError
    from alpha_cli.spine.setup_study import run_study
    from alpha_cli.spine.setup_trade import run_trade
    from tests.unit.test_setup_find import spec_file, worked_store

    worked_store(tmp_path)
    path = spec_file(tmp_path)
    path.write_text(path.read_text() + "[study]\nhorizons=[1,5]\nprimary=5\n[exit]\ntime_bars=5\n")
    with pytest.raises(SpineError, match="Fix the data"):
        run_find(path, home=tmp_path, check_data=True, report_time=CHECKED)
    found = run_find(path, home=tmp_path, accept_bad_data="inspect")
    with pytest.raises(SpineError, match="needs a reason"):
        run_find(path, home=tmp_path, accept_bad_data=" ")
    for run in (run_study, run_trade):
        with pytest.raises(SpineError, match="needs a reason"):
            run(found["find_id"], home=tmp_path, accept_bad_data="")
        with pytest.raises(SpineError, match="Fix the data"):
            run(found["find_id"], home=tmp_path)
        out = run(found["find_id"], home=tmp_path, accept_bad_data="inspect again")
        manifest = json.loads((Path(out["folder"]) / "manifest.json").read_bytes())
        assert manifest["data_health"]["override_reason"] == "inspect again"
        assert {"data-health-fail", "data-health-overridden"} <= set(manifest["labels"])
        assert out["facts"][0]["labels"] == out["labels"]


def test_rule_override_is_stored(tmp_path: Path) -> None:
    from alpha_cli.spine.run import run_idea
    from alpha_cli.spine.spec import load_spec
    from tests.unit.test_setup_find import seed

    seed(tmp_path, n=400)
    idea = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    result = run_idea(
        idea,
        home=tmp_path,
        quick=True,
        no_diagnose=True,
        check_data=True,
        accept_bad_data="inspect synthetic series",
        report_time=CHECKED,
    )["results"][0]
    assert result["error"] is None, result["error"]
    manifest = json.loads((Path(result["run_dir"]) / "manifest.json").read_bytes())
    assert manifest["data_health"]["override_reason"] == "inspect synthetic series"
    assert {"data-health-fail", "data-health-overridden", "dev-machine-data"} <= set(
        manifest["spine"]["labels"]
    )
    printed = CliRunner(env={"ALPHA_DATA_DIR": str(tmp_path)}).invoke(
        app, ["results", "show", result["run_id"]]
    )
    assert manifest["data_health"]["sentence"] == printed.stdout.splitlines()[0]


def test_tool_citation_carries_run_health(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alpha_cli import results_cmds
    from alpha_cli.toolbox.registry import METRIC_OUTPUTS

    run_id = "d" * 16
    folder = tmp_path / "runs" / run_id
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(
        json.dumps({"spine": {"labels": ["data-health-unchecked"]}})
    )

    def tool_fact(home: Path, run_id: str, metric: str, output_id: str | None) -> dict[str, Any]:
        return dict(run_id=run_id, metric=metric, value=12, labels=["non-default-params"])

    monkeypatch.setattr(results_cmds, "tool_fact", tool_fact)
    metric = next(iter(METRIC_OUTPUTS))
    fact = results_cmds.fact_lookup(tmp_path)(run_id, metric)
    assert fact["labels"] == ["non-default-params", "data-health-unchecked"]


def test_old_find_is_preserved_and_health_does_not_change_controls(tmp_path: Path) -> None:
    from alpha_cli.setup_cmds import run_find
    from alpha_cli.spine.setup_study import run_study
    from tests.unit.test_setup_study import make_find

    original = make_find(tmp_path)
    first = run_study(original["find_id"], home=tmp_path)
    folder = Path(original["folder"])
    for name in ("manifest.json", "summary.json"):
        path = folder / name
        value = json.loads(path.read_bytes())
        del value["data_health"]
        value["labels"].remove("data-health-unchecked")
        path.write_text(json.dumps(value))
    legacy = (folder / "manifest.json").read_bytes()
    retry = run_find(tmp_path / "spec.toml", home=tmp_path)
    # The id no longer holds the health record (it describes held-back rows too): the same find.
    assert retry["find_id"] == original["find_id"] and retry["executed"] is False
    assert (folder / "manifest.json").read_bytes() == legacy
    later = run_study(
        retry["find_id"],
        home=tmp_path,
        check_data=True,
        report_time=CHECKED,
        accept_bad_data="inspect synthetic weekends",
    )
    assert first["horizons"] == later["horizons"]


def test_only_overlapping_stock_peers_from_this_store(tmp_path: Path) -> None:
    from alpha_cli.spine.data_health import run_health_record

    home = tmp_path / "stocks"
    store = series(home, "TARGET")
    series(home, "PEER")
    series(home, "BTC/USD")
    series(home, "BTCUSDT").write_provenance(
        "BTCUSDT", source="binance", adapter_version="1", parser_version="1"
    )
    series(home, "LATER")
    store.write_bars(
        "LATER", store.read_bars("LATER").with_columns(pl.col("ts").dt.offset_by("2mo"))
    )
    series(tmp_path, "OUTSIDE")
    (tmp_path / "stores.toml").write_text('market="stocks"')
    asset = resolve_asset("TARGET@market", data_dir=tmp_path)
    record = run_health_record([asset], check_data=True, report_time=CHECKED)
    assert record["series"][0]["asset"] == "TARGET@market"
    saved = json.loads((store.root / "health/TARGET.json").read_bytes())
    assert saved["peer_symbols"] == ["PEER"]


def test_stale_outranks_missing_and_missing_outranks_a_warning(tmp_path: Path) -> None:
    from alpha_cli.spine.data_health import health_labels, run_health_record

    series(tmp_path, "WARN")
    store = series(tmp_path, "CHANGED")
    series(tmp_path, "MISSING")
    assets = [resolve_asset(name, data_dir=tmp_path) for name in ("WARN", "MISSING", "CHANGED")]
    run_health_record(assets[::2], check_data=True, report_time=datetime(2024, 2, 1, tzinfo=UTC))
    assert run_health_record(assets)["verdict"] == "unchecked"
    # Actions belong to the checked series; the peer comparison reads only prices.
    store.write_actions("CHANGED", [])
    record = run_health_record(assets)
    assert [row["status"] for row in record["series"]] == ["warn", "unchecked", "out-of-date"]
    assert record["verdict"] == "out-of-date"
    assert health_labels(record) == ["data-health-unchecked"]


@pytest.mark.parametrize(
    ("labels", "disclosure"),
    [
        (["data-health-unchecked"], "Data health: unchecked."),
        (["data-health-unchecked"], "Data health: out-of-date."),
        (
            ["data-health-fail", "data-health-overridden"],
            "Data health: fail. Data health overridden: inspect.",
        ),
    ],
)
def test_printed_health_wording_satisfies_citation(labels: list[str], disclosure: str) -> None:
    def lookup(run_id: str, metric: str) -> dict[str, Any]:
        return dict(run_id=run_id, metric=metric, value=12, labels=labels)

    assert check_text(f"{disclosure} 12 [aaaaaaaa:total_trials]", lookup)["ok"]
    assert not check_text(f"`{disclosure}` 12 [aaaaaaaa:total_trials]", lookup)["ok"]


def _pass_report(home: Path, symbol: str) -> None:
    """Store a matching report and mark every check passed: the run reads only the result."""
    from alpha_cli.spine.data_health import run_health_record

    asset = resolve_asset(symbol, data_dir=home)
    run_health_record([asset], check_data=True, accept_bad_data="x", report_time=CHECKED)
    path = home / "store" / "health" / f"{symbol}.json"
    saved = json.loads(path.read_bytes())
    saved["verdict"] = "pass"
    saved["checks"] = [{**check, "status": "pass"} for check in saved["checks"]]
    path.write_text(json.dumps(saved))


def _without_health(manifest: dict[str, Any], run_id: str, test_id: str) -> str:
    manifest.pop("data_health")
    reading = manifest["reading"]
    reading["checks"] = [c for c in reading["checks"] if c["name"] != "data-health"]
    spine = manifest["spine"]
    spine["labels"] = [x for x in spine["labels"] if not x.startswith("data-health-")]
    manifest["artifacts"]["tearsheet.html"].pop("sha256")
    return json.dumps(manifest, sort_keys=True).replace(run_id, "RUN").replace(test_id, "TEST")


def test_a_pass_report_changes_nothing_but_the_health_record(tmp_path: Path) -> None:
    """Byte proof: the same series with and without a report gives the same stored run."""
    from alpha_cli.spine.run import run_idea
    from alpha_cli.spine.spec import load_spec
    from tests.unit.test_setup_find import seed

    idea = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    outputs: list[dict[str, Any]] = []
    for label in ("before", "after"):
        home = tmp_path / label
        seed(home, n=400)
        if label == "after":
            _pass_report(home, "SPY")
        outputs.append(run_idea(idea, home=home, quick=True, no_diagnose=True))
    (before, old_test), (after, new_test) = ((o["results"][0], o["test_id"]) for o in outputs)
    assert (before["data_health"]["verdict"], after["data_health"]["verdict"]) == (
        "unchecked",
        "pass",
    )
    assert after["data_health"]["sentence"] == (
        "Data health: pass. SPY@home: report of 2024-01-04 covers all stored bars. "
        "SPY@home: 0 stock peers used."
    )
    old_dir, new_dir = Path(before["run_dir"]), Path(after["run_dir"])
    names = sorted(p.relative_to(old_dir) for p in old_dir.rglob("*") if p.is_file())
    assert names == sorted(p.relative_to(new_dir) for p in new_dir.rglob("*") if p.is_file())
    for name in names:
        old, new = (old_dir / name).read_bytes(), (new_dir / name).read_bytes()
        if name.name == "tearsheet.html":
            old = old.replace(before["run_id"].encode(), b"RUN")
            new = new.replace(after["run_id"].encode(), b"RUN")
        if name.name == "manifest.json":
            old_text = _without_health(json.loads(old), before["run_id"], old_test)
            assert old_text == _without_health(json.loads(new), after["run_id"], new_test)
        else:
            assert old == new, name
    for key in ("oos_sharpe", "benchmark_sharpe", "dsr", "verdict", "flags"):
        assert before[key] == after[key]
