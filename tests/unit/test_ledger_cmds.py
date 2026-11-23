"""CLI envelopes, read-only reports and evidence hashes."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli.ledger_cmds import _evidence, ledger_app
from alpha_cli.spine.trial_reader import LedgerSource, read_ledgers, trials_for_deflation
from alpha_cli.spine.trial_record import map_row
from tests.unit._rdagent_support import clock_rows
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


def test_totals_wording_and_grouping_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home, rd = example(tmp_path)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    out = CliRunner().invoke(ledger_app, ["summary", "--rdagent-ledger", str(rd)]).output
    assert "2 ledger rows ALPHA could not interpret; the deflated Sharpe counts them anyway." in out
    assert (
        "You have tested" in out and "on all assets" in out
    )  # the one headline number, not the row total
    out = CliRunner().invoke(ledger_app, ["query", "by-asset", "--rdagent-ledger", str(rd)]).output
    assert "Grouping normalises names" in out


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


@pytest.fixture
def recorded_evidence_ledger(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    ledger = root / "ledger/trials.jsonl"
    ledger.parent.mkdir(parents=True)
    run = root / "human-folder"
    run.mkdir()
    (run / "run-identity.json").write_text(json.dumps({"run_id": "recorded-id"}))
    (run / "series.json").write_text("evidence")
    return ledger


def test_evidence_resolves_recorded_run_identity(
    tmp_path: Path, recorded_evidence_ledger: Path
) -> None:
    ledger = recorded_evidence_ledger
    row = factor(run_id="recorded-id", evidence={"series_manifest": "series.json"})
    assert _evidence(map_row("rdagent", ledger, 1, row), tmp_path)["evidence_found"]


@pytest.mark.parametrize(
    "other", ["not json", "[]", json.dumps({"other": 1}), json.dumps({"run_id": 7})]
)
def test_evidence_lookup_ignores_unrelated_unreadable_run_identities(
    tmp_path: Path, recorded_evidence_ledger: Path, other: str
) -> None:
    """An odd identity file in some other run folder must not break every evidence lookup."""
    ledger = recorded_evidence_ledger
    root = tmp_path / "runs"
    unrelated = root / "an-unrelated-run"
    unrelated.mkdir()
    (unrelated / "run-identity.json").write_text(other)
    row = factor(run_id="recorded-id", evidence={"series_manifest": "series.json"})
    assert _evidence(map_row("rdagent", ledger, 1, row), tmp_path)["evidence_found"]


def test_absent_optional_source_is_quiet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path / "data"))
    ledger = tmp_path / "ledger"
    ledger.write_text(json.dumps(factor()) + "\n")
    output = CliRunner().invoke(ledger_app, ["summary", "--rdagent-ledger", str(ledger)])
    assert output.exit_code == 0
    assert "ledger file not found" not in output.output
    assert f"rdagent: read {ledger}" in output.output


def test_missing_evidence_still_refuses_path_traversal(tmp_path: Path) -> None:
    from alpha_cli.spine.errors import SpineError

    root = tmp_path / "runs"
    ledger = root / "ledger/trials.jsonl"
    ledger.parent.mkdir(parents=True)
    row = factor(run_id="missing-run", evidence={"series_manifest": "../../outside.json"})
    with pytest.raises(SpineError, match="escapes"):
        _evidence(map_row("rdagent", ledger, 1, row), tmp_path)


def test_plain_ledger_names_clock_beside_figures(tmp_path: Path) -> None:
    from dataclasses import asdict

    from alpha_cli.ledger_cmds import _render

    record = map_row("rdagent", tmp_path / "ledger", 1, factor(clocks=clock_rows(0.99)))
    assert "weekly: IC 0.04, q 0.04" in _render({"records": [asdict(record)]})


def test_bare_ledger_lists_every_kind_with_a_kind_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, rd = example(tmp_path)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    out = CliRunner().invoke(ledger_app, ["--rdagent-ledger", str(rd)]).output
    header = out.splitlines()[0].split("\t")
    assert "kind" in header
    assert {"rule_test", "factor", "rule_family"} <= {
        line.split("\t")[header.index("kind")] for line in out.splitlines()[1:] if "\t" in line
    }


def test_the_default_list_keeps_a_share_for_every_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, rd = example(tmp_path)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    result = CliRunner().invoke(ledger_app, ["list", "--limit", "3", "--rdagent-ledger", str(rd)])
    kinds = {
        row["kind"]
        for row in json.loads(
            CliRunner()
            .invoke(ledger_app, ["list", "--limit", "3", "--rdagent-ledger", str(rd), "--json"])
            .output
        )["records"]
    }
    assert kinds == {"rule_test", "factor", "rule_family"}
    assert "Showing 3 of 7 rows" in result.output


def test_the_default_list_never_exceeds_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, rd = example(tmp_path)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    out = CliRunner().invoke(
        ledger_app, ["list", "--limit", "1", "--rdagent-ledger", str(rd), "--json"]
    )
    assert len(json.loads(out.output)["records"]) == 1


def test_rdagent_ledger_flag_works_before_and_after_the_subcommand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "data"
    home.mkdir()
    ledger = tmp_path / "elsewhere.jsonl"
    ledger.write_text(json.dumps(factor(version=2, status="SPREAD_FAIL")) + "\n")
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    for args in (
        ["--rdagent-ledger", str(ledger), "summary"],
        ["summary", "--rdagent-ledger", str(ledger)],
    ):
        output = CliRunner().invoke(ledger_app, args).output
        assert f"rdagent: read {ledger.resolve()}" in output, args


def test_default_rdagent_ledger_follows_the_workstation_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "data"
    home.mkdir()
    runs = tmp_path / "custom-runs"
    ledger = runs / "rdagent-trial-ledger/rdagent-factor-trials.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps(factor(version=2, status="SPREAD_FAIL")) + "\n")
    monkeypatch.setenv("ALPHA_DATA_DIR", str(home))
    monkeypatch.setenv("ALPHA_RDAGENT_RUNS_DIR", str(runs))

    output = CliRunner().invoke(ledger_app, ["summary"]).output

    assert f"rdagent: read {ledger.resolve()}" in output
