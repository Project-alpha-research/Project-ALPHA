"""`alpha library search` looks through the shipped seed ideas and the kept papers offline by
default; the network search needs `--online`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from alpha_cli import library_papers_cmds
from alpha_cli.main import app
from alpha_cli.spine import papers


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def worker(argv: list[str], **_: Any) -> dict[str, object]:
        calls.append(argv)
        return {"candidates": [], "receipt": {}}

    monkeypatch.setattr(library_papers_cmds, "_run_literature_worker", worker)
    return calls


def _cli(home: Path, *args: str) -> tuple[int, str]:
    result = CliRunner().invoke(app, list(args), env={"ALPHA_DATA_DIR": str(home)})
    return result.exit_code, result.output


def test_offline_search_finds_seed_ideas_and_kept_papers_without_the_network(
    tmp_path: Path, no_network: list[list[str]]
) -> None:
    record = papers.make_record(
        identity=papers.paper_id("candidate", "lc_" + "c" * 64),
        state="candidate",
        facts={"title": "Coin momentum after halvings", "source": "openalex"},
    )
    papers.save(tmp_path, record)
    code, text = _cli(tmp_path, "library", "search", "crypto momentum", "--json")
    assert code == 0, text
    found = json.loads(text)
    assert "crypto-momentum" in [r["id"] for r in found["records"]]
    assert found["papers"] == []  # "crypto" is not in the paper's title
    code, text = _cli(tmp_path, "library", "search", "MOMENTUM", "--json")
    hits = json.loads(text)
    assert record["paper_id"] in [p["paper_id"] for p in hits["papers"]]
    assert "crypto-momentum" in [r["id"] for r in hits["records"]]
    code, plain = _cli(tmp_path, "library", "search", "momentum")
    assert code == 0 and "crypto-momentum" in plain and "Searched offline" in plain
    assert no_network == []


def test_no_match_says_so_and_points_to_online(tmp_path: Path) -> None:
    code, text = _cli(tmp_path, "library", "search", "zzqx-nothing")
    assert code == 0
    assert "No seed idea or kept paper matches" in text and "--online" in text


def test_online_needs_an_email_and_calls_the_worker(
    tmp_path: Path, no_network: list[list[str]]
) -> None:
    code, text = _cli(tmp_path, "library", "search", "momentum", "--online")
    assert code == 1 and "--unpaywall-email" in text and no_network == []
    code, text = _cli(
        tmp_path, "library", "search", "momentum", "--online", "--unpaywall-email", "x@example.org"
    )
    assert code == 0, text
    assert no_network[0][:3] == ["discover", "--query", "momentum"]
