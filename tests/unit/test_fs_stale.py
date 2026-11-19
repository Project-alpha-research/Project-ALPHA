"""`fs.py stale|owners|verify`: living documents are stamped with a fingerprint of their sources."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import fs
import fs_stale
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _write(repo: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    _write(repo, files)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _doc(verified: str, *sources: str) -> str:
    listed = "".join(f"  - {source}\n" for source in sources)
    return f"---\nowner: data layer\nsources:\n{listed}verified: {verified}\n---\n\n# Doc\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    return tmp_path


def _fresh(repo: Path, *sources: str, code: dict[str, str] | None = None) -> None:
    """A committed repository whose one document, docs/a.md, is verified against its sources."""
    _commit(repo, code or {"src/a.py": "a = 1\n", "src/b.py": "b = 1\n"}, "code")
    _commit(repo, {"docs/a.md": _doc("unset", *(sources or ("src/**",)))}, "doc")
    fs_stale.verify(repo, ["docs/a.md"])
    _commit(repo, {}, "stamp")


def test_front_matter_parses_scalars_and_lists() -> None:
    meta = fs_stale.front_matter(_doc("abc1234", "src/**", "tests/test_*.py"))
    assert meta == {
        "owner": "data layer",
        "sources": ["src/**", "tests/test_*.py"],
        "verified": "abc1234",
    }
    assert fs_stale.front_matter("# No front matter\n") is None
    with pytest.raises(fs_stale.FrontMatterError, match="not closed"):
        fs_stale.front_matter("---\nowner: x\n")
    with pytest.raises(fs_stale.FrontMatterError, match="duplicate"):
        fs_stale.front_matter("---\nowner: x\nowner: y\n---\n")


def test_verified_document_is_fresh_and_its_own_edits_do_not_count(repo: Path) -> None:
    _fresh(repo, "src/**", "docs/a.md")
    text = (repo / "docs/a.md").read_text(encoding="utf-8")
    assert "# Doc" in text and "verified: unset" not in text
    _commit(repo, {"docs/a.md": text + "More.\n"}, "doc edit")
    [report] = fs_stale.stale(repo)
    assert not report.stale and report.problems == []
    assert len(report.verified) == 16 and report.verified == report.fingerprint


@pytest.mark.parametrize("committed", [True, False])
def test_edit_add_and_delete_of_a_source_each_make_the_document_stale(
    repo: Path, committed: bool
) -> None:
    _fresh(repo)
    changes: list[dict[str, str]] = [{"src/a.py": "a = 2\n"}, {"src/new.py": "n = 1\n"}]
    for files in changes:
        _write(repo, files)
        if committed:
            _commit(repo, {}, "change")
        [report] = fs_stale.stale(repo)
        assert report.stale
        assert report.changed_files == (list(files) if "src/a.py" in files or committed else [])
        assert "STALE   docs/a.md" in fs_stale.render_text([report])
        fs_stale.verify(repo, ["docs/a.md"], reason="re-read; nothing it states changed")
        _commit(repo, {}, "stamp")
        assert not fs_stale.stale(repo)[0].stale
    (repo / "src/b.py").unlink()
    assert fs_stale.stale(repo)[0].stale


def test_unrelated_and_ignored_files_do_not_make_a_document_stale(repo: Path) -> None:
    _fresh(repo)
    _commit(repo, {"other.py": "x = 1\n", ".gitignore": "*.pyc\n"}, "elsewhere")
    _write(repo, {"src/a.pyc": "bytes"})
    assert not fs_stale.stale(repo)[0].stale


def test_unmatched_glob_is_a_problem_and_verify_refuses_it(repo: Path) -> None:
    _commit(repo, {"src/a.py": "a = 1\n"}, "code")
    _commit(repo, {"docs/a.md": _doc("unset", "src/**", "missing/**")}, "doc")
    [report] = fs_stale.stale(repo)
    assert report.problems == ["source glob matches no file: missing/**"]
    with pytest.raises(ValueError, match="missing"):
        fs_stale.verify(repo, ["docs/a.md"])
    with pytest.raises(ValueError, match="not a living document"):
        fs_stale.verify(repo, ["src/a.py"])
    assert "verified: unset" in (repo / "docs/a.md").read_text(encoding="utf-8")


def test_generated_and_plain_documents_are_skipped(repo: Path) -> None:
    _commit(
        repo,
        {
            "src/a.py": "",
            "docs/gen.md": "---\ngenerated_by: make\nsources:\n  - src/**\n---\n# Gen\n",
            "docs/plain.md": "# Plain\n",
        },
        "docs",
    )
    assert fs_stale.stale(repo) == []


def test_owners_names_the_documents_that_describe_a_path(repo: Path) -> None:
    _fresh(repo, "src/*.py", "tools", code={"src/a.py": "", "tools/x.sh": ""})
    _commit(repo, {"docs/b.md": _doc("unset", "src/**"), "src/deep/c.py": ""}, "second doc")
    assert fs_stale.owners(repo, ["src/a.py", "src/deep/c.py", "tools/x.sh", "docs/a.md", "z"]) == {
        "src/a.py": ["docs/a.md", "docs/b.md"],
        "src/deep/c.py": ["docs/b.md"],
        "tools/x.sh": ["docs/a.md"],
        "docs/a.md": [],
        "z": [],
    }


def test_a_document_named_as_a_source_counts_by_its_text_not_its_stamp(repo: Path) -> None:
    _commit(repo, {"src/a.py": "a = 1\n"}, "code")
    _commit(
        repo,
        {"docs/log.md": _doc("unset", "src/**"), "docs/a.md": _doc("unset", "docs/log.md")},
        "docs",
    )
    fs_stale.verify(repo, ["docs/log.md", "docs/a.md"])
    _commit(repo, {}, "stamp")
    [doc, _log] = fs_stale.stale(repo)
    assert not doc.stale and doc.fingerprint != fs_stale.EMPTY_FINGERPRINT and not doc.unchecked
    # The named document's stamp changing (a source of its own moved) does not cascade.
    _commit(repo, {"src/a.py": "a = 2\n"}, "code change")
    fs_stale.verify(repo, ["docs/log.md"], reason="src/a.py renamed nothing the log states")
    assert not fs_stale.stale(repo)[0].stale
    # Its text changing does.
    text = (repo / "docs/log.md").read_text(encoding="utf-8")
    _commit(repo, {"docs/log.md": text + "A new decision.\n"}, "decision")
    report = fs_stale.stale(repo)[0]
    assert report.stale and report.changed_files == ["docs/log.md"]


def test_a_document_with_nothing_to_check_is_reported_and_verify_refuses_it(repo: Path) -> None:
    _commit(repo, {"src/a.py": "a = 1\n", "docs/a.md": _doc("unset", "docs/a.md")}, "docs")
    [report] = fs_stale.stale(repo)
    assert report.unchecked and not report.stale and report.problems == []
    text = fs_stale.render_text([report])
    assert "cannot be checked" in text and "docs/a.md" in text
    assert fs.main(["--root", str(repo), "stale", "--strict"]) == 0
    with pytest.raises(ValueError, match="cannot be checked"):
        fs_stale.verify(repo, ["docs/a.md"], reason="nothing it could be checked against")


def test_verify_needs_an_edit_or_a_reason_and_records_the_reason(repo: Path) -> None:
    _fresh(repo)
    _commit(repo, {"src/a.py": "a = 2\nb = 3\n"}, "change")
    with pytest.raises(ValueError, match=r"(?s)--reason.*src/a\.py \(\+2 -1\)"):
        fs_stale.verify(repo, ["docs/a.md"])
    with pytest.raises(ValueError, match="say why"):
        fs_stale.verify(repo, ["docs/a.md"], reason="ok")
    assert fs_stale.stale(repo)[0].stale
    [report] = fs_stale.verify(repo, ["docs/a.md"], reason="the doc names no values in src/a.py")
    assert report.source_changes == [("src/a.py", 2, 1)]
    log = (repo / fs_stale.REASONS_LOG).read_text(encoding="utf-8")
    assert f"docs/a.md\n  verified {report.fingerprint}" in log
    assert "the doc names no values in src/a.py" in log
    # The log is not a source: recording a reason makes nothing stale.
    assert not fs_stale.stale(repo)[0].stale
    _commit(repo, {}, "stamp")
    # An edit to the document's own text is evidence of a re-read: no reason needed.
    _commit(repo, {"src/b.py": "b = 2\n"}, "change b")
    text = (repo / "docs/a.md").read_text(encoding="utf-8")
    _write(repo, {"docs/a.md": text + "Corrected.\n"})
    [report] = fs_stale.verify(repo, ["docs/a.md"])
    assert not fs_stale.stale(repo)[0].stale
    assert log == (repo / fs_stale.REASONS_LOG).read_text(encoding="utf-8")


def test_reasons_log_keeps_one_entry_per_document_in_path_order(repo: Path) -> None:
    _commit(repo, {"src/a.py": "a = 1\n"}, "code")
    _commit(repo, {"docs/b.md": _doc("unset", "src/**"), "docs/a.md": _doc("unset", "src/**")}, "d")
    fs_stale.verify(repo, ["docs/b.md", "docs/a.md"])
    _commit(repo, {}, "stamp")
    for reason in ("first reason for both", "second reason for both"):
        _commit(repo, {"src/a.py": f"a = '{reason}'\n"}, "change")
        fs_stale.verify(repo, ["docs/b.md", "docs/a.md"], reason=reason)
        _commit(repo, {}, "stamp")
    log = (repo / fs_stale.REASONS_LOG).read_text(encoding="utf-8")
    assert "first reason" not in log and log.count("second reason for both") == 2
    assert log.index("docs/a.md") < log.index("docs/b.md")
    assert "\n\ndocs/b.md\n" in log


def test_source_globs_match_exactly_what_git_matches() -> None:
    tracked = [p for p in fs_stale.git(ROOT, "ls-files", "-z").split("\0") if p]
    patterns = {
        pattern for meta in fs_stale.living_documents(ROOT).values() for pattern in meta["sources"]
    }
    assert patterns
    for pattern in sorted(patterns):
        ours = [p for p in tracked if fs_stale.glob_regex(pattern).fullmatch(p)]
        assert ours == sorted(fs_stale.tracked_matches(ROOT, pattern)), pattern


def test_two_branches_that_change_one_documents_sources_conflict_on_merge(repo: Path) -> None:
    _fresh(repo)
    for branch, files in (("one", {"src/a.py": "a = 2\n"}), ("two", {"src/b.py": "b = 2\n"})):
        _git(repo, "checkout", "-q", "-b", branch, "main")
        _write(repo, files)
        fs_stale.verify(repo, ["docs/a.md"], reason=f"re-read on branch {branch}")
        _commit(repo, {}, branch)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "one", "one")
    merge = subprocess.run(
        ["git", "-C", str(repo), "merge", "--no-ff", "-m", "two", "two"], capture_output=True
    )
    assert merge.returncode != 0
    assert "<<<<<<<" in (repo / "docs/a.md").read_text(encoding="utf-8")
    # Keeping either side's stamp does not hide it: neither names the merged sources.
    _git(repo, "checkout", "--theirs", "docs/a.md")
    assert fs_stale.stale(repo)[0].stale
    # The stamp written while resolving the merge is the one later changes are measured from.
    fs_stale.verify(repo, ["docs/a.md"], reason="re-read against both merged sources")
    _commit(repo, {}, "merge two")
    _commit(repo, {"src/c.py": "c = 1\n"}, "new source")
    with pytest.raises(ValueError, match=r"sources changed: src/c\.py \(\+1 -0\)$"):
        fs_stale.verify(repo, ["docs/a.md"])


def test_cli_exit_codes_json_owners_and_verify(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh(repo)
    root = ["--root", str(repo)]
    assert fs.main([*root, "stale", "--strict"]) == 0
    _commit(repo, {"src/a.py": "a = 2\n"}, "change")
    assert fs.main([*root, "stale"]) == 0
    assert fs.main([*root, "stale", "--strict"]) == 1
    capsys.readouterr()
    assert fs.main([*root, "stale", "--format", "json"]) == 0
    [payload] = json.loads(capsys.readouterr().out)
    assert payload["path"] == "docs/a.md" and payload["stale"] and payload["files"] == ["src/a.py"]
    assert fs.main([*root, "owners", "src/a.py", str(repo / "src/b.py"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "src/a.py": ["docs/a.md"],
        "src/b.py": ["docs/a.md"],
    }
    assert fs.main([*root, "verify", "docs/a.md"]) == 2
    err = capsys.readouterr().err
    assert "src/a.py (+1 -1)" in err and "--reason" in err
    reason = ["--reason", "re-read; it states nothing about a"]
    assert fs.main([*root, "verify", "docs/a.md", *reason]) == 0
    out = capsys.readouterr().out
    assert "verified docs/a.md" in out and "  - source changed: src/a.py (+1 -1)" in out
    assert fs.main([*root, "verify", "docs/a.md"]) == 0
    assert "already current docs/a.md" in capsys.readouterr().out
    assert fs.main([*root, "stale", "--strict"]) == 0
    assert fs.main([*root, "verify", "src/a.py"]) == 2
    _commit(repo, {"docs/bad.md": _doc("unset", "missing/**")}, "bad doc")
    assert fs.main([*root, "stale"]) == 1


def test_conflict_marked_front_matter_is_reported_and_fails_the_run(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _fresh(repo)
    conflicted = (
        "---\nowner: data layer\nsources:\n  - src/**\n"
        "<<<<<<< HEAD\nverified: aaaaaaaaaaaaaaaa\n=======\nverified: bbbbbbbbbbbbbbbb\n"
        ">>>>>>> main\n---\n\n# Doc\n"
    )
    _commit(repo, {"docs/broken.md": conflicted}, "conflicted")
    reports = fs_stale.stale(repo)
    broken = next(r for r in reports if r.path == "docs/broken.md")
    assert any(p.startswith("unreadable front matter: line") for p in broken.problems)
    assert "merge conflict markers" in broken.problems
    assert fs.main(["--root", str(repo), "stale"]) == 1
    out = capsys.readouterr().out
    assert "2 living documents checked; 0 stale; 1 with problems" in out
    assert "PROBLEM docs/broken.md" in out and "unreadable front matter" in out


def test_marker_lines_in_a_readable_living_document_are_reported(repo: Path) -> None:
    _fresh(repo)
    text = (repo / "docs/a.md").read_text(encoding="utf-8")
    _commit(repo, {"docs/a.md": text + "<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> main\n"}, "markers")
    [report] = fs_stale.stale(repo)
    assert report.problems == ["merge conflict markers"]


def test_foreign_yaml_is_skipped_and_a_clean_repo_is_unchanged(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _fresh(repo)
    foreign = "---\ntitle: [unclosed\n<<<<<<< HEAD\nname: x\n---\n\n# Other tool\n"
    _commit(repo, {"docs/foreign.md": foreign}, "foreign yaml")
    assert [r.path for r in fs_stale.stale(repo)] == ["docs/a.md"]
    assert fs.main(["--root", str(repo), "stale"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "1 living documents checked; 0 stale; 0 with problems; 0 cannot be checked"
    ]
