"""Owner-invoked, local-only PDF import for literature sources."""

from __future__ import annotations

import sqlite3
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

import typer

from alpha_cli._cli_json import emit as _emit
from alpha_cli.control_store import ControlStore
from alpha_cli.literature_call import (
    _read_owner_pdf,
    _run_literature_worker,
    _validated_extraction,
)
from alpha_cli.research_cmds import _store
from alpha_core import DataError

_Worker = Callable[[list[str]], dict[str, object]]


def _document_summary(document: dict[str, object]) -> dict[str, object]:
    return {
        key: document.get(key)
        for key in (
            "extraction_id",
            "source_sha256",
            "status",
            "page_count",
            "character_count",
            "parser_version",
        )
    }


def _import_result(
    source: dict[str, object],
    document: dict[str, object],
    *,
    byte_count: int,
    source_sha256: str,
    original_pdf_artifact: dict[str, object],
    idempotent_reuse: bool = False,
) -> dict[str, object]:
    acquisition: dict[str, object] = {
        "origin_kind": "owner_provided_local_pdf",
        "byte_count": byte_count,
        "sha256": source_sha256,
        "trust_label": "UNTRUSTED_SOURCE",
        "page_text_state": "extracted",
    }
    if idempotent_reuse:
        acquisition["idempotent_reuse"] = True
    return {
        "source": source,
        "document": _document_summary(document),
        "acquisition": acquisition,
        "original_pdf_artifact": original_pdf_artifact,
    }


def import_owner_pdf_file(
    store: ControlStore,
    *,
    project_id: str,
    file_path: Path,
    title: str,
    worker: _Worker,
) -> dict[str, object]:
    """Import a selected PDF without network access or authority from document text."""
    clean_title = title.strip()
    if not clean_title or len(clean_title) > 500 or "\x00" in clean_title:
        raise DataError("owner-provided PDF title must contain bounded text")
    # This bounded read-only projection checks project ownership before opening the file.
    store.list_research_sources(project_id, limit=1)
    raw, source_sha256 = _read_owner_pdf(file_path)

    with tempfile.TemporaryDirectory(prefix="alpha-owner-pdf-") as temporary_root:
        temporary = Path(temporary_root)
        staged_pdf = temporary / "owner-source.pdf"
        staged_pdf.write_bytes(raw)
        extraction = worker(
            [
                "extract",
                "--object-path",
                str(staged_pdf),
                "--source-sha256",
                source_sha256,
                "--extractions-dir",
                str(temporary / "extractions"),
            ]
        )
        artifact = _validated_extraction(extraction, source_sha256=source_sha256)

    extraction_id = cast(str, artifact["extraction_id"])
    try:
        existing_document = store.get_research_document_text(extraction_id)
    except DataError as exc:
        if str(exc) != f"unknown research extraction {extraction_id!r}":
            raise
        existing_document = None
    if existing_document is not None:
        existing_source_id = existing_document.get("source_id")
        if not isinstance(existing_source_id, str):
            raise DataError("existing PDF extraction has no source binding")
        existing_source = store.get_research_source(existing_source_id)
        if existing_source.get("project_id") != project_id:
            raise DataError("owner PDF extraction is already bound to a different project")
        existing_metadata = existing_source.get("metadata")
        if (
            existing_source.get("content_hash") != source_sha256
            or existing_source.get("access_mode") != "owner_provided"
            or existing_source.get("title") != clean_title
            or existing_source.get("provider") != "owner"
            or existing_source.get("locator") != f"owner-provided:sha256:{source_sha256}"
            or not isinstance(existing_metadata, dict)
            or existing_metadata.get("origin_kind") != "owner_provided_local_pdf"
        ):
            raise DataError("owner PDF extraction is already bound to a different source record")
        original_pdf_artifact = store.retain_research_source_original_pdf(
            project_id, existing_source_id, raw
        )
        if original_pdf_artifact.get("status") != "available":
            raise DataError(
                "owner PDF extraction remains attached, but its original bytes are "
                f"{original_pdf_artifact.get('status')}; no replacement was made"
            )
        return _import_result(
            existing_source,
            existing_document,
            byte_count=len(raw),
            source_sha256=source_sha256,
            original_pdf_artifact=original_pdf_artifact,
            idempotent_reuse=True,
        )

    source = store.create_research_source(
        project_id,
        title=clean_title,
        locator=f"owner-provided:sha256:{source_sha256}",
        provider="owner",
        access_mode="owner_provided",
        metadata={
            "origin_kind": "owner_provided_local_pdf",
            "trust_label": "UNTRUSTED_SOURCE",
        },
        content_hash=source_sha256,
    )
    try:
        original_pdf_artifact = store.retain_research_source_original_pdf(
            project_id, str(source["source_id"]), raw
        )
        if original_pdf_artifact.get("status") != "available":
            raise DataError(
                "original PDF bytes are "
                f"{original_pdf_artifact.get('status')}; no bytes were reported as retained"
            )
        document = store.record_research_document_text(str(source["source_id"]), artifact=artifact)
    except (DataError, OSError, sqlite3.Error) as exc:
        raise DataError(
            f"recoverable partial owner PDF import: source {source['source_id']} was recorded, "
            "but original-byte retention or extracted text did not return a verified attachment. "
            "Check the source and extraction status before retrying with the same project, "
            "file, and title. "
            f"Cause: {exc}"
        ) from exc
    return _import_result(
        source,
        document,
        byte_count=len(raw),
        source_sha256=source_sha256,
        original_pdf_artifact=original_pdf_artifact,
    )


def import_pdf_command(
    project_id: str,
    file_path: Path = typer.Option(..., "--file", help="one owner-selected local PDF"),  # noqa: B008
    title: str = typer.Option(..., "--title"),
    json_out: bool = typer.Option(False, "--json", help="emit JSON"),
) -> None:
    """Import text from one owner-selected local PDF; no links are followed."""
    try:
        result = import_owner_pdf_file(
            _store(),
            project_id=project_id,
            file_path=file_path,
            title=title,
            worker=_run_literature_worker,
        )
    except DataError as exc:
        raise typer.BadParameter(str(exc)) from exc
    source = cast(dict[str, object], result["source"])
    _emit(
        result,
        json_out=json_out,
        fallback=f"imported owner-provided PDF source {source['source_id']}",
    )


__all__ = ["import_pdf_command", "import_owner_pdf_file"]
