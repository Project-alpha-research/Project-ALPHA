"""Idea input, trial durability and rule-run assembly contracts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from alpha_cli.spine.spec import IdeaSpec, load_spec
from alpha_core import Bar, DataError


def test_files_flags_and_canonical_hash(tmp_path: Path) -> None:
    toml = tmp_path / "idea.toml"
    toml.write_text('assets = ["SPY"]\n[rule]\nkind = "ma_cross"\nfast = 5\nslow = 20\n')
    spec = load_spec(toml)
    flags = load_spec(None, rule="ma_cross", param=["slow=20", "fast=5"], asset=["SPY"])
    path = tmp_path / "idea.json"
    path.write_text(json.dumps(spec.model_dump(mode="json"), sort_keys=True))
    assert spec == flags == load_spec(path)
    assert spec.spec_sha256 == flags.spec_sha256
    assert spec.name == "ma_cross-5-20"
    assert spec.idea == ""
    assert spec.costs.fee_bps == pytest.approx(1)
    with pytest.raises(ValueError):
        spec.__setattr__("name", "changed")


@pytest.mark.parametrize(
    "rule, message",
    [
        ({"kind": "oops"}, "known.*ma_cross.*breakout.*tsmom"),
        ({"kind": "breakout", "window": 20, "oops": 1}, "known.*window"),
        ({"kind": "ma_cross", "fast": 20, "slow": 5}, "fast.*slow"),
        ({"kind": "tsmom", "lookback": 0}, "greater than"),
        ({"kind": "tsmom", "lookback": 2.5}, "integer"),
    ],
)
def test_invalid_rules(rule: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        IdeaSpec(assets=["SPY"], rule=rule)


def test_flags_conflicts_and_defaults(tmp_path: Path) -> None:
    spec = load_spec(None, rule="tsmom", param=["lookback=20"], asset=["BTC/USDT"])
    assert spec.rule.params == {"lookback": 20, "skip": 0}
    with pytest.raises(ValueError, match="spec file"):
        load_spec(tmp_path / "spec.toml", rule="tsmom")
    with pytest.raises(ValueError, match="duplicate"):
        load_spec(None, rule="tsmom", param=["lookback=20", "lookback=30"], asset=["SPY"])


def test_ledger_append_repeat_and_corruption(tmp_path: Path) -> None:
    from alpha_cli.spine.ledger import append_trial

    first = append_trial(tmp_path, {"run_id": "a", "labels": ["all-in"]})
    second = append_trial(tmp_path, {"run_id": "a", "labels": ["all-in"]})
    assert first["schema"] == "AlphaTrialV1"
    assert first["trial_index"] == first["total_trials"] == 1
    assert second["trial_index"] == second["total_trials"] == 2
    assert second["labels"] == ["all-in", "repeat"]
    ledger = tmp_path / "ledger/trials.jsonl"
    original = ledger.read_bytes()
    ledger.write_bytes(original + b'{"broken":')
    with pytest.raises(DataError, match="corrupt"):
        append_trial(tmp_path, {"run_id": "b", "labels": []})
    assert ledger.read_bytes() == original + b'{"broken":'


@pytest.mark.parametrize(
    "kind,params,warmup",
    [
        ("ma_cross", ["fast=5", "slow=20"], 20),
        ("breakout", ["window=20"], 21),
        ("tsmom", ["lookback=20"], 21),
    ],
)
def test_run_assembly(kind: str, params: list[str], warmup: int) -> None:
    from alpha_cli.spine.run import assemble_run_spec

    idea = load_spec(None, rule=kind, param=params, asset=["BTC/USDT"])
    spec = assemble_run_spec(idea, "BTC/USDT", 365, 800)
    assert spec.sizing == "all_in"
    assert not spec.allow_short
    assert spec.account_type == "MARGIN"
    assert spec.rebalance_every == 1
    assert spec.max_leverage == pytest.approx(1)
    assert spec.train_size == warmup == spec.min_train
    assert spec.anchored
    available = 799 - spec.train_size - spec.embargo
    assert available % spec.test_size < 5
    with pytest.raises(DataError, match="bars"):
        assemble_run_spec(idea, "SPY", 252, warmup + 59)


def test_alpaca_market() -> None:
    from alpha_web._runs import market_of

    assert market_of({"source": "alpaca", "symbol": "SPY"}) == "equities"


def test_run_records_errors_and_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alpha_cli import _gauntlet, _runner
    from alpha_cli.spine import run
    from alpha_data.store import ParquetStore
    from tests.fixtures.cli_fixtures import seed_store

    seed_store(tmp_path, symbol="SPY", n=100)
    # Strict pull provenance: bar reads reject a partial provenance file.
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    idea = load_spec(None, rule="tsmom", param=["lookback=20"], asset=["MISSING", "SPY"])
    seen = []

    def fail_gauntlet(
        bars: Sequence[Bar],
        spec: _runner.RunSpec,
        knobs: _gauntlet.GauntletParams,
        **kwargs: object,
    ) -> None:
        seen.append((bars, spec, knobs, kwargs))
        raise DataError("injected gauntlet failure")

    monkeypatch.setattr(_gauntlet, "run_gauntlet", fail_gauntlet)
    output = run.run_idea(idea, home=tmp_path, quick=True)
    assert len(seen) == 1
    bars, spec, knobs, kwargs = seen[0]
    assert len(bars) == 100
    assert spec.sizing == "all_in"
    assert knobs.tier1_paths == 20
    assert knobs.max_workers == 1
    assert kwargs["dividends"] == []
    assert "not found" in output["results"][0]["error"]
    assert "injected gauntlet failure" in output["results"][1]["error"]
    rows = [
        json.loads(line) for line in (tmp_path / "ledger/trials.jsonl").read_text().splitlines()
    ]
    assert len(rows) == output["trials_total"] == 2
    assert rows[0]["run_id"] is None
    assert all("error" in row["labels"] for row in rows)
    assert rows[1]["periods_per_year"] == 365
    assert rows[1]["dsr"] is None


def test_cli_json_partial_and_all_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import typer
    from typer.testing import CliRunner

    from alpha_cli import test_cmds

    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    app = typer.Typer()
    app.command()(test_cmds.test_rule)
    runner = CliRunner()
    args = ["--rule", "breakout", "--param", "window=20", "--asset", "MISSING", "--json"]
    failed = runner.invoke(app, args)
    assert failed.exit_code == 1, failed.output
    error = json.loads(failed.output)["error"]
    assert error["code"] == "UNKNOWN_ASSET"
    assert "not found" in error["message"]
    assert error["known"] == ["home"]
    assert "alpha test" in error["next"]
    output = {
        "test_id": "id",
        "name": "name",
        "trials_total": 2,
        "results": [
            {
                "asset": "MISSING",
                "run_id": None,
                "verdict": None,
                "oos_sharpe": None,
                "labels": [],
                "error": "missing",
            },
            {
                "asset": "SPY",
                "run_id": "run",
                "verdict": "F",
                "oos_sharpe": None,
                "labels": [],
                "error": None,
            },
        ],
    }
    monkeypatch.setattr(test_cmds, "run_idea", lambda *args, **kwargs: output)
    partial = runner.invoke(app, args)
    assert partial.exit_code == 0, partial.output
    assert json.loads(partial.output) == output


def test_json_redirects_renderer_status_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import typer
    from typer.testing import CliRunner

    from alpha_cli import test_cmds

    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    output = {
        "test_id": "id",
        "name": "name",
        "trials_total": 1,
        "results": [
            {
                "asset": "SPY",
                "run_id": "run",
                "verdict": "B",
                "oos_sharpe": 1.2,
                "labels": [],
                "error": None,
            },
        ],
    }

    def noisy_run(*args: object, **kwargs: object) -> dict[str, object]:
        print("HTML report saved to: artifact")
        return output

    monkeypatch.setattr(test_cmds, "run_idea", noisy_run)
    app = typer.Typer()
    app.command()(test_cmds.test_rule)
    result = CliRunner().invoke(
        app, ["--rule", "breakout", "--param", "window=20", "--asset", "SPY", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == output
    assert "HTML report saved" in result.stderr
