"""Idea spec -> two stores -> validation artifacts -> ledger and web reader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from alpha_data.store import ParquetStore
from alpha_web._runs import query_runs, run_artifacts_readable
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]


def test_rule_test_records_two_assets(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    data = home / "data"
    other = home / "crypto"
    for directory, symbol, source in ((data, "SPY", "alpaca"), (other, "BTC/USDT", "binance")):
        seed_store(directory, symbol=symbol, n=400)
        provenance = ParquetStore(directory / "store")._provenance_path(symbol)
        provenance.parent.mkdir(parents=True, exist_ok=True)
        provenance.write_text(json.dumps({"source": source}))
    (data / "stores.toml").write_text('crypto = "../crypto"\n')
    spec = home / "spec.toml"
    spec.write_text(
        'assets = ["SPY", "BTC/USDT@crypto"]\n[rule]\nkind = "ma_cross"\nfast = 5\nslow = 20\n'
    )
    ran = alpha(home, "test", str(spec), "--quick", "--json")
    output = ran.json()
    assert len(output["results"]) == 2
    assert output["trials_total"] == 2
    run_ids = set()
    original = {}
    for result in output["results"]:
        assert result["error"] is None, result
        run_id = result["run_id"]
        run_ids.add(run_id)
        rdir = data / "runs" / run_id
        assert Path(result["run_dir"]) == rdir
        manifest = json.loads((rdir / "manifest.json").read_text())
        assert manifest["command"] == "validate"
        assert manifest["spine"]["test_id"] == output["test_id"]
        assert manifest["spine"]["spec_sha256"] == output["spec_sha256"]
        assert {"all-in", "dev-machine-data", "short-history", "quick"} <= set(result["labels"])
        assert {"spec.json", "diagnostics.json"} <= manifest["artifacts"].keys()
        assert result["variants_evaluated"] == 5
        assert result["facts"]
        assert isinstance(result["flags"], list)
        assert json.loads((rdir / "spec.json").read_text())["spec_sha256"] == output["spec_sha256"]
        assert run_artifacts_readable("runs", run_id, data_dir=data)
        original[run_id] = {
            path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in rdir.iterdir()
        }
    assert len(run_ids) == 2
    records = query_runs(data_dir=data)["items"]
    assert {row["run_id"] for row in records} == run_ids
    assert {row["market"] for row in records} == {"equities", "crypto"}
    ledger = data / "ledger/trials.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [row["trial_index"] for row in rows] == [1, 2]
    assert all(row["schema"] == "AlphaTrialV1" for row in rows)
    again = alpha(home, "test", str(spec), "--quick", "--json").json()
    assert again["trials_total"] == 4
    assert {row["run_id"] for row in again["results"]} == run_ids
    assert all("repeat" in row["labels"] for row in again["results"])
    for run_id in run_ids:
        assert {
            path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in (data / "runs" / run_id).iterdir()
        } == original[run_id]
