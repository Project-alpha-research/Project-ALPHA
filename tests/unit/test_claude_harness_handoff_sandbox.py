"""`scripts/handoff_sandbox.py` — what a Codex build's sandbox may reach beyond its worktree.

The build-level behaviour (links in place during Codex, gone before verification; the cache used
outside the sandbox only before Codex starts) is pinned in `test_claude_harness_handoff.py`.
"""

from __future__ import annotations

from pathlib import Path

import handoff_sandbox
import pytest


def test_sandbox_args_keep_the_network_off_and_add_only_the_cache(tmp_path: Path) -> None:
    assert handoff_sandbox.sandbox_args(None) == [
        "-c",
        "sandbox_workspace_write.network_access=false",
    ]
    cache = tmp_path / "cache" / "uv" / "run-1"
    args = handoff_sandbox.sandbox_args(cache)
    settings = args[1::2]
    assert args[0::2] == ["-c"] * 3
    assert settings == [
        "sandbox_workspace_write.network_access=false",
        f'sandbox_workspace_write.writable_roots=["{cache}"]',
        f'shell_environment_policy.set={{UV_CACHE_DIR="{cache}", UV_OFFLINE="1"}}',
    ]
    assert not any("network_access=true" in a or "danger" in a for a in args)


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("cache/uv/run-1", None),
        ("cache/uv", "not a per-build folder"),
        ("cache/other/run-1", "not a per-build folder"),
        ("cache/uv/run-1/../../../..", "not a per-build folder"),
    ],
)
def test_the_cache_must_be_a_per_build_folder(
    tmp_path: Path, relative: str, expected: str | None
) -> None:
    home = tmp_path / "handoff"
    why = handoff_sandbox.unsafe_root(home / relative, home, [])
    assert (why is None) if expected is None else (why is not None and expected in why)


def test_the_cache_may_not_overlap_a_protected_place(tmp_path: Path) -> None:
    home = tmp_path / "handoff"
    cache = home / "cache" / "uv" / "run-1"
    inside = handoff_sandbox.unsafe_root(cache, home, [home / "cache"])
    assert inside is not None and "is inside" in inside
    holds = handoff_sandbox.unsafe_root(cache, home, [cache / "checkout"])
    assert holds is not None and "holds" in holds


def test_protected_places_name_the_checkouts_and_the_user_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    places = handoff_sandbox.protected_places(tmp_path / "main", tmp_path / "wt")
    assert places == [tmp_path / "main", tmp_path / "wt", tmp_path / "xdg/uv", tmp_path / "codex"]


def test_an_oversized_cache_is_not_provided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(handoff_sandbox, "CACHE_LIMIT_BYTES", 0)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text('#!/bin/sh\necho data > "$UV_CACHE_DIR/blob"\n')
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    home = tmp_path / "handoff"
    (tmp_path / "wt").mkdir()
    prep = handoff_sandbox.provision_cache(home, "run-1", tmp_path / "wt", tmp_path / "main")
    assert prep.cache is None and "not provided (5 bytes)" in prep.notes[0]
    assert not (home / "cache" / "uv" / "run-1").exists()


def test_the_sandbox_rule_stays_honest() -> None:
    for rule in (handoff_sandbox.RULE_WITH_CACHE, handoff_sandbox.RULE_WITHOUT_CACHE):
        assert "no network" in rule and "UNVERIFIED" in rule and "TestClient" in rule
        assert "outside the sandbox" in rule
    assert "never edit them" in handoff_sandbox.RULE_WITH_CACHE
    assert "`uv sync`" in handoff_sandbox.RULE_WITH_CACHE


def test_unlink_removes_only_what_the_tool_made(tmp_path: Path) -> None:
    main, wt = tmp_path / "main", tmp_path / "wt"
    (main / handoff_sandbox.WEB_ASSETS).mkdir(parents=True)
    (main / handoff_sandbox.NODE_MODULES / "pkg").mkdir(parents=True)
    (wt / "apps/alpha-web/frontend").mkdir(parents=True)
    prep = handoff_sandbox.Prepared(main)
    handoff_sandbox.link_built_files(wt, prep)
    assert (wt / handoff_sandbox.WEB_ASSETS).is_symlink()
    (wt / handoff_sandbox.NODE_MODULES / ".tmp").mkdir()  # a tool's scratch folder
    assert handoff_sandbox.unlink_built_files(prep) == []
    assert not (wt / "apps/alpha-web/src").exists() and (wt / "apps/alpha-web/frontend").is_dir()
    assert not (wt / handoff_sandbox.NODE_MODULES).exists()
    assert (main / handoff_sandbox.NODE_MODULES / "pkg").is_dir()
    assert (main / handoff_sandbox.WEB_ASSETS).is_dir()


def test_sandbox_command_rewrites_uv_run_for_the_fallback_form() -> None:
    assert handoff_sandbox.sandbox_command("uv run pytest -q a") == ".venv/bin/pytest -q a"
    assert handoff_sandbox.sandbox_command("uv run python -m x") == ".venv/bin/python -m x"
    assert handoff_sandbox.sandbox_command("test -f a") == "test -f a"
