"""fs.py see prints a card's see_it lines and runs only single alpha commands."""

from __future__ import annotations

import subprocess
from pathlib import Path

import fs
import fs_see
import pytest

_MAIN = '("data", "alpha_cli.data_cmds", "data_app"),\n'
_CARD = """
[[capability]]
id = "data-download"
name = "Download data"
what = "Download prices."
see_it = {see_it}
entry_points = ["cli: alpha data pull"]
proof_synthetic = []
real_data = "not yet confirmed"
needs = []
state = "Demo only"
missing = "tested in-process only; no end-to-end smoke check yet"
"""
_LINES = [
    "uv run alpha data pull SPY",
    "alpha data pull QQQ --json",
    "uv run alpha data pull <id>",
    "uv run alpha data pull SPY; rm -rf x",
    "uv run alpha data pull … --json",
    "Workstation: View, Data",
]


def _root(tmp_path: Path) -> Path:
    main = tmp_path / "apps/alpha-cli/src/alpha_cli/main.py"
    main.parent.mkdir(parents=True, exist_ok=True)
    main.write_text(_MAIN, encoding="utf-8")
    card = tmp_path / "docs/roadmap/capabilities.toml"
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(_CARD.format(see_it=str(_LINES).replace("'", '"')), encoding="utf-8")
    return tmp_path


def _fake(code: int, lines: int = 3) -> fs_see.Runner:
    def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv, code, "\n".join(f"row {i}" for i in range(lines)), ""
        )

    return run


def test_only_single_alpha_commands_are_runnable() -> None:
    runnable = [line for line in _LINES if fs_see.command_of(line)]
    assert runnable == _LINES[:2]


def test_print_only_lists_every_line_and_runs_nothing(tmp_path: Path) -> None:
    def boom(argv: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("must not run")

    text, code = fs_see.see(_root(tmp_path), "data-download", run=False, runner=boom)
    assert code == 0
    assert all(line in text for line in _LINES)
    assert "manual step" not in text


def test_run_reports_commands_exit_codes_and_manual_steps(tmp_path: Path) -> None:
    text, code = fs_see.see(_root(tmp_path), "data-download", run=True, runner=_fake(0))
    assert code == 0
    assert "$ uv run alpha data pull SPY" in text
    assert "exit 0" in text
    assert text.count("manual step:") == 4


def test_run_fails_when_a_command_fails_and_keeps_the_last_40_lines(tmp_path: Path) -> None:
    text, code = fs_see.see(_root(tmp_path), "data-download", run=True, runner=_fake(3, 100))
    assert code == 1
    assert "exit 3" in text
    assert "row 99" in text
    assert "row 59" not in text


def test_unknown_id_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown capability"):
        fs_see.see(_root(tmp_path), "nope", run=False)


def test_cli_prints_the_card(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert fs.main(["--root", str(_root(tmp_path)), "see", "data-download"]) == 0
    assert "uv run alpha data pull SPY" in capsys.readouterr().out
    assert fs.main(["--root", str(_root(tmp_path)), "see", "nope"]) == 2
