"""Who can reach the reserved-period confirmation: an interactive `alpha confirm run` only.

MCP, the web app, the generic web launcher, the nightly run, RD-Agent, the follow and the toolbox
cannot. The command words are checked too: `plan` and `run` say what is spent, that it cannot be
undone and how many slots are left, and `run` prints the plan before it spends anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
import pytest
from typer.testing import CliRunner

from alpha_cli import confirm_cmds, next_cmds
from alpha_cli.catalog import classify_generic_command
from alpha_cli.spine import confirm_run as confirm_run_module
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import load_spec
from alpha_data.store import ParquetStore
from alpha_mcp import server
from tests.fixtures.cli_fixtures import seed_store

ROOT = Path(__file__).resolve().parents[2]


def _python_files(*tops: str) -> dict[str, str]:
    found = {}
    for top in tops:
        for path in (ROOT / top).rglob("*.py"):
            rel = path.relative_to(ROOT)
            if not any(p.startswith(".") or p in {"node_modules", "tests"} for p in rel.parts):
                found[rel.as_posix()] = path.read_text(encoding="utf-8")
    return found


def test_mcp_exposes_no_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    names = {tool.name for tool in anyio.run(server.mcp.list_tools)}
    assert not [n for n in names if "confirm" in n or "reserv" in n]
    for rel, text in _python_files("apps/alpha-mcp").items():
        for word in ('"confirm"', "reserved_slots", "confirm_run", "open_with_receipt"):
            assert word not in text, (rel, word)


def test_the_generic_web_launcher_refuses_every_confirm_command() -> None:
    for sub in ("plan", "run", "list", "show"):
        assert classify_generic_command(["confirm", sub, "x"]) == "owner_only"


def test_no_web_route_and_no_automatic_part_reaches_it() -> None:
    for rel, text in _python_files("apps/alpha-web/src").items():
        for word in ('["confirm"', "reserved_slots", "confirm_run", "/owner-auth/confirm"):
            assert word not in text, (rel, word)
    files = _python_files("apps", "packages", "workers")
    callers = {
        "take_slot(": {"apps/alpha-cli/src/alpha_cli/spine/confirm_run.py"},
        "confirm_run import": {"apps/alpha-cli/src/alpha_cli/confirm_cmds.py"},
        "import confirm_run": {"apps/alpha-cli/src/alpha_cli/confirm_cmds.py"},
    }
    for word, allowed in callers.items():
        found = {rel for rel, text in files.items() if word in text}
        found.discard("apps/alpha-cli/src/alpha_cli/reserved_slots.py")
        assert found == allowed, (word, found)
    for rel, text in files.items():
        if any(part in rel for part in ("nightly", "rdagent", "follow", "toolbox", "workers/")):
            assert "confirm_cmds" not in text and "reserved_slots" not in text, rel


def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=1600)
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    spec = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    out = run_idea(spec, home=tmp_path, quick=True, no_diagnose=True)["results"][0]
    return tmp_path, str(out["run_id"])


SPENT_WORDS = (
    "The reserved period is the data from 2024-01-01 on",
    "It is frozen: nothing can change.",
    "Slots: 0 of 10 used, 10 left.",
    "This uses 1 of the 10 slots",
    "It cannot be undone.",
    "can never be confirmed again",
    "whatever it is",
)


def test_plan_says_what_is_spent_and_run_prints_the_plan_before_it_spends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, run_id = _home(tmp_path, monkeypatch)
    runner = CliRunner()
    shown = runner.invoke(confirm_cmds.confirm_app, ["plan", run_id])
    assert shown.exit_code == 0, shown.output
    for words in (*SPENT_WORDS, "Nothing was written.", f"alpha confirm run {run_id}"):
        assert words in shown.output, words
    assert "request" not in shown.output and "Touch ID" not in shown.output
    assert not (home / "control").exists()
    listed = runner.invoke(confirm_cmds.confirm_app, ["list"])
    assert "0 of 10 used" in listed.output
    assert "Reserved period" not in next_cmds._text(next_cmds.collect(home))
    order: list[str] = []

    def fake_run(found_home: Path, found_run: str, **_: Any) -> dict[str, Any]:
        order.append("run")
        assert (found_home, found_run) == (home, run_id)
        raise confirm_run_module.SpineError("RECHECK_MISMATCH", "No slot was used.", "x")

    monkeypatch.setattr(confirm_run_module, "confirm_run", fake_run)
    ran = runner.invoke(confirm_cmds.confirm_app, ["run", run_id])
    assert ran.exit_code == 1 and order == ["run"]
    for words in (*SPENT_WORDS, "Spending 1 slot now. After this, 9 slots are left."):
        assert words in ran.output, words
    assert ran.output.index("It cannot be undone.") < ran.output.index("No slot was used.")
    names = {command.name for command in confirm_cmds.confirm_app.registered_commands}
    assert names == {"plan", "run", "list", "show"}
