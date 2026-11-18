"""What a Codex build's sandbox reaches beyond its worktree: a package cache and read-only links.

Owner-approved 2026-11-18 (docs/reference/model-routing.md, "What the build sandbox allows"). Codex
keeps the workspace-write sandbox with the network off; this module adds exactly two things.

- A fresh, empty uv cache per build under ``<handoff home>/cache/uv/<run id>``, warmed OUTSIDE the
  sandbox before Codex starts and given to Codex as its one extra writable root, so ``uv run``
  works offline inside. Nothing outside the sandbox reads it after Codex starts: the warm step runs
  once, before the first Codex round, and the directory is deleted when the build ends.
- Links to the main checkout's built web assets and frontend packages, for reading and running.
  The sandbox mounts everything outside its writable roots read-only, and that holds through a
  link (checked 2026-11-18 with ``codex sandbox``: EROFS). The tool removes every link before it
  verifies or diffs, so none can be committed or counted against the scope.

Stdlib only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

CACHE_LIMIT_BYTES = 1_500_000_000
WARM_TIMEOUT = 600.0
WEB_ASSETS = "apps/alpha-web/src/alpha_web/static/app"
NODE_MODULES = "apps/alpha-web/frontend/node_modules"
# Package directories are linked one by one into a real node_modules folder in the worktree, so
# the tools' own scratch folders (.tmp, .vite-temp, ...) are written there, never in the target.
_NODE_KEEP_DOT = frozenset({".bin"})

RULE_WITH_CACHE = (
    "- Your sandbox has no network and can write only this directory, `/tmp` and a private "
    "package cache. `uv run ...` works here offline (`UV_OFFLINE=1` is set); never run "
    "`uv sync`, `uv add`, `uv lock` or `pip`. The built web assets "
    "(`apps/alpha-web/src/alpha_web/static/app`) and the frontend packages "
    "(`apps/alpha-web/frontend/node_modules`) are linked in read-only from the main checkout "
    "when it has them: read and run them (`node_modules/.bin/...`), never edit them. The "
    "sandbox cannot open any socket: no tests that use FastAPI `TestClient` (they hang), no "
    "localhost servers, no browsers, no `tests/smoke/` checks, no network calls. Do not claim "
    "such a check passed: list it under UNVERIFIED. The orchestrator runs every check again "
    "outside the sandbox."
)
RULE_WITHOUT_CACHE = (
    "- Your sandbox has no network and cannot write outside this directory: do not run "
    "`uv sync`/`uv run`/`pip`; use `.venv/bin/...`. It cannot run tests that use FastAPI "
    "`TestClient`, bind or connect localhost sockets, start the web server, run browsers or "
    "the `tests/smoke/` checks. Do not claim such a check passed: list it under UNVERIFIED. "
    "The orchestrator runs every check again outside the sandbox."
)

# What may reach the Codex process: enough to find its login (CODEX_HOME / HOME) and run tools.
_CODEX_ENV_KEEP = frozenset(
    {"HOME", "PATH", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ"}
    | {"TMPDIR", "CODEX_HOME", "XDG_RUNTIME_DIR"}
)
_UV_RUN = re.compile(r"\buv run (?:--\S+ )*(python|pytest|ruff|mypy|lint-imports)\b")


def codex_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _CODEX_ENV_KEEP}
    env["NO_COLOR"] = "1"
    return env


def sandbox_command(command: str) -> str:
    """A check rewritten for Codex's sandbox: no ``uv`` (its cache is outside the worktree)."""
    return _UV_RUN.sub(lambda m: f".venv/bin/{m.group(1)}", command)


def _toml(value: str) -> str:
    """A TOML basic string (JSON string escapes are valid TOML)."""
    return json.dumps(value)


def sandbox_args(cache: Path | None) -> list[str]:
    """Codex ``-c`` settings for the workspace-write sandbox: network off, at most the cache added.

    ``exec resume`` has no ``--add-dir``, so the extra root is set through config for both forms.
    The environment is passed with ``shell_environment_policy.set`` because ``inherit="core"``
    drops other variables from the commands Codex runs.
    """
    args = ["-c", "sandbox_workspace_write.network_access=false"]
    if cache is not None:
        uv_env = f'{{UV_CACHE_DIR={_toml(str(cache))}, UV_OFFLINE="1"}}'
        args += ["-c", f"sandbox_workspace_write.writable_roots=[{_toml(str(cache))}]"]
        args += ["-c", f"shell_environment_policy.set={uv_env}"]
    return args


def _within(path: Path, other: Path) -> bool:
    return path == other or other in path.parents


def unsafe_root(cache: Path, home: Path, protected: list[Path]) -> str | None:
    """Why ``cache`` must not become a writable root, or None when it is safe.

    It must be a folder strictly under ``<home>/cache/uv/``, and it may neither hold nor sit inside
    a protected place (the checkouts, the user's own uv cache, Codex's home).
    """
    cache, base = cache.resolve(), (home / "cache" / "uv").resolve()
    if base not in cache.parents:
        return f"{cache} is not a per-build folder under {base}"
    for place in (p.resolve() for p in protected):
        if _within(place, cache):
            return f"{cache} holds {place}"
        if _within(cache, place):
            return f"{cache} is inside {place}"
    return None


def _size(path: Path) -> int:
    total = 0
    for folder, _, files in os.walk(path):
        for name in files:
            total += (Path(folder) / name).lstat().st_size
    return total


@dataclass
class Prepared:
    """What the tool set up for one build's sandbox, so it can take it down again."""

    main: Path
    cache: Path | None = None
    links: list[Path] = field(default_factory=list)
    shadows: list[Path] = field(default_factory=list)
    made_dirs: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _uv(worktree: Path, cache: Path, *, offline: bool) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "UV_CACHE_DIR": str(cache)}
    if offline:
        env["UV_OFFLINE"] = "1"
    return subprocess.run(
        ["uv", "run", "--locked", "python", "-c", ""],
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        timeout=WARM_TIMEOUT,
        check=False,
    )


def protected_places(main: Path, worktree: Path) -> list[Path]:
    """Where the cache may never be: the checkouts, the user's own uv cache, Codex's home."""
    user_uv = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "uv"
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return [main, worktree, user_uv, codex_home]


def provision_cache(home: Path, run_id: str, worktree: Path, main: Path) -> Prepared:
    """A fresh per-build uv cache, warmed now (outside the sandbox) and proven to work offline.

    On any failure the folder is removed and ``cache`` stays None: the build then falls back to
    ``.venv/bin/...`` commands, as before. ``main`` is the main checkout the links point at.
    """
    prep = Prepared(main)
    cache = home / "cache" / "uv" / run_id
    why = unsafe_root(cache, home, protected_places(main, worktree))
    if why:
        prep.notes.append(f"package cache not provided: {why}")
        return prep
    cache.mkdir(parents=True, exist_ok=False)
    warm = _uv(worktree, cache, offline=False)
    proof = _uv(worktree, cache, offline=True) if warm.returncode == 0 else warm
    size = _size(cache)
    if proof.returncode != 0 or size > CACHE_LIMIT_BYTES:
        reason = f"{size:,} bytes" if proof.returncode == 0 else proof.stderr.strip()[-200:]
        prep.notes.append(f"package cache not provided ({reason}); Codex uses .venv/bin")
        prep.cache = cache
        prep.notes += remove_cache(prep)
        return prep
    prep.cache = cache
    prep.notes.append(f"package cache {cache} warmed outside the sandbox: {size:,} bytes")
    return prep


def remove_cache(prep: Prepared) -> list[str]:
    """Delete the build's cache (links inside are removed, never followed); notes on failure."""
    target, prep.cache = prep.cache, None
    if target is None or not target.exists():
        return []
    try:
        shutil.rmtree(target)
    except OSError as exc:
        return [f"could not remove the package cache {target}: {exc}"]
    return []


def link_built_files(worktree: Path, prep: Prepared) -> None:
    """Link the main checkout's built web assets and frontend packages into the worktree."""
    assets, wt_assets = prep.main / WEB_ASSETS, worktree / WEB_ASSETS
    if assets.is_dir() and not os.path.lexists(wt_assets):
        for parent in reversed(wt_assets.parents):
            if _within(parent, worktree) and not parent.exists():
                parent.mkdir()
                prep.made_dirs.append(parent)
        wt_assets.symlink_to(assets, target_is_directory=True)
        prep.links.append(wt_assets)
    nodes, wt_nodes = prep.main / NODE_MODULES, worktree / NODE_MODULES
    if nodes.is_dir() and wt_nodes.parent.is_dir() and not os.path.lexists(wt_nodes):
        wt_nodes.mkdir()
        prep.shadows.append(wt_nodes)
        for entry in sorted(nodes.iterdir()):
            if not entry.name.startswith(".") or entry.name in _NODE_KEEP_DOT:
                (wt_nodes / entry.name).symlink_to(entry)


def unlink_built_files(prep: Prepared) -> list[str]:
    """Remove every pre-linked path; one the builder replaced is reported as a policy violation."""
    problems: list[str] = []
    for path, want_link in [*((p, True) for p in prep.links), *((p, False) for p in prep.shadows)]:
        if not os.path.lexists(path):
            continue
        if path.is_symlink() != want_link or not (path.is_symlink() or path.is_dir()):
            problems.append(f"{path}: the builder replaced a path this tool linked in")
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    for folder in reversed(prep.made_dirs):
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    prep.links.clear()
    prep.shadows.clear()
    prep.made_dirs.clear()
    return problems
