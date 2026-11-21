"""Who can reach the reserved-period confirmation: the owner's CLI and Touch ID route only.

MCP, the generic web launcher, the nightly run, RD-Agent, the follow and the toolbox cannot.
The command words are checked too: the owner must see what is spent before saying yes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import anyio
import pytest
from typer.testing import CliRunner

from alpha_cli import confirm_cmds, next_cmds, owner_auth
from alpha_cli.catalog import classify_generic_command
from alpha_cli.spine.run import run_idea
from alpha_cli.spine.spec import load_spec
from alpha_data.store import ParquetStore
from alpha_mcp import server
from alpha_web.api import owner_auth as owner_api_module
from tests.fixtures.cli_fixtures import seed_store
from tests.fixtures.reserved_owner import enroll, install_double

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
    for sub in ("plan", "request", "run", "list", "show"):
        assert classify_generic_command(["confirm", sub, "x"]) == "owner_only"


def test_only_the_touch_id_route_runs_it_and_with_the_verified_yes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web = {
        rel: text
        for rel, text in _python_files("apps/alpha-web/src").items()
        if '"confirm"' in text or "RESERVED_ACTION" in text
    }
    assert list(web) == ["apps/alpha-web/src/alpha_web/api/owner_auth.py"]
    authorization = {
        "authorization_id": "verified-yes",
        "binding": {"action_type": owner_auth.RESERVED_ACTION},
    }
    monkeypatch.setattr(owner_api_module, "verify_action_assertion", lambda **_: authorization)
    sent: list[list[str]] = []

    def run_json(argv: list[str], **_: Any) -> dict[str, str]:
        sent.append(argv)
        return {"slot": "1"}

    monkeypatch.setattr(owner_api_module, "_run_json", run_json)
    body = owner_api_module.OwnerActionPerformRequest(
        challenge_id="c", credential={"id": "x"}, payload={"run_id": "r1", "reserved_end": "e"}
    )
    assert owner_api_module.perform_action(body)["result"] == {"slot": "1"}
    assert sent == [["confirm", "run", "r1", "--authorization", "verified-yes", "--json"]]


def test_no_automatic_part_reaches_it() -> None:
    files = _python_files("apps", "packages", "workers")
    callers = {
        "take_slot(": {"apps/alpha-cli/src/alpha_cli/spine/confirm_run.py"},
        "record_authorization(": {"apps/alpha-cli/src/alpha_cli/owner_auth.py"},
        "confirm_run import": {"apps/alpha-cli/src/alpha_cli/confirm_cmds.py"},
    }
    for word, allowed in callers.items():
        found = {rel for rel, text in files.items() if word in text}
        found.discard("apps/alpha-cli/src/alpha_cli/reserved_slots.py")
        assert found == allowed, (word, found)
    for rel, text in files.items():
        if any(part in rel for part in ("nightly", "rdagent", "follow", "toolbox", "workers/")):
            assert "confirm_cmds" not in text and "reserved_slots" not in text, rel


def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    install_double(monkeypatch)
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seed_store(tmp_path, symbol="SPY", n=1600)
    ParquetStore(tmp_path / "store").write_provenance(
        "SPY", source="alpaca", adapter_version="1", parser_version="1"
    )
    spec = load_spec(None, rule="ma_cross", param=["fast=5", "slow=20"], asset=["SPY"])
    out = run_idea(spec, home=tmp_path, quick=True, no_diagnose=True)["results"][0]
    return tmp_path, str(out["run_id"])


def test_the_owner_reads_what_is_spent_before_saying_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, run_id = _home(tmp_path, monkeypatch)
    runner = CliRunner()
    shown = runner.invoke(confirm_cmds.confirm_app, ["plan", run_id])
    assert shown.exit_code == 0, shown.output
    for words in (
        "The reserved period is the data from 2024-01-01 on",
        "It is frozen: nothing can change.",
        "Slots: 0 of 10 used, 10 left.",
        "This uses 1 of the 10 slots",
        "It cannot be undone.",
        "can never be confirmed again",
        "whatever it is",
        "Nothing was written.",
    ):
        assert words in shown.output, words
    assert not (home / "control").exists()
    refused = runner.invoke(confirm_cmds.confirm_app, ["request", run_id, "--reason", "why"])
    assert refused.exit_code == 1 and "not enrolled" in refused.output
    enroll(home)
    asked = runner.invoke(
        confirm_cmds.confirm_app, ["request", run_id, "--reason", "why", "--json"]
    )
    assert asked.exit_code == 0, asked.output
    url = urlparse(json.loads(asked.output)["url"])
    assert (url.scheme, url.netloc) == ("http", "localhost:8801")
    assert url.path.endswith("/confirm") and url.path.startswith("/owner")
    fragment = parse_qs(url.fragment)
    assert set(fragment) == {"challenge", "options", "payload", "summary"}
    listed = runner.invoke(confirm_cmds.confirm_app, ["list"])
    assert "0 of 10 used" in listed.output
    assert "Reserved period" not in next_cmds._text(next_cmds.collect(home))
    ran = runner.invoke(confirm_cmds.confirm_app, ["run", run_id])
    assert ran.exit_code == 1 and "Touch ID yes" in ran.output
