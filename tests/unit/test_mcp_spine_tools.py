"""The spine MCP tools build exact `alpha` argv, refuse authority arguments and expose no verbs."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from alpha_mcp import server, spine_tools

RUN = "0123456789abcdef"
SPINE_NAMES = frozenset(
    {
        "rule_test",
        "tool_list",
        "tool_describe",
        "tool_run",
        "tool_run_set",
        "results_show",
        "results_cite",
        "results_check",
        "ledger_summary",
        "ledger_history",
        "diagnose_run",
        "data_health",
        "setup_find",
        "setup_study",
        "setup_trade",
    }
)
AUTHORITY = re.compile(r"approve|promote|confirm|accept_bad|owner|order|enroll")


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


def test_rule_test_argv(calls: list[list[str]]) -> None:
    spine_tools.rule_test(
        rule="breakout",
        params={"window": "20"},
        assets=["SPY", "QQQ@alpaca"],
        name="n",
        idea="i",
        fee_bps=1.0,
        slippage_bps=2.0,
        quick=True,
        diagnose=False,
        check_data=True,
    )
    assert calls == [
        ["alpha", "test", "--rule", "breakout", "--param", "window=20"]
        + ["--asset", "SPY", "--asset", "QQQ@alpaca", "--name", "n", "--idea", "i"]
        + ["--fee-bps", "1.0", "--slippage-bps", "2.0", "--quick", "--no-diagnose"]
        + ["--check-data", "--json"]
    ]


def test_rule_test_spec_text_is_written_inside_the_data_dir(
    calls: list[list[str]], tmp_path: Path
) -> None:
    spine_tools.rule_test(spec_text='[rule]\nkind="breakout"\n')
    path = Path(calls[0][2])
    assert path.parent == tmp_path / "mcp-inputs"
    assert path.read_text() == '[rule]\nkind="breakout"\n'
    assert calls[0] == ["alpha", "test", str(path), "--json"]


def test_spec_path_must_stay_inside_the_data_dir(calls: list[list[str]], tmp_path: Path) -> None:
    (tmp_path / "spec.toml").write_text("x")
    spine_tools.rule_test(spec_path=str(tmp_path / "spec.toml"))
    assert calls[0][:3] == ["alpha", "test", str((tmp_path / "spec.toml").resolve())]
    for bad in ("/etc/passwd", "../outside.toml", str(tmp_path / ".." / "x.toml")):
        with pytest.raises(ValueError, match="inside the ALPHA data directory"):
            spine_tools.rule_test(spec_path=bad)
    assert len(calls) == 1


def test_tool_argv(calls: list[list[str]]) -> None:
    spine_tools.tool_list(for_target="SPY", search="drift", family="f", kind="k")
    spine_tools.tool_describe("monte_carlo")
    spine_tools.tool_run("monte_carlo", RUN, params={"paths": "100"}, seed=7)
    spine_tools.tool_run_set("core", RUN)
    assert calls == [
        ["alpha", "tool", "list", "--for", "SPY", "--search", "drift", "--family", "f"]
        + ["--kind", "k", "--json"],
        ["alpha", "tool", "describe", "monte_carlo", "--json"],
        ["alpha", "tool", "run", "monte_carlo", RUN, "--param", "paths=100", "--seed", "7"]
        + ["--json"],
        ["alpha", "tool", "run-set", "core", RUN, "--json"],
    ]


def test_results_ledger_diagnose_health_argv(calls: list[list[str]], tmp_path: Path) -> None:
    spine_tools.results_show(RUN)
    spine_tools.results_cite(RUN, "sharpe", tool_output="out1")
    spine_tools.results_check("Sharpe 1.2 [0123abcd:sharpe]", allow_untagged=2)
    spine_tools.ledger_summary()
    spine_tools.ledger_history(kind="rule", asset="SPY", limit=5)
    spine_tools.diagnose_run(RUN)
    spine_tools.data_health("SPY@alpaca", stored=True)
    draft = calls[2][3]
    assert Path(draft).parent == tmp_path / "mcp-inputs"
    assert calls == [
        ["alpha", "results", "show", RUN, "--json"],
        ["alpha", "results", "cite", RUN, "sharpe", "--tool-output", "out1", "--json"],
        ["alpha", "results", "check", draft, "--allow-untagged", "2", "--json"],
        ["alpha", "ledger", "summary", "--json"],
        ["alpha", "ledger", "list", "--kind", "rule", "--asset", "SPY", "--limit", "5", "--json"],
        ["alpha", "diagnose", RUN, "--json"],
        ["alpha", "data", "health", "SPY@alpaca", "--stored", "--json"],
    ]


def test_setup_argv(calls: list[list[str]], tmp_path: Path) -> None:
    spine_tools.setup_find(spec_text="[setup]\n", asset="SPY", context_bars=30, max_sheets=3)
    spine_tools.setup_study("find-1", check_data=True)
    spine_tools.setup_trade("find-1")
    spec = calls[0][3]
    assert Path(spec).parent == tmp_path / "mcp-inputs"
    assert calls == [
        ["alpha", "setup", "find", spec, "--asset", "SPY", "--context-bars", "30"]
        + ["--max-sheets", "3", "--json"],
        ["alpha", "setup", "study", "find-1", "--check-data", "--json"],
        ["alpha", "setup", "trade", "find-1", "--json"],
    ]


@pytest.mark.parametrize(
    "name",
    sorted(SPINE_NAMES),
)
@pytest.mark.parametrize(
    "extra",
    ["accept_bad_data", "approve", "confirm_reserved", "owner_auth", "rdagent_reply", "options"],
)
def test_unknown_or_authority_arguments_are_refused(
    calls: list[list[str]], name: str, extra: str
) -> None:
    arguments: dict[str, Any] = {extra: "x"}
    with pytest.raises((ToolError, TypeError, ValueError)):
        anyio.run(server.mcp.call_tool, name, arguments)
    assert calls == []


def test_bad_values_are_refused_before_the_cli_runs(calls: list[list[str]]) -> None:
    with pytest.raises(ValueError):
        spine_tools.results_show("not-a-run")
    with pytest.raises(ValueError):
        spine_tools.data_health("--accept-bad-data")
    with pytest.raises(ValueError):
        spine_tools.tool_run("monte_carlo", "SPY", params={"--x": "1"})
    with pytest.raises(ValueError):
        spine_tools.rule_test(rule="breakout", spec_text="x")
    with pytest.raises(ValueError):
        spine_tools.ledger_history(limit=0)
    assert calls == []


def test_tool_list_has_the_spine_tools_and_no_authority_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALPHA_DATA_DIR", str(tmp_path))
    names = {tool.name for tool in anyio.run(server.mcp.list_tools)}
    assert names >= SPINE_NAMES
    for tool in anyio.run(server.mcp.list_tools):
        assert AUTHORITY.search(tool.name) is None, tool.name
        if tool.name in SPINE_NAMES:
            assert "research records, not approvals" in " ".join((tool.description or "").split())
            assert AUTHORITY.search(" ".join(tool.inputSchema.get("properties", {}))) is None
