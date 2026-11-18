"""`scripts/handoff_routing.py`: what a build reads, what it leaves in git and how checks run."""

from __future__ import annotations

import os
import shlex
import stat
import sys
from pathlib import Path

import handoff_routing as routing
import handoff_sandbox
import pytest

_CONTEXT = """---
owner: x
sources:
  - src/**
verified: 0000000000000000
---

# src workspace

## Read first

| Read | Section | When |
|---|---|---|
| [rules](../docs/rules.md) | Checks | always |
| [rules](../docs/rules.md) | Long part | changing the long part |
| [guide](../docs/guide.md) | — | always |
| [design](../docs/design.md) | — | adding a feature |
| [missing](../docs/gone.md) | — | always |

## How to change it

- edit
"""

_RULES = "# Rules\n\n## Checks\n\nrun the gate\n\n### Sub\n\nmore\n\n## Long part\n\n" + "x" * 500


def _repo(tmp_path: Path) -> Path:
    files = {
        "src/CONTEXT.md": _CONTEXT,
        "docs/rules.md": _RULES + "\n\n## After\n\ny\n",
        "docs/guide.md": "# Guide\n\n" + "g" * 100 + "\n",
        "docs/design.md": "# Design\n\n" + "d" * 3000 + "\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return tmp_path


def test_reading_table_rows_resolve_to_repo_paths_and_sections(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    rows, problems = routing.reading_rows(root, "src/CONTEXT.md")
    assert problems == []
    assert [(r.target, r.section, r.when) for r in rows] == [
        ("docs/rules.md", "Checks", "always"),
        ("docs/rules.md", "Long part", "changing the long part"),
        ("docs/guide.md", "", "always"),
        ("docs/design.md", "", "adding a feature"),
        ("docs/gone.md", "", "always"),
    ]


def test_a_malformed_reading_table_is_reported_not_guessed(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "src/CONTEXT.md").write_text(
        "# src\n\n## Read first\n\n| File | When |\n|---|---|\n| [a](a.md) | always |\n"
        "\n## Outputs\n",
        encoding="utf-8",
    )
    rows, problems = routing.reading_rows(root, "src/CONTEXT.md")
    assert rows == [] and problems == [
        "src/CONTEXT.md: the Read first table header is not '| Read | Section | When |'"
    ]
    (root / "src/CONTEXT.md").write_text(
        "# src\n\n## Read first\n\n| Read | Section | When |\n|---|---|---|\n"
        "| [a](../docs/guide.md) | always |\n| [b](../docs/guide.md) | — | always |\n",
        encoding="utf-8",
    )
    rows, problems = routing.reading_rows(root, "src/CONTEXT.md")
    assert [r.target for r in rows] == ["docs/guide.md"]
    assert problems == [
        "src/CONTEXT.md: Read first row skipped (needs 3 cells): | [a](../docs/guide.md) | always |"
    ]
    (root / "src/CONTEXT.md").write_text("# src\n\nno table\n", encoding="utf-8")
    assert routing.reading_rows(root, "src/CONTEXT.md") == ([], [])


def test_routed_reads_are_sized_by_section_deduplicated_and_always_first(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    brief = [routing.ReadRow("docs/guide.md", "", "always", "brief")]
    routed = routing.route(root, ["src/CONTEXT.md"], brief)
    got = [(e["path"], e["section"], e["when"]) for e in routed.entries]
    assert got == [
        ("docs/rules.md", "Checks", "always"),
        ("docs/rules.md", "Long part", "changing the long part"),
        ("docs/design.md", "", "adding a feature"),
    ], "the brief already reads the guide whole; always rows come first"
    checks = "## Checks\n\nrun the gate\n\n### Sub\n\nmore\n\n"
    assert routed.entries[0]["bytes"] == len(checks.encode())
    assert routed.entries[2]["bytes"] == (root / "docs/design.md").stat().st_size
    assert routed.total == sum(e["bytes"] for e in routed.entries)
    assert routed.problems == ["src/CONTEXT.md: docs/gone.md is not a file"]
    lines = routed.prompt_lines()
    assert lines[0].startswith("- `docs/rules.md` — Checks (") and "; always" in lines[0]
    assert "(routed from `src/CONTEXT.md`)" in lines[0]
    record = routed.record()
    assert record["total_bytes"] == routed.total and record["left_out"] == []


def test_routed_reads_over_the_cap_are_left_out_and_named(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    routed = routing.route(root, ["src/CONTEXT.md"], [], cap=1000)
    assert [e["path"] for e in routed.entries] == [
        "docs/rules.md",
        "docs/guide.md",
        "docs/rules.md",
    ]
    assert [(e["path"], e["bytes"]) for e in routed.left_out] == [
        ("docs/design.md", (root / "docs/design.md").stat().st_size)
    ]
    assert routed.total <= 1000
    assert any(
        "left out over the 1,000-byte cap: `docs/design.md`" in ln for ln in routed.prompt_lines()
    )
    assert routed.record()["left_out"][0]["path"] == "docs/design.md"


def test_home_paths_become_repo_relative_or_outside_repo(tmp_path: Path) -> None:
    roots = [Path("/home/someone/checkout"), Path("/home/someone/tmp/handoff/wt/x")]
    text = (
        "Edited /home/someone/tmp/handoff/wt/x/src/mod.py and /home/someone/checkout/docs/a.md.\n"
        "Read `/home/someone/tmp/handoff/designs/plan.md` and /home/other/.codex/auth\n"
        "Model gpt-6.2-sol and claude-opus-5 said hi; Sonnet too.\n"
    )
    assert routing.strip_paths(text, roots) == (
        "Edited src/mod.py and docs/a.md.\n"
        "Read `<outside-repo>` and <outside-repo>\n"
        "Model <model> and <model> said hi; <model> too.\n"
    )


def test_task_files_land_in_a_dated_folder_and_reuse_it(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    folder = routing.task_folder(wt, "fix-it", None, "2026-11-18")
    assert folder == "docs/work/2026-11-18-fix-it"
    written = routing.save_task_files(
        wt, [wt], folder, brief="# Brief\n\nfix\n", report="## Changed files\n- x\n"
    )
    assert written == [f"{folder}/brief.md", f"{folder}/report.md"]
    assert (wt / folder / "brief.md").read_text(encoding="utf-8") == "# Brief\n\nfix\n"
    report = (wt / folder / "report.md").read_text(encoding="utf-8")
    assert report.startswith("# Build report: fix-it\n") and "- x" in report
    assert routing.task_folder(wt, "fix-it", None, "2026-11-20") == folder, "a rebuild reuses it"
    assert routing.task_folder(wt, "fix-it", "docs/work/2026-11-01-plan", "x") == (
        "docs/work/2026-11-01-plan"
    )
    assert routing.save_task_files(wt, [wt], folder, brief=None, report="") == []


def test_pytest_checks_run_under_the_owned_test_runner() -> None:
    owner = str(Path(routing.__file__).with_name("run_owned_test.py"))
    wrapped = routing.owned("uv run pytest -q tests/unit/test_web_x.py", 900.0)
    assert shlex.split(wrapped) == [
        sys.executable,
        owner,
        "--timeout",
        "900",
        "--",
        "bash",
        "-c",
        "uv run pytest -q tests/unit/test_web_x.py",
    ]
    for plain in ("uv run python scripts/gate.py check", "! grep -q BAD src/mod.py"):
        assert routing.owned(plain, 900.0) == plain


def test_checks_get_a_private_tmpdir_that_is_removed_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMPDIR", "/tmp")
    with routing.check_env() as env:
        private = Path(env["TMPDIR"])
        if Path("/dev/shm").is_dir() and os.access("/dev/shm", os.W_OK):
            assert private.parent == Path("/dev/shm") and private.is_dir()
            assert stat.S_IMODE(private.stat().st_mode) == 0o700
        else:
            assert private == Path("/tmp")
    assert private == Path("/tmp") or not private.exists()


def _frontend(path: Path, *, bundle: bool) -> None:
    (path / routing.WEB_FRONTEND).mkdir(parents=True, exist_ok=True)
    (path / routing.WEB_FRONTEND / "package.json").write_text("{}\n")
    if bundle:
        (path / handoff_sandbox.WEB_ASSETS).mkdir(parents=True)
        (path / handoff_sandbox.WEB_ASSETS / "index.html").write_text("<html>\n")


def test_web_bundle_step_skips_links_or_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main, wt = tmp_path / "main", tmp_path / "wt"
    wt.mkdir()
    main.mkdir()
    step = routing.web_bundle(wt, main, [], [])
    assert (step.prep, step.notes) == (None, []), "no frontend: nothing to do"
    _frontend(wt, bundle=False)
    _frontend(main, bundle=True)
    step = routing.web_bundle(wt, main, ["src/mod.py"], ["uv run pytest -q"])
    assert step.prep is not None and (wt / handoff_sandbox.WEB_ASSETS).is_symlink()
    assert "linked" in step.notes[0]
    assert handoff_sandbox.unlink_built_files(step.prep) == []
    assert not os.path.lexists(wt / handoff_sandbox.WEB_ASSETS)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    changed = [f"{routing.WEB_FRONTEND}/src/App.tsx"]
    step = routing.web_bundle(wt, main, changed, [])
    assert step.prep is None and step.notes == [
        "web app not built for the checks: npm is not available"
    ]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "npm"
    fake.write_text(
        '#!/bin/sh\necho "$@" >> ../../../npm-calls\n'
        'if [ "$1" = run ]; then mkdir -p ../src/alpha_web/static/app && '
        "echo x > ../src/alpha_web/static/app/index.html; fi\n"
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    step = routing.web_bundle(wt, main, ["src/mod.py"], ["cd apps/alpha-web/frontend && npm test"])
    assert step.prep is None and "built the web app" in step.notes[0]
    assert (wt / handoff_sandbox.WEB_ASSETS / "index.html").is_file()
    assert (wt / "npm-calls").read_text() == "ci\nrun build\n"
    assert step.ignored == {f"{handoff_sandbox.WEB_ASSETS}/"}
    assert routing.web_bundle(wt, main, ["src/mod.py"], []).notes == [], "built: nothing to do"
