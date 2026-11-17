"""Installed rule test -> stored controls -> diagnose and checked citations."""

from pathlib import Path

import pytest

from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store
from tests.smoke._harness import alpha

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("owned_test_process")]


def test_inverted_control_and_wfe(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    data = home / "data"
    seed_store(data, n=400)
    ParquetStore(data / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    output = alpha(
        home,
        "test",
        "--rule",
        "ma_cross",
        "--param",
        "fast=5",
        "--param",
        "slow=20",
        "--asset",
        "SPY",
        "--quick",
        "--json",
    ).json()
    result = output["results"][0]
    assert result["error"] is None, result
    assert output["trials_total"] == 1
    run_id = result["run_id"]
    ledger = data / "ledger/trials.jsonl"
    before = ledger.read_bytes()
    diagnosed = alpha(home, "diagnose", run_id, "--json").json()
    inverse = diagnosed["inverted_signal"]
    assert inverse["label"] in {"control passed", "control failed", "inconclusive"}
    assert "Shorts are not tradable here; this is a control only." in inverse["sentence"]
    assert "No borrowing or funding cost is charged" in inverse["sentence"]
    wfe = diagnosed["walk_forward_efficiency"]
    assert wfe["folds_total"] > 0
    assert wfe["wfe"] is not None or wfe["reasons"]["wfe"]
    assert "practitioner rule of thumb, not a statistical test" in wfe["sentence"]
    assert diagnosed["variants_evaluated"] == 5
    for metric in (
        "inverted_sharpe",
        "inverted_sharpe_se",
        "inverted_total_return",
        "inverted_trades",
    ):
        fact = alpha(home, "results", "cite", run_id, metric, "--json").json()
        assert fact["value"] == inverse[metric]
    human = alpha(home, "diagnose", run_id).stdout
    assert "standard error" in human and "practitioner rule of thumb" in human
    draft = home / "answer.md"
    draft.write_text(
        f"Quick look; short history; too few trades. Trial count 1 [{run_id}:total_trials]. "
        f"Inverted trades {inverse['inverted_trades']} [{run_id}:inverted_trades]. "
    )
    assert alpha(home, "results", "check", str(draft), "--json").json()["ok"]
    shown = alpha(home, "results", "show", run_id, "--json").json()
    assert any(f["metric"] == "wfe" and f["value"] == wfe["wfe"] for f in shown["runs"][0]["facts"])
    assert ledger.read_bytes() == before
