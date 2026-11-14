"""Local viewer boundaries, using synthetic runs and a stand-in foreground process."""

from __future__ import annotations

import errno
import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

WORKER = Path(__file__).resolve().parents[2] / "workers/rdagent"
spec = importlib.util.spec_from_file_location("rdagent_viewer", WORKER / "rdagent_viewer.py")
assert spec is not None and spec.loader is not None
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)


def run_dir(root: Path, name: str = "run") -> Path:
    run = root / name
    (run / "work/log").mkdir(parents=True)
    return run


def test_links_replace_only_symlinks(tmp_path: Path) -> None:
    runs = [run_dir(tmp_path, name) for name in ("first", "second")]
    directory = tmp_path / "links"
    directory.mkdir()
    (directory / "stale").symlink_to(tmp_path / "missing")
    (directory / "first").symlink_to(tmp_path / "old")
    (directory / "keep.txt").write_text("keep")
    (directory / "keep-dir").mkdir()
    assert viewer.links(runs, directory) == directory
    assert not (directory / "stale").is_symlink()
    for run in runs:
        assert (directory / run.name).readlink() == run / "work/log"
    assert (directory / "keep.txt").read_text() == "keep"
    assert (directory / "keep-dir").is_dir()


def test_links_refuse_missing_logs_and_relative_runs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="work/log"):
        viewer.links([tmp_path], tmp_path / "links")
    with pytest.raises(ValueError, match="absolute"):
        viewer.links([Path("relative")], tmp_path / "links")


@pytest.mark.parametrize("marker", ["directory", "file"])
def test_links_refuse_paths_inside_git(tmp_path: Path, marker: str) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    command = ["git", "init", "--quiet"]
    if marker == "file":
        command.extend(["--separate-git-dir", str(tmp_path / "git-metadata")])
    subprocess.run([*command, str(repo)], check=True)
    inside = run_dir(repo)
    outside = run_dir(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(repo, target_is_directory=True)
    for runs, directory in [
        ([inside], tmp_path / "links"),
        ([outside], repo / "links"),
        ([alias / "run"], tmp_path / "links"),
    ]:
        with pytest.raises(ValueError, match="git"):
            viewer.links(runs, directory)


def test_empty_git_named_directory_is_not_a_repository(tmp_path: Path) -> None:
    container = tmp_path / "ordinary-container"
    (container / ".git").mkdir(parents=True)
    run = run_dir(container)
    directory = container / "links"
    assert viewer.links([run], directory) == directory
    assert (directory / run.name).readlink() == run / "work/log"
    assert list((container / ".git").iterdir()) == []


def test_shared_memory_key_and_explicit_override(tmp_path: Path) -> None:
    runs = [run_dir(tmp_path, name) for name in ("first", "second")]
    memory = tmp_path / "memory"
    key = memory / "signing/artifact_signing.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"shared")
    for run in runs:
        (run / "receipt.json").write_text(
            json.dumps({"memory": {"enabled": True, "memory_dir": str(memory)}})
        )
    assert viewer.resolve_key(runs, None) == key
    explicit = tmp_path / "explicit.key"
    explicit.write_bytes(b"explicit")
    assert viewer.resolve_key(runs, explicit) == explicit


@pytest.mark.parametrize(
    "second", [None, {}, {"enabled": False}, {"enabled": True, "memory_dir": "/different"}]
)
def test_mixed_or_missing_memory_requires_explicit_key(tmp_path: Path, second: object) -> None:
    runs = [run_dir(tmp_path, name) for name in ("first", "second")]
    (runs[0] / "receipt.json").write_text(
        json.dumps({"memory": {"enabled": True, "memory_dir": str(tmp_path / "memory")}})
    )
    if second is not None:
        (runs[1] / "receipt.json").write_text(json.dumps({"memory": second}))
    with pytest.raises(ValueError, match="--signing-key"):
        viewer.resolve_key(runs, None)


def test_single_run_uses_its_home_key(tmp_path: Path) -> None:
    run = run_dir(tmp_path)
    key = run / "home/.rdagent/artifact_signing.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"single")
    assert viewer.resolve_key([run], None) == key
    key.unlink()
    with pytest.raises(ValueError, match="--signing-key"):
        viewer.resolve_key([run], None)


@pytest.mark.parametrize("receipt", [[], {"memory": None}, {"memory": []}])
def test_malformed_receipt_refuses_with_key_guidance(tmp_path: Path, receipt: object) -> None:
    run = run_dir(tmp_path)
    (run / "receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="--signing-key"):
        viewer.resolve_key([run], None)


def test_environment_is_exact_and_command_is_local(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LM_STUDIO_API_KEY", "ALPHA_GATEWAY_TOKEN", "OPENAI_API_KEY"):
        monkeypatch.setenv(name, "must-not-leak")
    python = Path("/bundle/venv/bin/python")
    home, source, key = Path("/temporary"), Path("/source"), Path("/temporary/key")
    environment = viewer.viewer_environment(python, home, source, key)
    assert environment == {
        "PATH": "/bundle/venv/bin:/usr/bin:/bin",
        "HOME": "/temporary",
        "LANG": "C.UTF-8",
        "ALPHA_RDAGENT_SOURCE": "/source",
        "ARTIFACT_SIGNING_KEY_PATH": "/temporary/key",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
    }
    assert not any(
        name.startswith(("LM_STUDIO", "ALPHA_GATEWAY", "OPENAI")) for name in environment
    )
    assert viewer.viewer_command(python, Path("/links"), 19899) == [
        str(python),
        "-m",
        "streamlit",
        "run",
        str(WORKER / "rdagent_ui_entry.py"),
        "--server.address",
        "127.0.0.1",
        "--server.port",
        "19899",
        "--server.headless",
        "true",
        "--",
        "--log_dir",
        "/links",
    ]


def test_busy_port_socket_is_refused() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(ValueError, match="already.*listening"):
            viewer.check_port(listener.getsockname()[1])


def test_busy_port_refusal_without_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = Mock()
    connection.bind.side_effect = OSError(errno.EADDRINUSE, "Address already in use")
    context = Mock()
    context.__enter__ = Mock(return_value=connection)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(viewer.socket, "socket", Mock(return_value=context))
    with pytest.raises(ValueError, match="already.*listening"):
        viewer.check_port(19899)
    connection.bind.assert_called_once_with(("127.0.0.1", 19899))


@pytest.mark.parametrize("interrupt", [False, True])
def test_serve_verifies_and_cleans_temporary_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    interrupt: bool,
) -> None:
    run = run_dir(tmp_path)
    key = tmp_path / "key"
    key.write_bytes(b"synthetic key")
    python = tmp_path / "bundle/venv/bin/python"
    monkeypatch.setenv("ALPHA_VIEWER_PYTHON", str(python))
    monkeypatch.setenv("ALPHA_RDAGENT_SOURCE", str(tmp_path / "source"))
    monkeypatch.setattr(viewer, "check_port", Mock())
    homes = []
    commands = []

    def child(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if len(commands) == 1:
            assert command == [
                sys.executable,
                str(WORKER / "install_stock_profile.py"),
                "--profile",
                "ui",
                "--verify",
                str(tmp_path / "bundle"),
            ]
            assert not (tmp_path / "rdagent-viewer-links").exists()
        else:
            environment = kwargs["env"]
            assert isinstance(environment, dict)
            home = Path(environment["HOME"])
            copied = Path(environment["ARTIFACT_SIGNING_KEY_PATH"])
            assert copied.parent == home
            assert copied.read_bytes() == key.read_bytes()
            assert copied.stat().st_mode & 0o777 == 0o600
            homes.append(home)
            if interrupt:
                raise KeyboardInterrupt
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(viewer.subprocess, "run", child)
    result = viewer.main(["serve", "--run-dir", str(run), "--signing-key", str(key)])
    assert result == (130 if interrupt else 0)
    assert len(commands) == 2
    assert homes and all(not home.exists() for home in homes)
    assert "http://127.0.0.1:19899" in capsys.readouterr().out
    assert key.read_bytes() == b"synthetic key"


def test_failed_verification_never_starts_viewer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ALPHA_VIEWER_PYTHON", str(tmp_path / "bundle/venv/bin/python"))
    monkeypatch.setenv("ALPHA_RDAGENT_SOURCE", str(tmp_path / "source"))
    child = Mock(side_effect=subprocess.CalledProcessError(1, ["verify"]))
    monkeypatch.setattr(viewer.subprocess, "run", child)
    assert viewer.main(["serve", "--run-dir", str(tmp_path)]) == 1
    assert child.call_count == 1
    assert "rdagent-viewer:" in capsys.readouterr().err
