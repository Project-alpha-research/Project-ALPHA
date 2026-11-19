"""`alpha rdagent run` and `status`: the same launcher argument list, no secret shown, read-only."""

from __future__ import annotations

import json
import os
import stat
import sys
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli.rdagent_cmds import rdagent_app
from alpha_cli.rdagent_run_config import (
    RdagentConfigError,
    child_command,
    launcher_argv,
    load_config,
    next_run,
)

SENTINEL = "sentinel-key-value-91c7"
RUNNER = CliRunner()
FAKE_LAUNCHER = """
import os, sys
from pathlib import Path
argv = sys.argv[1:]
run = Path(argv[argv.index("--run-dir") + 1])
run.mkdir()
(run / "saw-key.txt").write_text(str(len(os.environ.get("SENTINEL_KEY", ""))))
print("fake launcher ran")
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""


class Layout:
    """A synthetic working directory, data store and key file; nothing here is real."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.work = root / "work"
        self.data = root / "data"
        self.runs = root / "runs"
        self.universe = root / "universe.json"
        self.source = root / "rdagent-source"
        self.python = root / "factor-python"
        self.key = root / "keys.env"
        self.ledger = self.runs / "ledger" / "trials.jsonl"
        self.gateway = self.runs / "gateway-state"
        launcher = self.work / "workers" / "rdagent"
        launcher.mkdir(parents=True)
        (self.work / ".venv" / "bin").mkdir(parents=True)
        (self.work / ".venv" / "bin" / "python").symlink_to(sys.executable)
        (launcher / "factor_loop_launch.py").write_text(FAKE_LAUNCHER)
        (launcher / "model_gateway.py").write_text("    run_max_usd: float = 7.5\n")
        for folder in (self.data, self.ledger.parent, self.source):
            folder.mkdir(parents=True)
        for file in (self.universe, self.python):
            file.write_text("{}")
        self.key.write_text(f"export SENTINEL_KEY={SENTINEL}\n")
        self.key.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def text(self, extra: str = "") -> str:
        return (
            f'working_directory = "{self.work}"\n'
            f'data_dir = "{self.data}"\n'
            f'gateway_state = "{self.gateway}"\n'
            f'trial_ledger = "{self.ledger}"\n'
            f'rdagent_source = "{self.source}"\n'
            f'factor_python = "{self.python}"\n' + extra
        )

    def config(self, extra: str = "") -> Path:
        path = self.root / "rdagent.toml"
        path.write_text(self.text(extra))
        return path


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    return Layout(tmp_path)


def documented(layout: Layout, run_dir: Path, run_id: str, *tail: str) -> list[str]:
    """The README launch line, written out by hand, element by element."""
    return [
        ".venv/bin/python",
        "workers/rdagent/factor_loop_launch.py",
        "run",
        "--data-dir",
        str(layout.data),
        "--run-dir",
        str(run_dir),
        "--gateway-data-dir",
        str(layout.gateway),
        "--trial-ledger",
        str(layout.ledger),
        "--run-id",
        run_id,
        "--loop-n",
        "2",
        *tail,
    ]


def test_argv_equals_the_documented_launch_line(layout: Layout) -> None:
    config = load_config(layout.config())
    run_dir = layout.data / "runs" / "rdagent" / "20261119-01"
    assert launcher_argv(config, run_dir, "20261119-01") == documented(
        layout, run_dir, "20261119-01"
    )


def test_argv_with_the_optional_universe_equals_the_documented_line(layout: Layout) -> None:
    config = load_config(layout.config(f'universe = "{layout.universe}"\n'))
    run_dir = layout.data / "runs" / "rdagent" / "r2"
    assert launcher_argv(config, run_dir, "r2") == documented(
        layout, run_dir, "r2", "--universe", str(layout.universe)
    )


def test_discuss_and_limits_add_only_the_launchers_own_flags(layout: Layout) -> None:
    extra = "discuss = true\ndiscuss_wait_minutes = 10\non_timeout = 'stop'\nwall_seconds = 900\n"
    config = load_config(layout.config(extra + "loop_n = 3\nchat_route = 'fake'\n"))
    argv = launcher_argv(config, layout.data / "runs" / "rdagent" / "r", "r")
    assert argv[argv.index("--loop-n") + 1] == "3"
    assert argv[-9:] == [
        "--discuss",
        "--discuss-wait-minutes",
        "10",
        "--discuss-on-timeout",
        "stop",
        "--wall-seconds",
        "900",
        "--chat-route",
        "fake",
    ]


def test_unknown_key_is_an_error_naming_the_key(layout: Layout) -> None:
    with pytest.raises(RdagentConfigError) as caught:
        load_config(layout.config("loop_count = 2\n"))
    assert "loop_count" in str(caught.value)


def test_missing_paths_are_named_in_plain_words(layout: Layout) -> None:
    layout.universe.unlink()
    with pytest.raises(RdagentConfigError) as caught:
        load_config(layout.config(f'universe = "{layout.universe}"\n'))
    message = str(caught.value)
    assert "universe" in message and "does not exist" in message


def test_next_run_counts_the_runs_already_there(layout: Layout) -> None:
    config = load_config(layout.config())
    root = layout.data / "runs" / "rdagent"
    (root / "20261119-01").mkdir(parents=True)
    run_id, run_dir = next_run(config, date(2026, 11, 19))
    assert (run_id, run_dir) == ("20261119-02", root / "20261119-02")


def test_the_key_file_path_never_enters_the_command_string(layout: Layout) -> None:
    command = child_command(["python", "launcher", "run"], layout.key)
    assert command[:2] == ["bash", "-c"]
    assert str(layout.key) not in command[2]
    assert '"$ALPHA_RDAGENT_KEYFILE"' in command[2]
    assert command[-3:] == ["python", "launcher", "run"]


def test_dry_run_prints_plain_words_then_argv_and_starts_nothing(layout: Layout) -> None:
    config = layout.config(f'key_file = "{layout.key}"\n')
    result = RUNNER.invoke(rdagent_app, ["run", "--config", str(config), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Nothing was started." in result.output
    assert "loops: 2" in result.output
    assert "$7.50" in result.output
    assert "workers/rdagent/factor_loop_launch.py run --data-dir" in result.output
    assert not (layout.data / "runs").exists()
    assert SENTINEL not in result.output


def test_run_passes_the_key_to_the_child_but_never_shows_it(
    layout: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SENTINEL_KEY", raising=False)
    config = layout.config(f'key_file = "{layout.key}"\n')
    result = RUNNER.invoke(rdagent_app, ["run", "--config", str(config)])
    assert result.exit_code == 0, result.output
    assert "alpha ledger proposal --run-dir" in result.output
    assert "alpha rdagent status" in result.output
    runs = sorted((layout.data / "runs" / "rdagent").iterdir())
    assert len(runs) == 1
    assert (runs[0] / "saw-key.txt").read_text() == str(len(SENTINEL))
    assert SENTINEL not in result.output
    for file in (f for f in runs[0].rglob("*") if f.is_file()):
        assert SENTINEL not in file.read_text()
    assert not layout.ledger.exists()


def test_run_returns_the_launchers_exit_code(
    layout: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_EXIT", "2")
    result = RUNNER.invoke(rdagent_app, ["run", "--config", str(layout.config())])
    assert result.exit_code == 2


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def make_run(root: Path, **files: object) -> Path:
    run = root / "run-1"
    write(run / "launch-command.json", {"argv": ["run", "--loop-n", "3"]})
    for name, value in files.items():
        write(run / name.replace("__", "/").replace("_json", ".json"), value)
    return run


def status_of(run: Path, *extra: str) -> dict[str, object]:
    result = RUNNER.invoke(rdagent_app, ["status", "--run-dir", str(run), "--json", *extra])
    assert result.exit_code == 0, result.output
    value: dict[str, object] = json.loads(result.output)
    return value


KEYS = {
    "calls_cap",
    "calls_used",
    "next_command",
    "reason",
    "round",
    "rounds_total",
    "run_dir",
    "state",
    "state_words",
    "usd_spent",
}


def test_status_running_has_stable_keys(tmp_path: Path) -> None:
    run = make_run(tmp_path, discussion__status_json={"state": "evaluating", "round": 1})
    value = status_of(run)
    assert set(value) == KEYS
    assert (value["state"], value["round"], value["rounds_total"]) == ("running", 2, 3)
    assert "alpha rdagent status" in str(value["next_command"])


def test_status_waiting_for_your_answer(tmp_path: Path) -> None:
    run = make_run(
        tmp_path,
        discussion__status_json={"state": "waiting", "round": 0, "rounds_total": 2},
    )
    write(run / "discussion" / "round-0" / "proposal.json", {"ideas": []})
    value = status_of(run)
    assert value["state"] == "waiting"
    assert "alpha ledger proposal --run-dir" in str(value["next_command"])
    assert value["usd_spent"] is None


def test_status_finished_and_stopped_from_the_receipt(tmp_path: Path) -> None:
    this_run = {"counted_calls": 12, "usd": 0.4}
    done = make_run(
        tmp_path,
        receipt_json={
            "exit_status": 0,
            "loop_reason": "completed",
            "gateway_status": {"this_run": this_run},
        },
    )
    value = status_of(done)
    assert (value["state"], value["calls_used"], value["usd_spent"]) == ("finished", 12, 0.4)
    stopped = tmp_path / "run-2"
    write(stopped / "launch-command.json", {"argv": []})
    write(stopped / "receipt.json", {"exit_status": 1, "loop_reason": "loop exit 1"})
    value = status_of(stopped)
    assert value["state"] == "stopped" and value["reason"] == "loop exit 1"


def test_status_reads_only_and_refuses_a_folder_that_is_not_a_run(tmp_path: Path) -> None:
    run = make_run(tmp_path, receipt_json={"exit_status": 0})
    before = sorted((p.name, p.stat().st_mtime_ns) for p in run.rglob("*"))
    status_of(run)
    assert before == sorted((p.name, p.stat().st_mtime_ns) for p in run.rglob("*"))
    empty = tmp_path / "empty"
    empty.mkdir()
    result = RUNNER.invoke(rdagent_app, ["status", "--run-dir", str(empty)])
    assert result.exit_code != 0 and "not an RD-Agent run folder" in result.output


def test_status_text_says_round_and_next_command(tmp_path: Path) -> None:
    run = make_run(tmp_path, discussion__status_json={"state": "applying", "round": 0})
    result = RUNNER.invoke(rdagent_app, ["status", "--run-dir", str(run)])
    assert result.exit_code == 0
    assert "Round 1 of 3" in result.output and "Next:" in result.output
    assert os.sep in result.output
