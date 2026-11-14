"""Run RD-Agent's pinned log viewer in the foreground, on this computer only."""

from __future__ import annotations

import argparse
import errno
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

WORKER = Path(__file__).resolve().parent


def _outside_git(path: Path) -> Path:
    resolved = path.resolve()
    for candidate in (path.absolute(), resolved):
        for parent in (candidate, *candidate.parents):
            marker = parent / ".git"
            # Worktrees use a gitdir file; repository directories contain HEAD even
            # before the first commit. An empty directory named .git is neither.
            if marker.is_file() or (marker / "HEAD").is_file():
                raise ValueError(f"path must be outside git: {path}")
    return resolved


def links(run_dirs: list[Path], links_dir: Path) -> Path:
    """Replace the viewer's symlinks without removing any other directory entries."""
    if not run_dirs:
        raise ValueError("at least one --run-dir is required")
    targets = {}
    for run in run_dirs:
        if not run.is_absolute():
            raise ValueError(f"--run-dir must be absolute: {run}")
        _outside_git(run)
        target = _outside_git(run / "work/log")
        if not target.is_dir():
            raise ValueError(f"run must contain work/log/: {run}")
        if run.name in targets:
            raise ValueError(f"run folder names must be unique: {run.name}")
        targets[run.name] = target
    directory = _outside_git(links_dir)
    directory.mkdir(parents=True, exist_ok=True)
    for name in targets:
        destination = directory / name
        if destination.exists() and not destination.is_symlink():
            raise ValueError(f"cannot replace a non-symlink: {destination}")
    for entry in directory.iterdir():
        if entry.is_symlink():
            entry.unlink()
    for name, target in targets.items():
        (directory / name).symlink_to(target, target_is_directory=True)
    return directory


def resolve_key(run_dirs: list[Path], explicit: Path | None) -> Path:
    """Select the explicit key, unanimous memory key, or a single run's home key."""
    key = explicit
    if key is None:
        memories = []
        for run in run_dirs:
            receipt = run / "receipt.json"
            value = json.loads(receipt.read_bytes()) if receipt.exists() else {}
            if not isinstance(value, dict) or not isinstance(value.get("memory", {}), dict):
                raise ValueError(f"invalid memory receipt: {receipt}; supply --signing-key PATH")
            memory = value.get("memory", {})
            directory = memory.get("memory_dir")
            memories.append(
                directory if memory.get("enabled") is True and isinstance(directory, str) else None
            )
        if memories and memories[0] and all(item == memories[0] for item in memories):
            key = Path(memories[0]) / "signing/artifact_signing.key"
        elif len(run_dirs) == 1:
            key = run_dirs[0] / "home/.rdagent/artifact_signing.key"
    if key is None or not key.is_file():
        raise ValueError("cannot select a signing key; supply --signing-key PATH")
    return key


def viewer_environment(python: Path, home: Path, source: Path, key: Path) -> dict[str, str]:
    return {
        "PATH": f"{python.parent}:/usr/bin:/bin",
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "ALPHA_RDAGENT_SOURCE": str(source),
        "ARTIFACT_SIGNING_KEY_PATH": str(key),
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
    }


def viewer_command(python: Path, links_dir: Path, port: int) -> list[str]:
    return [
        str(python),
        "-m",
        "streamlit",
        "run",
        str(WORKER / "rdagent_ui_entry.py"),
        "--server.address",
        "127.0.0.1",
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--",
        "--log_dir",
        str(links_dir),
    ]


def check_port(port: int) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    with socket.socket() as connection:
        try:
            connection.bind(("127.0.0.1", port))
        except OSError as error:
            if error.errno == errno.EADDRINUSE:
                raise ValueError(
                    f"port {port} is already listening; choose another --port"
                ) from error
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    serve = parser.add_subparsers(dest="command", required=True).add_parser("serve")
    serve.add_argument("--run-dir", type=Path, action="append", required=True)
    serve.add_argument("--links-dir", type=Path)
    serve.add_argument("--port", type=int, default=19899)
    serve.add_argument("--signing-key", type=Path)
    args = parser.parse_args(argv)
    try:
        if not os.environ.get("ALPHA_VIEWER_PYTHON") or not os.environ.get("ALPHA_RDAGENT_SOURCE"):
            raise ValueError(
                "set ALPHA_VIEWER_PYTHON and ALPHA_RDAGENT_SOURCE from setup --with-ui"
            )
        # Do not resolve the venv executable symlink: the bundle is above its lexical path.
        python = Path(os.environ["ALPHA_VIEWER_PYTHON"]).absolute()
        source = Path(os.environ["ALPHA_RDAGENT_SOURCE"]).absolute()
        subprocess.run(
            [
                sys.executable,
                str(WORKER / "install_stock_profile.py"),
                "--profile",
                "ui",
                "--verify",
                str(python.parents[2]),
            ],
            check=True,
        )
        check_port(args.port)
        directory = links(
            args.run_dir, args.links_dir or args.run_dir[0].parent / "rdagent-viewer-links"
        )
        key = resolve_key(args.run_dir, args.signing_key)
        with tempfile.TemporaryDirectory(prefix="alpha-rdagent-viewer-") as temporary:
            home = Path(temporary)
            copied = home / "artifact_signing.key"
            shutil.copyfile(key, copied)
            copied.chmod(0o600)
            environment = viewer_environment(python, home, source, copied)
            print(f"RD-Agent viewer: http://127.0.0.1:{args.port}", flush=True)
            return subprocess.run(
                viewer_command(python, directory, args.port), env=environment, cwd=home, check=False
            ).returncode
    except KeyboardInterrupt:
        print("rdagent-viewer: interrupted", file=sys.stderr)
        return 130
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"rdagent-viewer: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
