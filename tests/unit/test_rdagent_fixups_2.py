"""Regression contracts for the second real-loop fix-up brief."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import rdagent_factor_eval as ev
from alpha_cli._rdagent_clocks import clock_feedback
from alpha_cli.ledger_cmds import ledger_app
from alpha_cli.spine.trial_reader import LedgerSource, read_ledgers, trials_for_deflation
from alpha_cli.spine.trial_record import map_row
from tests.unit.test_rdagent_factor_eval import fixture
from tests.unit.test_trial_record import factor


def test_spread_failure_listed_and_counted_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "trials.jsonl"
    ledger.write_text(json.dumps(factor(version=2, status="SPREAD_FAIL")) + "\n")
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    args = ["list", "--rdagent-ledger", str(ledger)]
    result = CliRunner().invoke(ledger_app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)["records"]
    assert len(rows) == 1 and rows[0]["outcome"] == "rejected"
    assert rows[0]["raw_status"] == "SPREAD_FAIL"
    assert "stopped by the spread check" in CliRunner().invoke(ledger_app, args).output
    snapshot = read_ledgers([LedgerSource("rdagent", str(ledger))])
    assert trials_for_deflation(snapshot, "rdagent-factors")["all_trials"] == 1


def test_ledger_reads_the_default_rdagent_ledger_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "data"
    home.mkdir()
    default = tmp_path / "runs/rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    default.parent.mkdir(parents=True)
    default.write_text(json.dumps(factor(version=2, status="SPREAD_FAIL")) + "\n")
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    output = CliRunner().invoke(ledger_app, ["summary"]).output
    assert f"rdagent: read {default.resolve()}" in output
    assert "not understood" not in output
    # A configured source still wins; the default is only the fallback.
    configured = tmp_path / "elsewhere.jsonl"
    (home / "ledger").mkdir()
    (home / "ledger/sources.toml").write_text(f'[rdagent]\nfactor_ledger = "{configured}"\n')
    output = CliRunner().invoke(ledger_app, ["summary"]).output
    assert f"rdagent: ledger file not found ({configured})" in output


def test_spread_message_says_replay_counts_only() -> None:
    row = factor(version=2, status="SPREAD_FAIL", screen={}, replay={"counted_only": "spread"})
    assert "replayed only to count the trial; its result is not used" in clock_feedback(row)


@pytest.mark.parametrize("reason", ["critic_rejected", "cap_reached", "exception", "bad_output"])
def test_failure_reason_reaches_ledger_and_proposer(tmp_path: Path, reason: str) -> None:
    run = tmp_path / "run"
    request_path = fixture(run)
    request = json.loads(request_path.read_text())
    request["factors"][0].update(
        status="FAILED", failure_reason=reason, failure_detail="first error line"
    )
    request_path.write_text(json.dumps(request))
    ledger = tmp_path / "ledger.jsonl"
    result = ev.evaluate(run, request_path, run / "result.json", ledger)
    row = json.loads(ledger.read_text())
    assert row["failure_reason"] == reason
    assert reason in result["feedback_text"]
    assert "first error line" in result["feedback_text"]


def test_recorded_at_takes_precedence_and_old_dates_still_work() -> None:
    row = factor(recorded_at="2026-11-17T03:04:05+00:00")
    record = map_row("rdagent", Path("/ledger"), 1, row)
    assert record.created_at == row["recorded_at"] and record.created_at_basis == "recorded"
    del row["recorded_at"]
    assert map_row("rdagent", Path("/ledger"), 1, row).created_at == "2026-11-15"


def test_evaluation_uses_receipt_identity_and_records_utc(tmp_path: Path) -> None:
    run = tmp_path / "different-folder-name"
    request_path = fixture(run)
    (run / "run-identity.json").write_text(json.dumps({"run_id": "receipt-id"}))
    request = json.loads(request_path.read_text())
    request["factors"][0].update(status="FAILED", failure_reason="critic_rejected")
    request_path.write_text(json.dumps(request))
    result = ev.evaluate(run, request_path, run / "result.json", tmp_path / "ledger")
    row = result["factors"][0]
    assert row["run_id"] == "receipt-id"
    assert datetime.fromisoformat(row["recorded_at"]).tzinfo == UTC


def test_proposer_counts_have_plain_labels(tmp_path: Path) -> None:
    run = tmp_path / "run"
    request_path = fixture(run)
    request: dict[str, Any] = json.loads(request_path.read_text())
    request["factors"][0].update(status="FAILED", failure_reason="critic_rejected")
    request_path.write_text(json.dumps(request))
    result = ev.evaluate(run, request_path, run / "result.json", tmp_path / "ledger")
    assert (
        "Factor-family trials (primary clocks now; legacy clocks and unreadable rows included): 1"
        in result["feedback_text"]
    )
    assert "Ledger rows, all families (rules, repeats too): 1" in result["feedback_text"]
    assert "ledger_trials_all_families:" not in result["feedback_text"]
