"""The front-door MCP tools build exact `alpha` argv, refuse bad input and expose no authority."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from alpha_cli.catalog import classify_generic_command
from alpha_mcp import front_door_tools, server

CARD = "0123abcd"
RECORD = "52-week-high"
FRONT_DOOR_COMMANDS: dict[str, list[str]] = {
    "next_step": ["next"],
    "idea_list": ["idea", "list"],
    "idea_show": ["idea", "show", CARD],
    "idea_file": ["idea", "file", CARD],
    "idea_new": ["idea", "new"],
    "library_list": ["library", "list"],
    "library_show": ["library", "show", RECORD],
    "library_card": ["library", "card", RECORD],
    "tool_find": ["tool", "find", "drift"],
    "tool_situations": ["tool", "situations"],
    "follows_today": ["follow", "today"],
    "follows_list": ["follow", "list"],
    "follows_show": ["follow", "show", CARD],
    "follows_verify": ["follow", "verify", CARD],
    "nightly_status": ["nightly", "status"],
}
FORBIDDEN = (
    "follow start",
    "follow stop",
    "follow update",
    "nightly run",
    "rdagent run",
    "data pull",
    "library import-catalogue",
)
BAD_TEXT = ["--config", "-x", "a\nb", "a\rb", "a\x00b", "", "  ", "x" * 301]


@pytest.fixture
def calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Replace the subprocess with a recorder that answers `{}` and keeps every argv."""
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_: Any) -> Any:
        seen.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


def test_every_tool_builds_the_expected_argv(calls: list[list[str]]) -> None:
    front_door_tools.next_step()
    front_door_tools.idea_list()
    front_door_tools.idea_show(CARD)
    front_door_tools.idea_file(CARD)
    front_door_tools.idea_new(claim="Buy dips", baseline="buy and hold", supersedes="beef1234")
    front_door_tools.library_list()
    front_door_tools.library_list(market="crypto", tier="all")
    front_door_tools.library_show(RECORD)
    front_door_tools.library_card(RECORD)
    front_door_tools.tool_find("drift")
    front_door_tools.tool_situations()
    front_door_tools.follows_today()
    front_door_tools.follows_list()
    front_door_tools.follows_show(CARD)
    front_door_tools.follows_verify(CARD)
    front_door_tools.follows_verify(CARD, entry=3)
    front_door_tools.nightly_status()
    assert calls == [
        ["alpha", "next", "--json"],
        ["alpha", "idea", "list", "--json"],
        ["alpha", "idea", "show", CARD, "--json"],
        ["alpha", "idea", "file", CARD, "--json"],
        ["alpha", "idea", "new", "--claim", "Buy dips", "--baseline", "buy and hold"]
        + ["--supersedes", "beef1234", "--json"],
        ["alpha", "library", "list", "--json"],
        ["alpha", "library", "list", "--market", "crypto", "--tier", "all", "--json"],
        ["alpha", "library", "show", RECORD, "--json"],
        ["alpha", "library", "card", RECORD, "--json"],
        ["alpha", "tool", "find", "drift", "--json"],
        ["alpha", "tool", "situations", "--json"],
        ["alpha", "follow", "today", "--json"],
        ["alpha", "follow", "list", "--json"],
        ["alpha", "follow", "show", CARD, "--json"],
        ["alpha", "follow", "verify", CARD, "--json"],
        ["alpha", "follow", "verify", CARD, "--entry", "3", "--json"],
        ["alpha", "nightly", "status", "--json"],
    ]


def test_free_text_is_one_argv_element(calls: list[list[str]]) -> None:
    front_door_tools.tool_find("my rule fails after costs; why?")
    front_door_tools.idea_new(claim="Gap fills $(date) within a day")
    assert calls[0] == ["alpha", "tool", "find", "my rule fails after costs; why?", "--json"]
    assert calls[1] == [
        "alpha",
        "idea",
        "new",
        "--claim",
        "Gap fills $(date) within a day",
        "--json",
    ]


@pytest.mark.parametrize("bad", BAD_TEXT)
def test_free_text_refusals(calls: list[list[str]], bad: str) -> None:
    with pytest.raises(ValueError):
        front_door_tools.tool_find(bad)
    for field in ("claim", "mechanism", "other_side", "disproved_by", "baseline", "signal_forms"):
        with pytest.raises(ValueError):
            front_door_tools.idea_new(**{field: bad})
    assert calls == []


@pytest.mark.parametrize(
    "bad",
    [
        "--config",
        "-x",
        ";rm",
        "$(id)",
        "ab\n",
        "abc",
        "g" * 8,
        "a" * 17,
        "",
        "0123abcd;ls",
        "-1234",
    ],
)
def test_ids_are_refused_before_a_command_is_built(calls: list[list[str]], bad: str) -> None:
    for call in (
        front_door_tools.idea_show,
        front_door_tools.idea_file,
        front_door_tools.follows_show,
        front_door_tools.follows_verify,
    ):
        with pytest.raises(ValueError):
            call(bad)
    with pytest.raises(ValueError):
        front_door_tools.idea_new(supersedes=bad)
    assert calls == []


@pytest.mark.parametrize(
    "bad",
    ["--config", "-x", ";rm", "$(id)", "a\n", "UPPER", "a--", "-a", "a" * 65, "", "a b", "a/b"],
)
def test_library_ids_are_refused(calls: list[list[str]], bad: str) -> None:
    with pytest.raises(ValueError):
        front_door_tools.library_show(bad)
    with pytest.raises(ValueError):
        front_door_tools.library_card(bad)
    assert calls == []


def test_typed_options_are_closed(calls: list[list[str]]) -> None:
    for market, tier in (
        ("--config", "all"),
        ("moon", "all"),
        ("crypto", "everything"),
        ("-x", "-y"),
    ):
        with pytest.raises(ValueError):
            library_list: Any = front_door_tools.library_list
            library_list(market=market, tier=tier)
    for entry in (-1, 1_000_001, True):
        with pytest.raises(ValueError):
            front_door_tools.follows_verify(CARD, entry=entry)
    assert calls == []


def test_the_command_error_json_is_returned_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    error = {"error": {"code": "IDEA_CARD_UNKNOWN", "message": "m", "next": "n", "known": None}}

    def fake_run(argv: list[str], **_: Any) -> Any:
        return subprocess.CompletedProcess(argv, 1, stdout=json.dumps(error), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert front_door_tools.idea_show(CARD) == error


def test_a_failure_without_error_json_is_a_plain_error_not_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))

    def fake_run(argv: list[str], **_: Any) -> Any:
        return subprocess.CompletedProcess(argv, 2, stdout="", stderr="Traceback boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="failed"):
        front_door_tools.next_step()


def test_a_timeout_is_set_on_every_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    seen: list[float | None] = []

    def fake_run(argv: list[str], **kwargs: Any) -> Any:
        seen.append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    front_door_tools.next_step()
    front_door_tools.follows_today()
    front_door_tools.library_card(RECORD)
    assert all(isinstance(value, float) and 0 < value <= 120 for value in seen)


# `alpha tool` is classed `empirical` as a root (because `tool run` is); `tool find` and `tool
# situations` are its read-only subcommands, like the existing `tool_list` and `tool_describe`.
_READ_ONLY_UNDER_EMPIRICAL_ROOT = frozenset({"tool_find", "tool_situations"})
# `data_pull` is an older tool in server.py (pinned in test_research_mcp.py); this change adds none.
_OLDER_FORBIDDEN_TOOLS = frozenset({"data_pull"})


def test_every_tool_maps_to_a_command_the_catalog_calls_safe() -> None:
    assert {tool.__name__ for tool in front_door_tools.FRONT_DOOR_TOOLS} == set(FRONT_DOOR_COMMANDS)
    for name, argv in FRONT_DOOR_COMMANDS.items():
        expected = "empirical" if name in _READ_ONLY_UNDER_EMPIRICAL_ROOT else "safe"
        assert classify_generic_command(argv) == expected, name


@pytest.mark.parametrize("command", FORBIDDEN)
def test_no_tool_exists_for_a_forbidden_command(command: str) -> None:
    names = {tool.name for tool in anyio.run(server.mcp.list_tools)} - _OLDER_FORBIDDEN_TOOLS
    front_door = {tool.__name__ for tool in front_door_tools.FRONT_DOOR_TOOLS}
    words = command.split()
    joined = "_".join(words).replace("-", "_")
    assert joined not in names
    assert not {
        n
        for n in front_door
        if n.startswith(words[0] + "_")
        and n.split("_", 1)[1] in {"start", "stop", "update", "run", "pull", "import_catalogue"}
    }
    if words[0] in {"follow", "nightly", "rdagent"}:
        assert classify_generic_command(words) == "owner_only"


def test_tools_are_registered_refuse_unknown_arguments_and_say_what_they_are(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    listed = {tool.name: tool for tool in anyio.run(server.mcp.list_tools)}
    assert set(FRONT_DOOR_COMMANDS) <= set(listed)
    for name in FRONT_DOOR_COMMANDS:
        text = " ".join((listed[name].description or "").split())
        assert 0 < len(text) <= 400
        assert "profit" not in text.lower()
        assert "not advice" in text or "research record" in text
        for extra in ("config", "options", "approve", "flags"):
            with pytest.raises((ToolError, TypeError, ValueError)):
                anyio.run(server.mcp.call_tool, name, {extra: "x"})
    assert calls == []
    assert "next_step" in (server.mcp.instructions or "")


def test_the_module_does_not_read_the_follow_store() -> None:
    source = Path(front_door_tools.__file__).read_text()
    assert "forward" not in source
    assert "follow_store" not in source
