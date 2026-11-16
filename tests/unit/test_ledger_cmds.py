"""CLI envelopes, read-only reports and evidence hashes."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli.ledger_cmds import ledger_app
from tests.unit.test_trial_reader import example, write_rows
from tests.unit.test_trial_record import factor, rule


@pytest.mark.parametrize(
    "args", [["summary"], ["list"], ["families"], ["query", "by-outcome"], ["show", "spine:1"]]
)
def test_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: Any) -> None:
    home, rd = example(tmp_path)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    result = CliRunner().invoke(ledger_app, [*args, "--rdagent-ledger", str(rd), "--json"])
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    if args == ["summary"]:
        assert output["sources"][1]["mapped"] == 4 and output["sources"][1]["unknown"] == 2
        assert output["by_kind"] == {"rule_test": 3, "factor": 3, "rule_family": 1}
    human = CliRunner().invoke(ledger_app, [*args, "--rdagent-ledger", str(rd)])
    assert human.exit_code == 0, human.output
    assert human.output.rstrip().endswith("Read-only view; the ledgers themselves are unchanged.")
    assert {
        p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()
    } == before


@pytest.mark.parametrize("is_rule", [False, True])
def test_evidence_match_mismatch_and_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, is_rule: Any
) -> None:
    home, rd = example(tmp_path)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    content = b'{"evidence":true}'
    row = (rule if is_rule else factor)(
        evidence={
            "trial" if is_rule else "series_manifest": "evidence.json",
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    )
    write_rows(rd, [row])
    root = rd.parent.parent / "study" if is_rule else rd.parent.parent
    path = root / row["run_id"] / "evidence.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    args = ["show", "rdagent:1", "--rdagent-ledger", str(rd), "--json"]
    for expected in (True, False):
        result = CliRunner().invoke(ledger_app, args)
        assert result.exit_code == 0, result.output
        output = json.loads(result.output)
        assert output["raw_row"] == row
        assert output["evidence_found"] and output["evidence_matches"] is expected
        path.write_bytes(b"changed")
    path.unlink()
    assert json.loads(CliRunner().invoke(ledger_app, args).output)["evidence_found"] is False


def test_filters_and_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home, rd = example(tmp_path)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    runner = CliRunner()
    result = runner.invoke(
        ledger_app,
        [
            "list",
            "--kind",
            "rule_test",
            "--family",
            "spine:ma_cross",
            "--asset",
            "SPY",
            "--source",
            "spine",
            "--outcome",
            "rejected",
            "--limit",
            "1",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["records"][0]["trial_id"] == "spine:2"
    for args, code in [
        (["show", "missing"], "UNKNOWN_TRIAL"),
        (["query", "not-a-question"], "UNKNOWN_QUESTION"),
        (["query", "asset-history"], "BAD_PARAMETER"),
    ]:
        result = runner.invoke(ledger_app, [*args, "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error"]["code"] == code


def test_human_top_measure_and_spine_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, rd = example(tmp_path)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    evidence = home / "runs/abc/manifest.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(b"manifest")
    shown = CliRunner().invoke(ledger_app, ["show", "spine:1", "--json"])
    assert shown.exit_code == 0, shown.output
    result = json.loads(shown.output)
    assert result["evidence_found"] is True and result["evidence_matches"] is None
    assert result["evidence_sha256_now"] == hashlib.sha256(b"manifest").hexdigest()
    human = CliRunner().invoke(ledger_app, ["query", "top-measure", "--measure", "oos_sharpe"])
    assert human.exit_code == 0, human.output
    assert "measure_value" in human.output and "0.7" in human.output
