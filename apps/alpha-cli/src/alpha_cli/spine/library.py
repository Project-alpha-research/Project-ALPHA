"""The library of published ideas: one small TOML record per idea, our own words, pointers only.

Public records live in git under `research/library/published/`. The owner's private records live in
`<home>/library/private/` and are never committed. A record is a starting map, not a claim. Making
an idea card from a record tests nothing and writes no ledger row.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from alpha_cli.spine import idea_card as cards
from alpha_cli.spine.errors import SpineError

PUBLIC_DIR = Path(__file__).resolve().parents[5] / "research" / "library" / "published"
MARKETS = ("us-equities", "crypto", "futures", "multi")
LINKS_FILE = "links.jsonl"
_ID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_VERDICTS = ("yes", "partly", "no")


class Source(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    authors: str
    year: int
    title: str
    venue: str
    url: str


class Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    source: Source
    year_published: int
    market: Literal["us-equities", "crypto", "futures", "multi"]
    idea: str
    mechanism_claimed: str
    data_needed: list[str]
    direction: Literal["long", "short", "long-short", "n-a"]
    holding_clock: str
    decay_evidence: str
    can_test_today: str
    notes: str = ""

    @field_validator("id")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not _ID.fullmatch(value):
            raise ValueError("id must be lower-case words joined by hyphens")
        return value

    @field_validator("can_test_today")
    @classmethod
    def _verdict(cls, value: str) -> str:
        if value.split(" ")[0] not in _VERDICTS:
            raise ValueError("can_test_today must start with yes, partly or no")
        return value


class Entry(BaseModel):
    model_config = ConfigDict(frozen=True)

    record: Record
    origin: Literal["public", "private"]


def load_record(path: Path) -> Record:
    """Read one record file. The file name must be the record id."""
    try:
        record = Record.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
        if record.id != path.stem:
            raise ValueError(f"id {record.id!r} must equal the file name {path.stem!r}")
    except (OSError, ValueError, ValidationError) as exc:
        raise SpineError(
            "LIBRARY_RECORD_INVALID",
            f"The library record {path.name} is not valid: {exc}",
            "Check it against research/library/README.md. Unknown keys are not allowed.",
        ) from exc
    return record


def read(home: Path, public_dir: Path = PUBLIC_DIR) -> tuple[list[Entry], dict[str, SpineError]]:
    """Public records, then the owner's private records, sorted by id.

    A private record that cannot be read is left out and returned by file name with its error, so
    one bad file never hides the others. A bad public record is a bug and raises.
    """
    found: dict[str, Entry] = {}
    skipped: dict[str, SpineError] = {}
    folders: list[tuple[Literal["public", "private"], Path]] = [
        ("public", public_dir),
        ("private", home / "library" / "private"),
    ]
    for origin, folder in folders:
        for path in sorted(folder.glob("*.toml")):
            try:
                record = load_record(path)
            except SpineError as exc:
                if origin == "public":
                    raise
                skipped[path.stem] = exc
                continue
            if record.id in found:
                raise SpineError(
                    "LIBRARY_ID_CLASH",
                    f"The library id {record.id!r} is used twice ({path}).",
                    "Rename the private record file and its id.",
                )
            found[record.id] = Entry(record=record, origin=origin)
    return [found[key] for key in sorted(found)], skipped


def entries(home: Path, public_dir: Path = PUBLIC_DIR) -> list[Entry]:
    return read(home, public_dir)[0]


def find(home: Path, wanted: str) -> Entry:
    found, skipped = read(home)
    key = wanted.strip().lower()
    for entry in found:
        if entry.record.id == key:
            return entry
    if key in skipped:
        raise skipped[key]
    raise SpineError(
        "LIBRARY_UNKNOWN",
        f"There is no library record with the id {wanted!r}.",
        "Run `alpha library list` to see the ids.",
    )


def provenance(record: Record) -> str:
    return f"from library record {record.id}, published {record.year_published}"


def make_card(record: Record) -> cards.IdeaCard:
    return cards.IdeaCard(
        claim=record.idea,
        mechanism=record.mechanism_claimed,
        held_for=record.holding_clock,
        source=provenance(record),
    )


def create_card(home: Path, record: Record) -> tuple[str, bool]:
    """Save the card and note which record it came from. Nothing is tested."""
    identity, created = cards.save(home, make_card(record))
    row = {"card": identity, "record": record.id}
    path = home / "library" / LINKS_FILE
    if row not in _link_rows(home):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    return identity, created


def _link_rows(home: Path) -> list[dict[str, str]]:
    try:
        lines = (home / "library" / LINKS_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return [row for row in rows if isinstance(row, dict)]


def cards_from(home: Path, record_id: str) -> list[dict[str, str | int]]:
    """Existing idea cards made from this record, each with its count of linked tests."""
    rows = _link_rows(home)
    ids = sorted({row.get("card", "") for row in rows if row.get("record") == record_id})
    stored = set(cards.all_ids(home))
    return [{"card": c, "tests": cards.linked_tests(home, c)} for c in ids if c in stored]
