"""`alpha follow`: the frozen record, versions, and what start must not touch."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli import follow_cmds
from alpha_cli.main import app
from alpha_data.store import ParquetStore
from tests.fixtures.cli_fixtures import seed_store

RUNNER = CliRunner()
T0 = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)
CARD = "c" * 12
RUN_A = "a" * 16
RUN_B = "b" * 16
FIND = "f" * 16


class Now:
    def __init__(self) -> None:
        self.at = T0

    def __call__(self) -> datetime:
        self.at += timedelta(minutes=1)
        return self.at


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Now:
    now = Now()
    monkeypatch.setattr(follow_cmds, "CLOCK", now)
    return now


def _home(tmp_path: Path) -> Path:
    seed_store(tmp_path, symbol="SPY", n=60)
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    (tmp_path / "ideas").mkdir()
    (tmp_path / "ideas" / f"{CARD}.toml").write_text('claim = "x"\n')
    return tmp_path


def _rule_test(home: Path, run_id: str, spec: str, card: str = CARD) -> None:
    folder = home / "runs" / run_id
    folder.mkdir(parents=True)
    spine = {"spec_sha256": spec, "store": "home", "idea_card": card}
    manifest = {"run_id": run_id, "metadata": {"symbol": "SPY"}, "spine": spine}
    (folder / "manifest.json").write_text(json.dumps(manifest))


def _find(home: Path) -> None:
    folder = home / "setups" / FIND
    folder.mkdir(parents=True)
    manifest = {
        "find_id": FIND,
        "spec_sha256": "9" * 64,
        "assets": [{"asset": "SPY", "error": None}],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))


def _cli(home: Path, *args: str) -> tuple[int, str]:
    result = RUNNER.invoke(app, ["follow", *args], env={"ALPHA_DATA_DIR": str(home)})
    return result.exit_code, result.output


def _start(home: Path, *args: str) -> dict[str, object]:
    code, output = _cli(home, "start", *args, "--json")
    assert code == 0, output
    return dict(json.loads(output))


def _files(home: Path) -> dict[str, str]:
    return {
        str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(home.rglob("*"))
        if p.is_file()
    }


def test_start_writes_only_under_forward_and_no_ledger_row(tmp_path: Path, clock: Now) -> None:
    home = _home(tmp_path)
    _rule_test(home, RUN_A, "1" * 64)
    ledger = home / "ledger" / "trials.jsonl"
    ledger.parent.mkdir()
    ledger.write_text('{"kind": "rule_test"}\n')
    before = _files(home)
    started = _start(home, "--test", RUN_A)
    after = _files(home)
    new = set(after) - set(before)
    assert new and all(name.startswith(f"forward/{started['follow_id']}/") for name in new)
    assert {n for n in before if before[n] != after.get(n)} == set()
    assert ledger.read_text() == '{"kind": "rule_test"}\n'


def test_the_record_is_frozen_with_the_source_and_paper_size(tmp_path: Path, clock: Now) -> None:
    home = _home(tmp_path)
    _rule_test(home, RUN_A, "1" * 64)
    started = _start(home, "--test", RUN_A, "--size-pct", "5")
    code, output = _cli(home, "show", str(started["follow_id"]), "--json")
    facts = json.loads(output)
    record = facts["record"]
    assert code == 0 and record["kind"] == "rule_test" and record["source_id"] == RUN_A
    assert record["spec_sha256"] == "1" * 64 and record["card_id"] == CARD
    assert record["assets"] == ["SPY"] and record["paper_account_percent"] == 5.0
    assert (record["version"], record["supersedes"]) == (1, "")
    assert record["started_at"].startswith("2026-11-19T08:01")
    assert facts["entries"] == {"start": 1} and facts["waiting_for_first_bar"] is True
    assert len(facts["head"]) == 64 and len(record["follow_id"]) == 12


def test_a_setup_find_can_be_followed(tmp_path: Path, clock: Now) -> None:
    home = _home(tmp_path)
    _find(home)
    started = _start(home, "--find", FIND)
    assert started["kind"] == "setup_find"


def test_a_factor_is_refused_as_not_built_yet(tmp_path: Path, clock: Now) -> None:
    code, output = _cli(_home(tmp_path), "start", "--factor", "x", "--json")
    assert code == 1 and "not built yet" in output
    assert not (tmp_path / "forward").exists()


def test_start_needs_exactly_one_source(tmp_path: Path, clock: Now) -> None:
    home = _home(tmp_path)
    assert _cli(home, "start")[0] == 1
    assert _cli(home, "start", "--test", RUN_A, "--find", FIND)[0] == 1


def test_a_changed_spec_of_the_same_idea_is_a_new_version(tmp_path: Path, clock: Now) -> None:
    home = _home(tmp_path)
    _rule_test(home, RUN_A, "1" * 64)
    _rule_test(home, RUN_B, "2" * 64)
    old = _start(home, "--test", RUN_A)
    new = _start(home, "--test", RUN_B)
    assert new["follow_id"] != old["follow_id"] and new["version"] == 2
    assert new["supersedes"] == old["follow_id"] and new["replaced"] == old["follow_id"]
    code, text = _cli(home, "start", "--test", RUN_A)
    assert code == 0, text
    old_show = json.loads(_cli(home, "show", str(old["follow_id"]), "--json")[1])
    assert old_show["entries"] == {"start": 1, "stop": 1} and old_show["state"] == "stopped"
    assert (home / "forward" / str(old["follow_id"]) / "follow.toml").is_file()
    new_show = json.loads(_cli(home, "show", str(new["follow_id"]), "--json")[1])
    assert new_show["record"]["supersedes"] == old["follow_id"]
    assert _cli(home, "verify", str(old["follow_id"]))[0] == 0


def test_the_same_spec_again_is_not_a_new_follow(tmp_path: Path, clock: Now) -> None:
    home = _home(tmp_path)
    _rule_test(home, RUN_A, "1" * 64)
    first = _start(home, "--test", RUN_A)
    again = _start(home, "--test", RUN_A)
    assert again["follow_id"] == first["follow_id"] and again["created"] is False
    assert len(list((home / "forward").iterdir())) == 1


def test_the_forward_clock_restart_is_said_in_words(tmp_path: Path, clock: Now) -> None:
    home = _home(tmp_path)
    _rule_test(home, RUN_A, "1" * 64)
    _rule_test(home, RUN_B, "2" * 64)
    _start(home, "--test", RUN_A)
    code, output = _cli(home, "start", "--test", RUN_B)
    assert code == 0 and "forward clock restarts" in output and "paper" in output.lower()


def test_list_and_show_text_say_paper_and_waiting(tmp_path: Path, clock: Now) -> None:
    home = _home(tmp_path)
    assert "paper" in _cli(home, "list")[1].lower()
    _rule_test(home, RUN_A, "1" * 64)
    follow_id = str(_start(home, "--test", RUN_A)["follow_id"])
    _, listing = _cli(home, "list")
    assert follow_id in listing and "waiting for its first new bar" in listing
    _, shown = _cli(home, "show", follow_id)
    assert "waiting for its first new bar" in shown and "paper" in shown.lower()
    assert "profit" not in (listing + shown).lower()
    assert json.loads(_cli(home, "list", "--json")[1])["follows"][0]["follow_id"] == follow_id


def test_stop_writes_a_stop_entry_and_blocks_more(tmp_path: Path, clock: Now) -> None:
    home = _home(tmp_path)
    _rule_test(home, RUN_A, "1" * 64)
    follow_id = str(_start(home, "--test", RUN_A)["follow_id"])
    assert _cli(home, "stop", follow_id, "--reason", "done")[0] == 0
    assert _cli(home, "stop", follow_id)[0] == 1
    assert "stopped" in _cli(home, "list")[1]


def test_verify_exits_1_and_names_the_first_break(tmp_path: Path, clock: Now) -> None:
    home = _home(tmp_path)
    _rule_test(home, RUN_A, "1" * 64)
    follow_id = str(_start(home, "--test", RUN_A)["follow_id"])
    assert _cli(home, "verify", follow_id)[0] == 0
    journal = home / "forward" / follow_id / "journal.jsonl"
    journal.write_text(journal.read_text().replace("paper", "PAPER"))
    code, output = _cli(home, "verify", follow_id)
    assert code == 1 and "entry 1" in output


def test_an_unknown_follow_or_run_is_refused_in_plain_words(tmp_path: Path, clock: Now) -> None:
    home = _home(tmp_path)
    assert "no follow" in _cli(home, "show", "abcd")[1].lower()
    code, output = _cli(home, "start", "--test", RUN_A)
    assert code == 1 and "no rule test" in output.lower()
