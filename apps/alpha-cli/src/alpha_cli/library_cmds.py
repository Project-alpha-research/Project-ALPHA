"""`alpha library`: read the library of published ideas and turn one into an idea card."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from alpha_cli._cli_json import emit
from alpha_cli.spine import library, library_import
from alpha_cli.spine.errors import SpineError, fail
from alpha_core.config import AlphaSettings

library_app = typer.Typer(help="Browse published ideas and turn one into an idea card.")
JSON = Annotated[bool, typer.Option("--json", help="Print the same facts as JSON.")]
MAP_LINE = "A starting map, not a claim. Nothing here says an idea makes money."


def _row(entry: library.Entry) -> dict[str, object]:
    record = entry.record
    return {
        "id": record.id,
        "tier": record.tier,
        "name": record.name,
        "market": record.market,
        "year_published": record.year_published,
        "direction": record.direction,
        "holding_clock": record.holding_clock,
        "can_test_today": record.can_test_today.split(" ")[0],
        "origin": entry.origin,
    }


@library_app.command("list")
def list_records(
    market: Annotated[str, typer.Option(help="One of: us-equities, crypto, futures, multi.")] = "",
    tier: Annotated[str, typer.Option(help="checked (default), imported or all.")] = "checked",
    json_out: JSON = False,
) -> None:
    """List the records. Add `--market` or `--tier` to change what is shown."""
    home = AlphaSettings().data_dir
    try:
        if market and market not in library.MARKETS:
            raise SpineError(
                "LIBRARY_MARKET",
                f"{market!r} is not a market in the library.",
                "Use one of: " + ", ".join(library.MARKETS) + ".",
            )
        if tier not in (*library.TIERS, "all"):
            raise SpineError(
                "LIBRARY_TIER",
                f"{tier!r} is not a tier in the library.",
                "Use one of: checked, imported, all.",
            )
        records, skipped = library.read(home, imported=True)
        counts = {t: sum(1 for e in records if e.record.tier == t) for t in library.TIERS}
        found = [
            e
            for e in records
            if (not market or e.record.market == market) and tier in ("all", e.record.tier)
        ]
    except SpineError as exc:
        fail(exc, json_out)
    rows = [_row(e) for e in found]
    left_out = {name: str(exc) for name, exc in skipped.items()}
    lines = [
        f"{len(rows)} library record(s) shown ({tier}). {MAP_LINE}",
        f"Tiers: {counts['checked']} checked, {counts['imported']} imported. "
        "Imported records hold facts only; checked ones are hand-verified.",
    ]
    lines += [f"Left out: {message}" for message in left_out.values()]
    lines += [
        f"  {r['id']}  {r['name']} ({r['year_published']}, {r['market']}, "
        f"{r['direction']}, {r['holding_clock']}; test today: {r['can_test_today']}; "
        f"tier: {r['tier']})" + ("  [private]" if r["origin"] == "private" else "")
        for r in rows
    ]
    emit(
        {"records": rows, "counts": counts, "left_out": left_out},
        json_out=json_out,
        fallback="\n".join(lines),
    )


def _show_text(entry: library.Entry, made: list[dict[str, str | int]]) -> str:
    r = entry.record
    s = r.source
    lines = [
        f"{r.name} ({r.id})" + ("  [private]" if entry.origin == "private" else ""),
        f"  Source: {s.authors} ({s.year}), {s.title}, {s.venue}. {s.url}",
        f"  Market: {r.market}. Direction: {r.direction}. Holding clock: {r.holding_clock}.",
        f"  Idea: {r.idea}",
        f"  Why it is said to work: {r.mechanism_claimed}",
        f"  Data needed: {', '.join(r.data_needed)}",
        f"  Decay evidence: {r.decay_evidence}",
        f"  Can test today: {r.can_test_today}",
    ]
    if r.imported:
        i = r.imported
        sign = {1: "+1 (long high)", -1: "-1 (long low)"}.get(i.predicted_sign or 0, "not stated")
        lines.append(
            f"  Imported facts ({r.tier}): {i.project}, release {i.release}; id {i.source_id}, "
            f"acronym {i.acronym}; category {i.category}; data {i.data_category}; "
            f"predicted sign {sign}; sample {i.sample_start}-{i.sample_end}."
        )
    if r.notes:
        lines.append(f"  Notes: {r.notes}")
    if made:
        lines.append("Idea cards made from this record:")
        lines += [f"  {m['card']}  {m['tests']} test(s) linked" for m in made]
    else:
        lines.append("No idea card was made from this record yet.")
    lines.append(f"Make one: alpha library card {r.id}")
    return "\n".join(lines)


@library_app.command("show")
def show(
    record_id: Annotated[str, typer.Argument(help="Record id from `alpha library list`.")],
    json_out: JSON = False,
) -> None:
    """Print one record and the idea cards already made from it."""
    home = AlphaSettings().data_dir
    try:
        entry = library.find(home, record_id)
    except SpineError as exc:
        fail(exc, json_out)
    made = library.cards_from(home, entry.record.id)
    facts = {**entry.record.model_dump(), "origin": entry.origin, "cards": made}
    emit(facts, json_out=json_out, fallback=_show_text(entry, made))


@library_app.command("card")
def card(
    record_id: Annotated[str, typer.Argument(help="Record id from `alpha library list`.")],
    json_out: JSON = False,
) -> None:
    """Make an idea card from a record. Nothing is tested; no ledger row is written."""
    home = AlphaSettings().data_dir
    try:
        entry = library.find(home, record_id)
        identity, created = library.create_card(home, entry.record)
    except SpineError as exc:
        fail(exc, json_out)
    word = "saved" if created else "already saved"
    emit(
        {"card": identity, "created": created, "record": entry.record.id},
        json_out=json_out,
        fallback=f"Idea card {identity} {word}, {library.provenance(entry.record)}.\n"
        "Fill in what would disprove it and the baseline. Nothing was tested.\n"
        f"Read it: alpha idea show {identity}",
    )


@library_app.command("import-catalogue")
def import_catalogue(
    source: Annotated[str, typer.Argument(help="The catalogue: osap.")],
    from_file: Annotated[Path, typer.Option("--from", help="Local SignalDoc.csv.")],
    release: Annotated[str, typer.Option(help="The release it came from, e.g. 2026.10.")],
    into: Annotated[str, typer.Option(help="home (default, never in git) or repo.")] = "home",
    json_out: JSON = False,
) -> None:
    """Turn a published signal table into facts-only `imported` records. Nothing is tested."""
    home = AlphaSettings().data_dir
    try:
        if source not in library_import.SOURCES or into not in ("home", "repo"):
            raise SpineError(
                "LIBRARY_IMPORT_ARGS",
                f"Cannot import {source!r} into {into!r}.",
                "Use the source osap, and --into home or --into repo.",
            )
        try:
            raw = from_file.read_bytes()
        except OSError as exc:
            raise SpineError(
                "LIBRARY_CATALOGUE_INVALID",
                f"Cannot read {from_file}: {exc.strerror}.",
                "Fetch SignalDoc.csv first; see research/library/README.md.",
            ) from exc
        dest = library.IMPORTED_DIR if into == "repo" else home / "library" / "imported"
        report = library_import.import_osap(raw, release=release, dest=dest)
    except SpineError as exc:
        fail(exc, json_out)
    emit(
        report.model_dump(mode="json"),
        json_out=json_out,
        fallback=f"{report.written} record(s) written to {report.folder} (tier imported, "
        f"release {release}); {report.not_predictors} not predictors, left out; "
        f"{report.removed} stale record(s) removed.\nFacts only. Read the paper for the idea.",
    )
