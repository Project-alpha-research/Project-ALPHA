"""Offline keyword search over the seed ideas the product ships and the papers kept here.

A record or paper matches when every search word appears in its words (case is ignored). Seed
ideas: the checked and imported library records, public and private (name, idea, mechanism, notes,
market and the imported facts as tags). Papers: title, authors, source and why a search kept it.
Nothing is fetched and nothing is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alpha_cli.spine import library, papers


def _words(text: str) -> list[str]:
    return text.lower().split()


def _record_text(record: library.Record) -> str:
    facts = record.imported
    tags = [facts.acronym, facts.category, facts.data_category] if facts else []
    return " ".join(
        [
            record.id.replace("-", " "),
            record.name,
            record.idea,
            record.mechanism_claimed,
            record.notes,
            record.market,
            record.holding_clock,
            *tags,
        ]
    ).lower()


def _paper_text(row: dict[str, Any]) -> str:
    parts = [row.get("title"), row.get("source"), row.get("relevance_explanation")]
    authors = row.get("authors")
    parts += authors if isinstance(authors, list) else []
    return " ".join(p for p in parts if isinstance(p, str)).lower()


def search(home: Path, words: str) -> dict[str, Any]:
    """Every seed idea and kept paper whose words hold all the search words."""
    wanted = _words(words)
    if not wanted:
        raise ValueError("give at least one word to look for")
    found, skipped = library.read(home, imported=True)
    records = [
        {
            "id": e.record.id,
            "name": e.record.name,
            "tier": e.record.tier,
            "market": e.record.market,
            "idea": e.record.idea,
            "origin": e.origin,
        }
        for e in found
        if all(w in _record_text(e.record) for w in wanted)
    ]
    rows, left_out = papers.all_papers(home)
    kept = [row for row in rows if all(w in _paper_text(row) for w in wanted)]
    return {
        "query": words,
        "records": records,
        "papers": kept,
        "left_out": {**{k: str(v) for k, v in skipped.items()}, **left_out},
    }


__all__ = ["search"]
