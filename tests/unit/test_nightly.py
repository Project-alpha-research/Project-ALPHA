"""The nightly run: fake command runner, step classes, append-only records, readiness streak."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from alpha_cli.nightly_config import NightlyConfig, NightlyConfigError, load_config
from alpha_cli.nightly_run import run_nightly
from alpha_cli.nightly_status import (
    last_night_line,
    read_records,
    readiness,
    status_facts,
    status_text,
)
from alpha_cli.nightly_steps import Outcome

Reply = Outcome | Callable[[list[str]], Outcome]


def ok(payload: object) -> Outcome:
    return Outcome(0, json.dumps(payload), "", 0.25, False)


def text(line: str) -> Outcome:
    return Outcome(0, line + "\n", "", 0.1, False)


class FakeRunner:
    """Answers the real commands with canned replies. Matches the start of the argument text."""

    def __init__(self, replies: dict[str, Reply] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.replies: dict[str, Reply] = {**_happy(), **(replies or {})}

    def __call__(self, argv: Sequence[str], timeout: float) -> Outcome:
        tail = list(argv)[3:]
        self.calls.append(tail)
        line = " ".join(tail)
        for prefix in sorted(self.replies, key=len, reverse=True):
            if line.startswith(prefix):
                reply = self.replies[prefix]
                return reply(tail) if callable(reply) else reply
        raise AssertionError(f"no fake reply for: {line}")


def _happy() -> dict[str, Reply]:
    run = {"asset": "SPY", "run_id": "r1", "verdict": "C", "error": None, "labels": ["quick"]}
    return {
        "next": ok({"stores": [], "recent_trials": [], "paths": {}, "waiting": {}, "notes": []}),
        "data health": ok({"symbol": "SPY", "verdict": "pass", "checks": []}),
        "test": ok({"test_id": "t1", "trials_total": 3, "results": [run]}),
        "diagnose": ok({"audit": [{"check": "a", "status": "PASS"}], "flags": [], "labels": []}),
        "results cite": text("1.5 [r1:oos_sharpe] (basis) [quick]"),
        "results check": ok({"ok": True, "problems": [], "warnings": []}),
        "setup find": ok({"find_id": "f1", "totals": {"events": 4}, "labels": ["exploratory"]}),
        "setup study": ok({"study_id": "s1", "outcome": "rejected", "labels": ["exploratory"]}),
        "setup trade": ok({"trade_id": "tr1", "outcome": "inconclusive", "labels": []}),
        "results show": ok({"runs": [{"id": "tr1"}], "failed": []}),
    }


def config(tmp_path: Path, **more: Any) -> NightlyConfig:
    tmp_path.mkdir(parents=True, exist_ok=True)
    rule = tmp_path / "rule.toml"
    setup = tmp_path / "setup.toml"
    rule.write_text("name = 'x'\n")
    setup.write_text("[setup]\n")
    source = tmp_path / "nightly.toml"
    return NightlyConfig(assets=("SPY",), rule_spec=rule, setup_spec=setup, source=source, **more)


def run(
    tmp_path: Path, runner: FakeRunner, only: tuple[str, ...] | None = None, **more: Any
) -> dict[str, Any]:
    return run_nightly(config(tmp_path, **more), tmp_path / "home", runner, only=only)


def states(record: dict[str, Any]) -> dict[str, str]:
    return {step["id"]: step["state"] for step in record["steps"]}


def test_clean_run_passes_every_step_and_writes_a_record(tmp_path: Path) -> None:
    record = run(tmp_path, FakeRunner())
    assert record["summary_line"] == "Last night: 2 of 2 paths worked."
    assert record["full"] is False and record["blocking"] == 0
    assert record["paths_run"] == ["N1", "N2"]
    assert record["complete"] == "two of three paths (RD-Agent path off)"
    assert set(states(record).values()) == {"pass", "not-run"}
    assert states(record)["N3.stub"] == "not-run"
    folder = next((tmp_path / "home" / "nightly").iterdir())
    assert json.loads((folder / "record.json").read_text()) == record
    summary = (folder / "summary.txt").read_text()
    assert summary.startswith("Last night: 2 of 2 paths worked.")
    assert "needs the owner's key file and a spend cap" in summary


def test_exit_code_one_is_blocking_and_dependents_are_not_run(tmp_path: Path) -> None:
    runner = FakeRunner({"test": Outcome(1, "", "boom\nline two", 0.2, False)})
    record = run(tmp_path, runner)
    found = states(record)
    assert found["N1.test"] == "defect-blocking"
    assert found["N1.diagnose.SPY"] == found["N1.check.SPY"] == "not-run"
    step = next(s for s in record["steps"] if s["id"] == "N1.diagnose.SPY")
    assert step["note"] == "not run: step N1.test failed"
    assert found["N2.trade"] == "pass"  # an independent path still runs
    assert record["summary_line"] == "Last night: 1 of 2 paths worked."
    defect = record["defects"][0]
    assert defect["severity"] == "blocking" and "boom" in defect["text"]
    assert defect["reproduce"].startswith("alpha test ")


def test_timeout_is_blocking(tmp_path: Path) -> None:
    record = run(tmp_path, FakeRunner({"setup find": Outcome(None, "", "", 9.0, True)}))
    assert states(record)["N2.find"] == "defect-blocking"
    assert states(record)["N2.study"] == "not-run"
    assert "timed out" in record["defects"][0]["text"]


def test_bad_json_and_missing_field_are_blocking(tmp_path: Path) -> None:
    bad = FakeRunner({"next": Outcome(0, "not json at all", "", 0.1, False)})
    assert states(run(tmp_path / "a", bad))["N1.next"] == "defect-blocking"
    missing = FakeRunner({"setup study": ok({"study_id": "s1"})})
    record = run(tmp_path / "b", missing)
    assert states(record)["N2.study"] == "defect-blocking"
    assert "outcome" in record["defects"][0]["text"]


def test_a_not_supported_verdict_is_not_a_defect(tmp_path: Path) -> None:
    rejected = {"test_id": "t1", "trials_total": 1, "results": [_result(verdict="F")]}
    runner = FakeRunner({"test": ok(rejected), "setup study": ok(_study("rejected"))})
    record = run(tmp_path, runner)
    assert record["blocking"] == 0 and record["minor"] == 0
    study = next(s for s in record["steps"] if s["id"] == "N2.study")
    assert study["state"] == "pass" and study["verdict"] == "rejected"


def _result(verdict: str = "C", error: object = None) -> dict[str, Any]:
    return {"asset": "SPY", "run_id": "r1", "verdict": verdict, "error": error, "labels": []}


def _study(outcome: str) -> dict[str, Any]:
    return {"study_id": "s1", "outcome": outcome}


def test_asset_error_inside_a_test_is_blocking(tmp_path: Path) -> None:
    broken = {"test_id": "t1", "trials_total": 1, "results": [_result(error={"code": "X"})]}
    record = run(tmp_path, FakeRunner({"test": ok(broken)}))
    assert states(record)["N1.test"] == "defect-blocking"


def test_warnings_are_minor_and_do_not_block(tmp_path: Path) -> None:
    runner = FakeRunner({"data health": ok({"symbol": "SPY", "verdict": "warn", "checks": []})})
    record = run(tmp_path, runner)
    assert states(record)["N1.health.SPY"] == "defect-minor"
    assert record["blocking"] == 0 and record["minor"] == 1
    assert record["summary_line"] == "Last night: 2 of 2 paths worked."
    failed = FakeRunner({"data health": ok({"symbol": "SPY", "verdict": "fail", "checks": []})})
    assert states(run(tmp_path / "b", failed))["N1.health.SPY"] == "defect-blocking"


def test_saved_health_report_is_read_before_a_new_one_is_made(tmp_path: Path) -> None:
    runner = FakeRunner()
    assert states(run(tmp_path / "a", runner))["N1.health.SPY"] == "pass"
    assert ["data", "health", "SPY", "--stored", "--json"] in runner.calls
    assert ["data", "health", "SPY", "--json"] not in runner.calls
    stale = FakeRunner({"data health SPY --stored": ok({"symbol": "SPY", "status": "out of date"})})
    record = run(tmp_path / "b", stale)
    assert ["data", "health", "SPY", "--json"] in stale.calls
    assert states(record)["N1.health.SPY"] == "pass"
    missing = FakeRunner(
        {"data health SPY --stored": Outcome(2, "", "no stored report", 0.1, False)}
    )
    run(tmp_path / "c", missing)
    assert ["data", "health", "SPY", "--json"] in missing.calls


def test_results_check_disagreement_is_blocking(tmp_path: Path) -> None:
    problems = {"ok": False, "problems": [{"kind": "VALUE_MISMATCH"}], "warnings": []}
    runner = FakeRunner({"results check": Outcome(1, json.dumps(problems), "", 0.1, False)})
    record = run(tmp_path, runner)
    assert states(record)["N1.check.SPY"] == "defect-blocking"
    assert "VALUE_MISMATCH" in record["defects"][0]["text"]


def test_post_tools_run_after_the_test(tmp_path: Path) -> None:
    runner = FakeRunner({"monte-carlo": ok({"ok": True})})
    record = run(tmp_path, runner, post_tools=("monte-carlo classical --from-run {run_id} --json",))
    assert states(record)["N1.tool.1"] == "pass"
    assert ["monte-carlo", "classical", "--from-run", "r1", "--json"] in runner.calls


def test_only_runs_a_part_and_is_never_full(tmp_path: Path) -> None:
    runner = FakeRunner()
    record = run(tmp_path, runner, only=("N2",))
    assert record["full"] is False and record["paths_run"] == ["N2"]
    assert not any(call[0] == "next" for call in runner.calls)
    assert record["summary_line"] == "Last night: 1 of 1 paths worked (partial run: N2 only)."


def test_rdagent_runs_only_when_configured_and_unchanged(tmp_path: Path) -> None:
    key_free = tmp_path / "rdagent.toml"
    key_free.write_text("")
    runner = FakeRunner(
        {
            "rdagent run": text("done"),
            "rdagent status": ok({"state": "finished", "state_words": "x"}),
        }
    )
    record = run(tmp_path, runner, rdagent_config=key_free)
    assert ["rdagent", "run", "--config", str(key_free)] in runner.calls
    assert ["rdagent", "status", "--config", str(key_free), "--json"] in runner.calls
    assert states(record)["N3.status"] == "pass"
    assert record["summary_line"] == "Last night: 3 of 3 paths worked."
    assert record["full"] is True and record["complete"] == "all three paths"
    assert record["paths_run"] == ["N1", "N2", "N3"]
    stopped = FakeRunner(
        {"rdagent run": text("x"), "rdagent status": ok({"state": "stopped", "state_words": "x"})}
    )
    assert states(run(tmp_path / "b", stopped, rdagent_config=key_free))["N3.status"] == (
        "defect-blocking"
    )


def test_the_record_is_append_only_and_holds_no_values(tmp_path: Path) -> None:
    first = run(tmp_path, FakeRunner())
    folder = tmp_path / "home" / "nightly" / f"{first['date']}-1"
    before = (folder / "record.json").read_bytes()
    second = run(tmp_path, FakeRunner())
    assert second["run_number"] == 2
    assert (folder / "record.json").read_bytes() == before
    assert "1.5" not in json.dumps(second) and "oos_sharpe" not in json.dumps(second)
    assert len(read_records(tmp_path / "home")) == 2


ALL = ["N1", "N2", "N3"]


def _step(step_id: str, evidence: str) -> dict[str, Any]:
    return {"id": step_id, "scenario": step_id[:2], "state": "pass", "evidence": evidence}


def _record(
    home: Path,
    name: str,
    *,
    paths: list[str] | None = None,
    evidence: str | None = "computed",
    blocking: int = 0,
    scenarios: list[str] | None = None,
) -> None:
    """Write one record by hand. `evidence=None` writes an old record with no evidence field."""
    ran = ALL if paths is None else paths
    steps = [_step("N1.test", evidence or ""), _step("N2.find", evidence or "")]
    if evidence is None:
        steps = [{k: v for k, v in s.items() if k != "evidence"} for s in steps]
    folder = home / "nightly" / name
    folder.mkdir(parents=True)
    body: dict[str, Any] = {
        "date": name[:10],
        "run_number": int(name[11:]),
        "full": ran == ALL,
        "scenarios": ALL if scenarios is None else scenarios,
        "blocking": blocking,
        "minor": 0,
        "summary_line": "Last night: 2 of 2 paths worked.",
        "steps": steps,
        "defects": [],
    }
    if evidence is not None:
        body["paths_run"] = ran
    (folder / "record.json").write_text(json.dumps(body))


def _verdict(home: Path) -> dict[str, Any]:
    return readiness(read_records(home))


def test_two_computed_three_path_runs_on_two_dates_are_ready(tmp_path: Path) -> None:
    _record(tmp_path, "2026-11-18-1")
    _record(tmp_path, "2026-11-19-1")
    verdict = _verdict(tmp_path)
    assert verdict["ready"] is True and verdict["missing"] == []


def test_two_runs_on_one_date_are_not_ready_reason_a(tmp_path: Path) -> None:
    _record(tmp_path, "2026-11-19-1")
    _record(tmp_path, "2026-11-19-2")
    verdict = _verdict(tmp_path)
    assert verdict["ready"] is False and verdict["missing"] == ["a"]
    assert "same date" in verdict["reasons"][0]


def test_a_run_with_the_rdagent_path_off_is_not_ready_reason_c(tmp_path: Path) -> None:
    _record(tmp_path, "2026-11-18-1")
    _record(tmp_path, "2026-11-19-1", paths=["N1", "N2"])
    verdict = _verdict(tmp_path)
    assert verdict["missing"] == ["c"] and "RD-Agent path" in verdict["reasons"][0]


def test_all_reused_runs_are_reused_only_reason_d(tmp_path: Path) -> None:
    _record(tmp_path, "2026-11-18-1")
    _record(tmp_path, "2026-11-19-1", evidence="reused")
    verdict = _verdict(tmp_path)
    assert verdict["missing"] == ["d"]
    assert "reused only" in verdict["reasons"][0]
    assert "no new data that night" in verdict["reasons"][0]
    assert verdict["recent"][-1]["reused_only"] is True


def test_a_blocking_defect_is_not_ready_reason_b(tmp_path: Path) -> None:
    _record(tmp_path, "2026-11-18-1")
    _record(tmp_path, "2026-11-19-1", blocking=1)
    verdict = _verdict(tmp_path)
    assert verdict["missing"] == ["b"]


def test_an_old_record_without_evidence_is_unknown_and_does_not_qualify(tmp_path: Path) -> None:
    _record(tmp_path, "2026-11-17-1", evidence=None)
    _record(tmp_path, "2026-11-18-1", evidence=None)
    verdict = _verdict(tmp_path)
    assert verdict["ready"] is False
    assert set(verdict["missing"]) <= {"c", "d"} and verdict["missing"]
    assert verdict["recent"][0]["unknown"] == 2 and verdict["recent"][0]["computed"] == 0


def test_a_partial_run_is_ignored_and_does_not_break_the_streak(tmp_path: Path) -> None:
    _record(tmp_path, "2026-11-18-1")
    _record(tmp_path, "2026-11-19-1")
    _record(tmp_path, "2026-11-19-2", paths=["N2"], scenarios=["N2"])
    assert _verdict(tmp_path)["ready"] is True
    assert len(_verdict(tmp_path)["recent"]) == 2


def test_fewer_than_two_runs_are_not_ready(tmp_path: Path) -> None:
    assert _verdict(tmp_path)["ready"] is False
    _record(tmp_path, "2026-11-19-1")
    assert _verdict(tmp_path)["missing"] == ["a"]


def test_status_prints_runs_and_exactly_what_is_missing(tmp_path: Path) -> None:
    _record(tmp_path, "2026-11-18-1")
    _record(tmp_path, "2026-11-19-1", evidence="reused")
    text_out = status_text(status_facts(tmp_path, Path("nightly.toml")))
    assert "2026-11-19-1" in text_out and "reused only" in text_out
    assert "Ready: no." in text_out and "(d)" in text_out
    assert "pull data before it" in text_out
    _record(tmp_path, "2026-11-20-1")
    _record(tmp_path, "2026-11-21-1")
    assert "Ready: yes." in status_text(status_facts(tmp_path, Path("nightly.toml")))


def test_crontab_line_and_last_night_line(tmp_path: Path) -> None:
    assert status_facts(tmp_path, Path("nightly.toml"))["last"] is None
    _record(tmp_path, "2026-11-19-1")
    facts = status_facts(tmp_path, Path("nightly.toml"))
    assert facts["crontab_line"].startswith("17 2 * * * ")
    assert "nightly run --config" in facts["crontab_line"]
    assert last_night_line(tmp_path) == "Last night: 2 of 2 paths worked."
    assert last_night_line(tmp_path / "empty") is None


def test_crontab_uses_the_config_of_the_last_full_run(tmp_path: Path) -> None:
    cfg = config(tmp_path, rdagent_config=tmp_path / "r.toml")
    (tmp_path / "r.toml").write_text("")
    runner = FakeRunner({"rdagent run": text("done"), "rdagent status": ok({"state": "finished"})})
    run_nightly(cfg, tmp_path / "home", runner, today=date(2026, 11, 19))
    line = status_facts(tmp_path / "home", Path("other.toml"))["crontab_line"]
    assert str(cfg.source) in line and "other.toml" not in line


def _evidence(record: dict[str, Any]) -> dict[str, str]:
    return {step["id"]: step["evidence"] for step in record["steps"]}


def test_steps_say_computed_or_reused_from_what_the_commands_print(tmp_path: Path) -> None:
    fresh = _evidence(run(tmp_path / "a", FakeRunner()))
    assert fresh["N1.test"] == fresh["N2.find"] == fresh["N2.study"] == "computed"
    assert fresh["N1.next"] == "unknown"
    again = {"labels": ["quick", "repeat"]}
    repeat = _result()
    repeat["labels"] = again["labels"]
    listed = {"test_id": "t1", "trials_total": 3, "results": [repeat]}
    runner = FakeRunner(
        {
            "test": ok(listed),
            "setup find": ok({"find_id": "f1", "totals": {}, "labels": ["repeat"]}),
        }
    )
    record = run(tmp_path / "b", runner)
    assert _evidence(record)["N1.test"] == "reused"
    assert _evidence(record)["N2.find"] == "reused"
    assert (
        "N1.test: worked, reused the stored result (repeat)"
        in (tmp_path / "b" / "home" / "nightly" / f"{record['date']}-1" / "summary.txt").read_text()
    )
    silent = FakeRunner({"setup find": ok({"find_id": "f1", "totals": {}})})
    assert _evidence(run(tmp_path / "c", silent))["N2.find"] == "unknown"


def test_real_runs_on_two_dates_become_ready_and_one_date_does_not(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cfg = config(tmp_path, rdagent_config=tmp_path / "r.toml")
    (tmp_path / "r.toml").write_text("")
    runner = FakeRunner({"rdagent run": text("done"), "rdagent status": ok({"state": "finished"})})
    for day in (date(2026, 11, 19), date(2026, 11, 19)):
        run_nightly(cfg, home, runner, today=day)
    assert readiness(read_records(home))["missing"] == ["a"]
    run_nightly(cfg, home, runner, today=date(2026, 11, 20))
    assert readiness(read_records(home))["ready"] is True


def test_config_loads_relative_paths_and_rejects_unknown_keys(tmp_path: Path) -> None:
    (tmp_path / "r.toml").write_text("")
    (tmp_path / "s.toml").write_text("")
    path = tmp_path / "nightly.toml"
    path.write_text('assets = ["AAA"]\nrule_spec = "r.toml"\nsetup_spec = "s.toml"\n')
    loaded = load_config(path)
    assert loaded.rule_spec == tmp_path / "r.toml" and loaded.rdagent_config is None
    path.write_text(path.read_text() + "extra_option = 1\n")
    with pytest.raises(NightlyConfigError, match="extra_option"):
        load_config(path)
