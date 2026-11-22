"""`alpha library search`, `import-pdf` and `papers`: the paper shelf. No project, no case."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated, Any

import typer

from alpha_cli._cli_json import emit
from alpha_cli.library_cmds import JSON, library_app
from alpha_cli.local_pdf_cmds import _read_owner_pdf, _validated_extraction
from alpha_cli.research_cmds import _run_literature_worker
from alpha_cli.spine import papers
from alpha_cli.spine.errors import SpineError, fail
from alpha_core import DataError
from alpha_core.config import AlphaSettings

SOURCE_LINE = "A paper is a source for ideas only. It is not evidence, a test or an approval."


def _line(record: dict[str, Any]) -> str:
    authors = ", ".join(record["authors"]) if record["authors"] else "authors not stated"
    year = record["year"] if record["year"] is not None else "year not stated"
    title = record["title"] or "title not stated"
    source = record["source"] or "source not stated"
    flag = "  [RETRACTED]" if record.get("retracted") is True else ""
    return f"  {record['paper_id']}  {title} ({authors}; {year}; {source}; {record['state']}){flag}"


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _authors(value: object) -> list[str] | None:
    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        return list(value)
    return None


def _offline(words: str, json_out: bool) -> None:
    """The stored seed ideas and kept papers that hold every word. No network, nothing written."""
    from alpha_cli.spine.library_search import search as offline_search

    try:
        found = offline_search(AlphaSettings().data_dir, words)
    except (SpineError, ValueError) as exc:
        fail(
            exc
            if isinstance(exc, SpineError)
            else SpineError("LIBRARY_SEARCH", str(exc), "Give the words to look for."),
            json_out,
        )
    records, kept = found["records"], found["papers"]
    lines = [
        f"Searched offline: {len(records)} seed idea(s) and {len(kept)} kept paper(s) match "
        f"{words!r}. {SOURCE_LINE}",
        *(f"  {r['id']}  {r['name']} ({r['market']}; tier {r['tier']})" for r in records),
        *(_line(r) for r in kept),
    ]
    if not records and not kept:
        lines[0] = (
            f"No seed idea or kept paper matches {words!r}. To search the literature sources on "
            "the network: add --online --unpaywall-email <your contact>."
        )
    lines += [f"Left out: {name}: {why}" for name, why in found["left_out"].items()]
    emit(found, json_out=json_out, fallback="\n".join(lines))


@library_app.command("search")
def search(
    words: Annotated[str, typer.Argument(help="What to look for, in plain words.")],
    online: Annotated[
        bool,
        typer.Option(
            "--online", help="Search the literature sources on the network and keep the hits."
        ),
    ] = False,
    unpaywall_email: Annotated[
        str | None,
        typer.Option("--unpaywall-email", help="Contact for Unpaywall (with --online only)."),
    ] = None,
    max_candidates: Annotated[int, typer.Option(min=1, max=20)] = 20,
    json_out: JSON = False,
) -> None:
    """Search the shipped seed ideas and the kept papers offline. Nothing is tested.

    With --online, search the literature sources on the network and keep the hits as papers."""
    if not online:
        _offline(words, json_out)
        return
    if not unpaywall_email:
        fail(
            SpineError(
                "LIBRARY_SEARCH",
                "The online search needs a contact address for Unpaywall.",
                "Add --unpaywall-email <your contact>, or leave out --online to search offline.",
            ),
            json_out,
        )
    home = AlphaSettings().data_dir
    try:
        artifact = _run_literature_worker(
            [
                "discover",
                "--query",
                words,
                "--email",
                unpaywall_email,
                "--max-candidates",
                str(max_candidates),
                "--max-full-texts",
                "0",
            ]
        )
        found = artifact.get("candidates")
        if not isinstance(found, list):
            raise DataError("literature worker returned no candidate list")
        kept = []
        for candidate in found:
            if not isinstance(candidate, dict) or not isinstance(
                candidate.get("candidate_id"), str
            ):
                raise DataError("literature worker returned a candidate without an id")
            found_retracted = candidate.get("retracted")
            record = papers.make_record(
                identity=papers.paper_id("candidate", candidate["candidate_id"]),
                state="candidate",
                facts={
                    "title": candidate.get("title")
                    if isinstance(candidate.get("title"), str)
                    else None,
                    "authors": _authors(candidate.get("authors")),
                    "year": _int_or_none(candidate.get("year")),
                    "source": candidate.get("provider"),
                    "doi": candidate.get("doi"),
                    "url": candidate.get("open_access_url"),
                },
                retracted=found_retracted if isinstance(found_retracted, bool) else None,
                extra={"relevance_explanation": candidate.get("relevance_explanation")},
            )
            stored = papers.save(home, record)[0]
            # The stored paper is kept once; the reason it matched belongs to this search.
            kept.append({**stored, "relevance_explanation": record["relevance_explanation"]})
    except (DataError, SpineError) as exc:
        fail(
            SpineError("LIBRARY_SEARCH", str(exc), "Check the words and the network, then retry."),
            json_out,
        )
    emit(
        {"query": words, "papers": kept, "receipt": artifact.get("receipt", {})},
        json_out=json_out,
        fallback="\n".join(
            [f"{len(kept)} paper(s) found and kept. {SOURCE_LINE}", *(_line(r) for r in kept)]
        ),
    )


@library_app.command("import-pdf")
def import_pdf(
    file_path: Annotated[Path, typer.Argument(help="One local PDF.", metavar="FILE")],
    title: Annotated[str, typer.Option(help="The title; if empty it stays not stated.")] = "",
    author: Annotated[list[str] | None, typer.Option(help="An author; repeat for more.")] = None,
    year: Annotated[int | None, typer.Option(help="Year published.")] = None,
    json_out: JSON = False,
) -> None:
    """Keep the text of one PDF as a paper. The same file twice gives one paper."""
    home = AlphaSettings().data_dir
    try:
        raw, digest = _read_owner_pdf(file_path)
        identity = papers.paper_id("pdf", digest)
        with tempfile.TemporaryDirectory(prefix="alpha-library-pdf-") as scratch:
            staged = Path(scratch) / "paper.pdf"
            staged.write_bytes(raw)
            extraction = _validated_extraction(
                _run_literature_worker(
                    [
                        "extract",
                        "--object-path",
                        str(staged),
                        "--source-sha256",
                        digest,
                        "--extractions-dir",
                        str(Path(scratch) / "extractions"),
                    ]
                ),
                source_sha256=digest,
            )
        where = papers.save_text(home, extraction)
        record = papers.make_record(
            identity=identity,
            state="imported",
            facts={
                "title": " ".join(title.split()),
                "authors": author or None,
                "year": year,
                "source": "owner-provided PDF",
            },
            file_sha256=digest,
            text={
                "path": where,
                "extraction_id": extraction["extraction_id"],
                "pages": extraction["page_count"],
                "characters": extraction["character_count"],
            },
        )
        stored, created = papers.save(home, record)
    except (DataError, SpineError) as exc:
        fail(SpineError("LIBRARY_IMPORT_PDF", str(exc), "Check the file and retry."), json_out)
    word = "saved" if created else "already saved"
    emit(
        {"paper": stored, "created": created},
        json_out=json_out,
        fallback=f"Paper {stored['paper_id']} {word}. {SOURCE_LINE}\n"
        f"Text: {stored['text']['path']}",
    )


@library_app.command("papers")
def list_papers(json_out: JSON = False) -> None:
    """List the papers kept from searches and PDF imports."""
    home = AlphaSettings().data_dir
    rows, left_out = papers.all_papers(home)
    lines = [f"{len(rows)} paper(s). {SOURCE_LINE}", *(_line(r) for r in rows)]
    lines += [f"Left out: {name}: {why}" for name, why in left_out.items()]
    emit({"papers": rows, "left_out": left_out}, json_out=json_out, fallback="\n".join(lines))
