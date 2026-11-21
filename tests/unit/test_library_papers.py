"""`alpha library search / import-pdf / papers` and `alpha idea new --paper`. Offline only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import library_papers_cmds
from alpha_cli.main import app

RUNNER = CliRunner()
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
TEXT = "Synthetic page about momentum."
RECORDED_SEARCH: dict[str, Any] = {
    "candidates": [
        {
            "candidate_id": "lc_" + "a" * 64,
            "title": "Momentum in a synthetic market",
            "authors": ["A. Writer", "B. Author"],
            "year": 2001,
            "provider": "openalex",
            "doi": "10.0000/synthetic",
            "open_access_url": "https://arxiv.org/pdf/0000.00000",
            "relevance_explanation": "title shares: momentum",
        },
        {"candidate_id": "lc_" + "b" * 64, "title": "No year here", "provider": "crossref"},
    ],
    "receipt": {"schema": "LiteratureDiscoveryReceiptV1"},
}


def _extraction(digest: str) -> dict[str, object]:
    page = {
        "page": 1,
        "text": TEXT,
        "character_count": len(TEXT),
        "text_sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
    }
    core: dict[str, object] = {
        "schema": "ResearchDocumentTextV1",
        "source_sha256": digest,
        "parser": "pypdf",
        "parser_version": "synthetic",
        "config_hash": hashlib.sha256(b"cfg").hexdigest(),
        "normalization": "NFC_LF_RSTRIP_V1",
        "status": "extracted",
        "pages": [page],
        "page_count": 1,
        "character_count": len(TEXT),
        "warnings": [],
        "trust_label": "UNTRUSTED_SOURCE",
    }
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {"extraction_id": "rx_" + hashlib.sha256(blob.encode()).hexdigest(), **core}


@pytest.fixture(autouse=True)
def offline_worker(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def worker(argv: list[str], *, timeout_seconds: int = 180) -> dict[str, object]:
        calls.append(argv)
        if argv[0] == "discover":
            return RECORDED_SEARCH
        assert argv[0] == "extract"
        return _extraction(argv[argv.index("--source-sha256") + 1])

    monkeypatch.setattr(library_papers_cmds, "_run_literature_worker", worker)
    return calls


def _cli(home: Path, *args: str) -> tuple[int, str]:
    result = RUNNER.invoke(app, list(args), env={"ALPHA_DATA_DIR": str(home)})
    return result.exit_code, result.stdout


def _facts(home: Path, *args: str) -> dict[str, Any]:
    code, out = _cli(home, *args, "--json")
    assert code == 0, out
    parsed: dict[str, Any] = json.loads(out)
    return parsed


def _pdf(tmp_path: Path) -> Path:
    path = tmp_path / "paper.pdf"
    path.write_bytes(PDF)
    return path


def test_search_keeps_papers_needs_no_project_and_lists_them(
    tmp_path: Path, offline_worker: list[list[str]]
) -> None:
    first = _facts(tmp_path, "library", "search", "momentum", "--unpaywall-email", "x@example.org")
    assert offline_worker[0][:3] == ["discover", "--query", "momentum"]
    assert [p["state"] for p in first["papers"]] == ["candidate", "candidate"]
    listed = _facts(tmp_path, "library", "papers")["papers"]
    assert len(listed) == 2
    again = _facts(tmp_path, "library", "search", "momentum", "--unpaywall-email", "x@example.org")
    assert len(_facts(tmp_path, "library", "papers")["papers"]) == 2
    assert again["papers"] == first["papers"]


def test_a_missing_value_is_null_with_a_reason_never_zero(tmp_path: Path) -> None:
    _facts(tmp_path, "library", "search", "momentum", "--unpaywall-email", "x@example.org")
    by_title = {p["title"]: p for p in _facts(tmp_path, "library", "papers")["papers"]}
    bare = by_title["No year here"]
    assert bare["year"] is None and bare["authors"] is None
    assert {"year", "authors", "doi", "url", "file_sha256", "text"} <= set(bare["not_stated"])
    code, text = _cli(tmp_path, "library", "papers")
    assert code == 0 and "year not stated" in text and "authors not stated" in text


def test_import_pdf_keeps_hash_text_place_and_one_record_for_one_file(tmp_path: Path) -> None:
    home = tmp_path / "home"
    args = [
        "library",
        "import-pdf",
        str(_pdf(tmp_path)),
        "--title",
        "Momentum",
        "--author",
        "A. W.",
    ]
    first = _facts(home, *args, "--year", "2001")
    second = _facts(home, *args, "--year", "2001")
    paper = first["paper"]
    assert first["created"] is True and second["created"] is False
    assert second["paper"]["paper_id"] == paper["paper_id"]
    assert paper["file_sha256"] == hashlib.sha256(PDF).hexdigest()
    assert (paper["title"], paper["authors"], paper["year"]) == ("Momentum", ["A. W."], 2001)
    assert paper["source"] == "owner-provided PDF"
    assert (home / paper["text"]["path"]).is_file()
    assert len(_facts(home, "library", "papers")["papers"]) == 1


def test_import_pdf_without_title_says_not_stated_and_bad_file_fails_loud(tmp_path: Path) -> None:
    paper = _facts(tmp_path, "library", "import-pdf", str(_pdf(tmp_path)))["paper"]
    assert paper["title"] is None and "title" in paper["not_stated"]
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"not a pdf at all")
    code, out = _cli(tmp_path, "library", "import-pdf", str(junk))
    assert code == 1 and "not a PDF" in out


def test_a_paper_links_to_an_idea_card_and_shows_in_the_idea_file(tmp_path: Path) -> None:
    paper = _facts(tmp_path, "library", "import-pdf", str(_pdf(tmp_path)), "--title", "T")["paper"]
    card = _facts(
        tmp_path, "idea", "new", "--claim", "momentum persists", "--paper", paper["paper_id"]
    )
    assert [p["paper_id"] for p in card["papers"]] == [paper["paper_id"]]
    file_facts = _facts(tmp_path, "idea", "file", card["id"])
    assert [p["paper_id"] for p in file_facts["papers"]] == [paper["paper_id"]]
    assert file_facts["counts"]["tests_linked"] == 0 and file_facts["readings"] == []
    code, text = _cli(tmp_path, "idea", "file", card["id"])
    assert code == 0 and "not evidence" in text and paper["paper_id"] in text
    # the same card with a second paper later: the card id does not change
    other = _facts(tmp_path, "library", "search", "x", "--unpaywall-email", "x@example.org")
    extra = other["papers"][0]["paper_id"]
    again = _facts(tmp_path, "idea", "new", "--claim", "momentum persists", "--paper", extra)
    assert again["id"] == card["id"] and again["created"] is False
    assert len(_facts(tmp_path, "idea", "file", card["id"])["papers"]) == 2


def test_unknown_paper_writes_no_card(tmp_path: Path) -> None:
    code, _ = _cli(tmp_path, "idea", "new", "--claim", "c", "--paper", "deadbeef")
    assert code == 1
    assert not (tmp_path / "ideas").exists()


def test_old_commands_name_the_new_ones(tmp_path: Path) -> None:
    env = {"ALPHA_DATA_DIR": str(tmp_path)}
    pdf = ["research", "import-pdf", "p1", "--file", str(_pdf(tmp_path)), "--title", "T"]
    assert "alpha library import-pdf" in RUNNER.invoke(app, pdf, env=env).output
    find = ["research", "sources", "discover", "p1", "--query", "q", "--unpaywall-email", "e@x.org"]
    assert "alpha library search" in RUNNER.invoke(app, find, env=env).output
