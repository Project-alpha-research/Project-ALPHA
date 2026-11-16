"""Installed rule test followed by unified ledger reads and a DuckDB question."""

import json
from pathlib import Path

import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]


def test_ledger_reads_rule_and_factor_trials(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    data = home / "data"
    seed_store(data, symbol="SPY", n=400)
    ParquetStore(data / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    spec = home / "idea.toml"
    spec.write_text('assets = ["SPY"]\n[rule]\nkind = "ma_cross"\nfast = 5\nslow = 20\n')
    ran = alpha(home, "test", str(spec), "--quick", "--json").json()
    assert ran["results"][0]["error"] is None
    ledger = home / "factors.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "schema": "AlphaRdagentFactorTrialV1",
                "trial_index": 1,
                "name": "Smoke factor",
                "code_sha256": "a" * 64,
                "run_id": "2026-11-16-smoke",
                "family_size": 1,
                "status": "SCREEN_FAIL",
                "p": 1.0,
                "q": 1.0,
                "screen": {},
                "label": "exploratory",
                "survivorship": [],
                "authority": {"admitted": False},
                "windows": {
                    "history": ["2017-01-01", "2020-12-31"],
                    "exploration": ["2021-01-01", "2023-12-24"],
                    "panel_end": "2023-12-31",
                    "reserved_start": "2024-01-01",
                },
            }
        )
        + "\n"
    )
    paths = [ledger, data / "ledger/trials.jsonl", data / "ledger/trials.jsonl.lock"]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
    flags = ("--rdagent-ledger", str(ledger), "--json")
    summary = alpha(home, "ledger", "summary", *flags).json()
    assert summary["by_kind"] == {"rule_test": 1, "factor": 1}
    assert not summary["unknown"]
    queried = alpha(home, "ledger", "query", "by-outcome", *flags).json()
    assert {r["outcome"]: r["rows"] for r in queried["rows"]} == summary["by_outcome"]
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths} == before
