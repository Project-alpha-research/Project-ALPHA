"""`alpha follow book`: every active follow as a share of one paper account. Read-only."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli import follow_cmds, follow_store
from alpha_cli.follow_source import Source
from alpha_cli.main import app
from tests.fixtures import follow_today_fixtures as fx

RUNNER = CliRunner()
D19 = date(2026, 11, 19)


def near(value: float) -> object:
    return pytest.approx(value, rel=1e-9, abs=1e-12)


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(follow_cmds, "CLOCK", lambda: fx.NOW)


def _cli(home: Path, *args: str) -> tuple[int, str]:
    result = RUNNER.invoke(app, ["follow", "book", *args], env={"ALPHA_DATA_DIR": str(home)})
    return result.exit_code, result.output


def _start(home: Path, asset: str, run_id: str, size: float) -> str:
    source = Source("rule_test", run_id, hashlib.sha256(run_id.encode()).hexdigest(), "", [asset])
    facts = follow_store.start_follow(home, source, card="", size_pct=size, clock=lambda: fx.START)
    return str(facts["follow_id"])


def _world(home: Path) -> dict[str, str]:
    """Two follows hold AAA (60% and 30%), one is flat in BBB (40%), one is stopped."""
    fx.seed(home)
    ids = {
        "a60": _start(home, "AAA", "a" * 16, 60.0),
        "a30": _start(home, "AAA", "b" * 16, 30.0),
        "b40": _start(home, "BBB", "c" * 16, 40.0),
        "stopped": _start(home, "CCC", "d" * 16, 100.0),
    }
    fx.add(home, ids["a60"], D19, action="hold", words="holding", units=6.0)
    fx.add(home, ids["a30"], D19, action="hold", words="holding", units=3.0)
    fx.add(home, ids["b40"], D19)
    follow_store.stop_follow(home, ids["stopped"], reason="test", clock=lambda: fx.NOW)
    return ids


def test_sizes_total_and_exposure_per_asset(tmp_path: Path) -> None:
    ids = _world(tmp_path)
    code, out = _cli(tmp_path, "--json")
    assert code == 0, out
    facts = json.loads(out)
    by = {f["follow_id"]: f for f in facts["follows"]}
    assert set(by) == {ids["a60"], ids["a30"], ids["b40"]}
    assert by[ids["a60"]]["size_pct"] == near(60.0) and by[ids["a60"]]["open"] is True
    assert by[ids["b40"]]["open"] is False and by[ids["b40"]]["assets"] == ["BBB"]
    assert facts["total_pct"] == near(130.0)
    assert facts["in_market_pct"] == near(90.0)
    assert facts["assets"] == [
        {"asset": "AAA", "size_pct": near(90.0), "in_market_pct": near(90.0), "follows": 2},
        {"asset": "BBB", "size_pct": near(40.0), "in_market_pct": near(0.0), "follows": 1},
    ]
    assert facts["above_account"] is True
    assert facts["sentence"] == "The follows together use 130% of the paper account."
    assert facts["paper"] is True and facts["unreadable"] == []


def test_the_text_view(tmp_path: Path) -> None:
    ids = _world(tmp_path)
    code, text = _cli(tmp_path)
    assert code == 0
    lines = text.splitlines()
    assert lines[0] == "Paper book: 3 active follow(s), each as a share of one paper account."
    assert any(ids["a60"] in line and "60% of the paper account" in line for line in lines)
    assert "Total size: 130% of the paper account. In the market now: 90%." in lines
    assert "  AAA  90% in 2 follows; 90% in the market now" in lines
    assert "  BBB  40% in 1 follow; 0% in the market now" in lines
    assert "The follows together use 130% of the paper account." in lines
    assert lines[-1] == "Paper only. Forward use; not research. Not advice."
    assert ids["stopped"] not in text


def test_no_line_when_the_total_is_within_one_account(tmp_path: Path) -> None:
    fx.seed(tmp_path)
    _start(tmp_path, "AAA", "a" * 16, 60.0)
    _start(tmp_path, "BBB", "b" * 16, 40.0)
    code, out = _cli(tmp_path, "--json")
    facts = json.loads(out)
    assert code == 0 and facts["total_pct"] == near(100.0)
    assert facts["above_account"] is False and facts["sentence"] is None
    assert "together use" not in _cli(tmp_path)[1]


def test_no_follows(tmp_path: Path) -> None:
    code, text = _cli(tmp_path)
    assert code == 0 and text.startswith("No active follows yet (paper).")
    assert json.loads(_cli(tmp_path, "--json")[1])["follows"] == []


def test_a_broken_journal_is_named_and_not_counted(tmp_path: Path) -> None:
    ids = _world(tmp_path)
    journal = follow_store.folder_of(tmp_path, ids["a30"]) / "journal.jsonl"
    journal.write_text(journal.read_text() + "not json\n")
    code, out = _cli(tmp_path, "--json")
    facts = json.loads(out)
    assert code == 0 and facts["unreadable"] == [ids["a30"]]
    assert facts["total_pct"] == near(100.0)
    assert f"Not counted: follow {ids['a30']} cannot be read" in _cli(tmp_path)[1]


def test_the_view_writes_nothing(tmp_path: Path) -> None:
    _world(tmp_path)

    def state() -> dict[str, str]:
        return {
            p.relative_to(tmp_path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in tmp_path.rglob("*")
            if p.is_file()
        }

    before = state()
    assert _cli(tmp_path)[0] == 0 and _cli(tmp_path, "--json")[0] == 0
    assert state() == before
