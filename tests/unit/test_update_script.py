"""scripts/update.sh: step order, the way back and the refusals, with real git and fake tools.

No network: origin is a local repository; uv, npm, systemctl, curl, ss and alpha only record calls.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha_cli.main import app

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/update.sh"
STUB = (
    f"#!{sys.executable}\n"
    + """import os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
command = " ".join([name, *sys.argv[1:]])
with open(os.environ["UPDATE_LOG"], "a") as log:
    log.write(command + " @ " + Path(os.getcwd()).name + "\\n")
if name == "systemctl" and sys.argv[1:3] == ["--user", "show"]:
    print("4242" if "MainPID" in command else "ALPHA_WEB_PORT=8802")
if name == "ss":
    print("LISTEN users:((\\"alpha-web\\",pid=4242,fd=3))")
if name == "curl":
    print("200")
if name == "alpha" and os.environ.get("BROKEN_TAG") and \\
        Path(os.environ["CHECKOUT"], "VERSION").read_text().strip() == os.environ["BROKEN_TAG"] \\
        and sys.argv[1:] == ["next"]:
    sys.exit(3)
"""
)
ALL_TOOLS = ("uv", "npm", "systemctl", "curl", "ss")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


class Fixture:
    def __init__(self, tmp_path: Path) -> None:
        self.origin = tmp_path / "origin"
        self.origin.mkdir()
        self.checkout = tmp_path / "checkout"
        git(self.origin, "init", "-q", "-b", "main")
        self.commits: dict[str, str] = {}
        for tag in ("r1", "r2"):
            (self.origin / "scripts").mkdir(exist_ok=True)
            shutil.copyfile(SCRIPT, self.origin / "scripts/update.sh")
            (self.origin / "VERSION").write_text(tag + "\n")
            (self.origin / ".gitignore").write_text(".update/\n.venv/\n")
            git(self.origin, "add", "-A")
            git(self.origin, "commit", "-q", "-m", tag)
            git(self.origin, "tag", tag)
            self.commits[tag] = git(self.origin, "rev-parse", "HEAD")
        git(tmp_path, "clone", "-q", str(self.origin), str(self.checkout))
        git(self.checkout, "checkout", "-q", "--detach", "r1")
        (self.checkout / ".venv/bin").mkdir(parents=True)
        for folder, lock in (("a", True), ("b", True), ("c", False), ("d", True)):
            (self.checkout / "workers" / folder / ".venv").mkdir(parents=True)
            if lock:
                (self.checkout / "workers" / folder / "uv.lock").write_text("")
        self.log = tmp_path / "calls.log"
        self.tools = tmp_path / "tools"
        self.tools.mkdir()
        for name in (*ALL_TOOLS, "alpha"):
            (self.tools / name).write_text(STUB)
            (self.tools / name).chmod(0o755)
        (self.checkout / ".venv/bin/alpha").symlink_to(self.tools / "alpha")
        self.data = tmp_path / "data"
        self.data.mkdir()

    def run(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        environment = {
            "PATH": f"{self.tools}:{os.environ['PATH']}",
            "HOME": str(self.checkout.parent),
            "UPDATE_LOG": str(self.log),
            "CHECKOUT": str(self.checkout),
            "ALPHA_DATA_DIR": str(self.data),
            **extra,
        }
        return subprocess.run(
            ["bash", str(self.checkout / "scripts/update.sh"), *args],
            cwd=self.checkout.parent,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def head(self) -> str:
        return git(self.checkout, "rev-parse", "HEAD")


@pytest.fixture()
def fx(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path)


def test_happy_path_installs_every_locked_worker_in_order(fx: Fixture) -> None:
    result = fx.run("--to", "r2")
    assert result.returncode == 0, result.stdout + result.stderr
    assert fx.head() == fx.commits["r2"]
    assert (fx.checkout / ".update/last-good").read_text().strip() == fx.commits["r2"]
    syncs = [c for c in fx.calls() if c.startswith("uv sync --locked")]
    assert syncs == [
        "uv sync --locked @ checkout",
        "uv sync --locked @ a",
        "uv sync --locked @ b",
        "uv sync --locked @ d",
    ]
    calls = fx.calls()
    assert calls.index(
        "systemctl --user restart alpha-workstation.service @ checkout"
    ) > calls.index("uv sync --locked @ d")
    assert "alpha data coverage @ checkout" in calls
    assert "from r1 to r2" in result.stdout and "releases/tag/r2" in result.stdout


def test_default_target_is_the_newest_tag(fx: Fixture) -> None:
    assert fx.run().returncode == 0
    assert fx.head() == fx.commits["r2"]


def test_failing_smoke_check_returns_to_the_last_good_commit(fx: Fixture) -> None:
    result = fx.run("--to", "r2", BROKEN_TAG="r2")
    assert result.returncode == 1, result.stdout + result.stderr
    assert fx.head() == fx.commits["r1"]
    assert "Returned to the last good version r1." in result.stderr
    assert (fx.checkout / ".update/last-good").read_text().strip() == fx.commits["r1"]
    assert len([c for c in fx.calls() if c.startswith("systemctl --user restart")]) == 2


def test_a_failed_return_exits_two_and_names_the_commit(fx: Fixture) -> None:
    (fx.tools / "uv").write_text(STUB.replace("with open", "sys.exit(5)\nwith open", 1))
    result = fx.run("--to", "r2")
    assert result.returncode == 2
    assert fx.commits["r1"] in result.stderr


def test_dirty_checkout_is_refused(fx: Fixture) -> None:
    (fx.checkout / "VERSION").write_text("changed\n")
    result = fx.run("--to", "r2")
    assert result.returncode == 1 and "uncommitted changes" in result.stderr
    assert fx.calls() == [] and fx.head() == fx.commits["r1"]


def test_already_current_changes_nothing(fx: Fixture) -> None:
    result = fx.run("--to", "r1")
    assert result.returncode == 0 and "Already at r1" in result.stdout
    assert fx.calls() == [] and not (fx.checkout / ".update").exists()


def test_check_only_changes_nothing(fx: Fixture) -> None:
    result = fx.run("--check-only")
    assert result.returncode == 0, result.stderr
    assert fx.head() == fx.commits["r1"] and not (fx.checkout / ".update").exists()
    assert not any(c.startswith(("uv sync", "npm", "systemctl --user restart")) for c in fx.calls())
    bad = fx.run("--check-only", BROKEN_TAG="r1")
    assert bad.returncode == 1 and fx.head() == fx.commits["r1"]


def test_no_restart_skips_the_service_steps(fx: Fixture) -> None:
    result = fx.run("--to", "r2", "--no-restart")
    assert result.returncode == 0, result.stderr
    assert not any(c.startswith(("systemctl", "ss", "curl")) for c in fx.calls())


def test_update_command_lists_its_options() -> None:
    result = CliRunner().invoke(app, ["home", "update", "--help"])
    assert result.exit_code == 0
    for option in ("--to", "--check-only", "--service", "--no-restart"):
        assert option in result.output
