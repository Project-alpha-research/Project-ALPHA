"""The paper shelf of `alpha library`: papers found by search or imported from a PDF.

One paper is one small JSON file under `<home>/library/papers/`. A paper is a source for ideas
only. It is never a test, a result or an approval. A paper links to an idea card through a line in
`<home>/library/paper-links.jsonl`; the link is kept out of the card's identity. A value that is
not known is stored as null and named in `not_stated`; it is never shown as a real value.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from alpha_cli.spine.errors import SpineError

LINKS_FILE = "paper-links.jsonl"
FIELDS = ("title", "authors", "year", "source", "doi", "url")
STATES = ("candidate", "imported")
_ID_LENGTH = 12


def _folder(home: Path) -> Path:
    return home / "library" / "papers"


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(f".{os.getpid()}.part")
    staged.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    os.replace(staged, path)


def paper_id(kind: str, key: str) -> str:
    """The id comes from the file hash (imported) or the search candidate id (candidate)."""
    return hashlib.sha256(f"{kind}:{key}".encode()).hexdigest()[:_ID_LENGTH]


def make_record(
    *,
    identity: str,
    state: str,
    facts: dict[str, Any],
    file_sha256: str | None = None,
    text: dict[str, Any] | None = None,
    retracted: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean = {name: facts.get(name) or None for name in FIELDS}
    return {
        "paper_id": identity,
        "state": state,
        **clean,
        "retracted": retracted,
        "file_sha256": file_sha256,
        "text": text,
        "not_stated": [
            name
            for name in (*FIELDS, "retracted", "file_sha256", "text")
            if _blank(name, clean, file_sha256, text, retracted)
        ],
        "trust_label": "UNTRUSTED_SOURCE",
        "use": "A source for ideas only. Not evidence, not a test, not an approval.",
        **(extra or {}),
    }


def _blank(
    name: str, facts: dict[str, Any], file_sha256: str | None, text: Any, retracted: bool | None
) -> bool:
    if name == "retracted":
        return retracted is None  # not stated by the provider; never read as "not retracted"
    if name == "file_sha256":
        return file_sha256 is None
    if name == "text":
        return text is None
    return facts[name] is None


def save(home: Path, record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Store a paper. The same paper twice gives one record; imported is never downgraded."""
    path = _folder(home) / f"{record['paper_id']}.json"
    if path.is_file():
        stored = load(home, record["paper_id"])
        if stored["state"] == "imported" or record["state"] == "candidate":
            return stored, False
    _write_once(path, record)
    return record, True


def save_text(home: Path, extraction: dict[str, Any]) -> str:
    """Keep the extracted text file; return its place relative to the data home."""
    name = f"{extraction['extraction_id']}.json"
    path = _folder(home) / "text" / name
    if not path.is_file():
        _write_once(path, extraction)
    return f"library/papers/text/{name}"


def load(home: Path, wanted: str) -> dict[str, Any]:
    wanted = wanted.strip().lower()
    found = sorted(p for p in _folder(home).glob("*.json") if p.stem.startswith(wanted))
    if len(wanted) < 4 or len(found) != 1:
        raise SpineError(
            "PAPER_UNKNOWN" if len(found) != 1 else "PAPER_ID",
            f"There is no single paper with the id {wanted!r}.",
            "Run `alpha library papers` to see the paper ids.",
        )
    try:
        record = json.loads(found[0].read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SpineError(
            "PAPER_UNREADABLE",
            f"The paper file {found[0].name} cannot be read: {exc}",
            "Do not edit paper files. Import the paper again.",
        ) from exc
    if not isinstance(record, dict) or record.get("paper_id") != found[0].stem:
        raise SpineError(
            "PAPER_CHANGED",
            f"The paper file {found[0].name} no longer matches its id.",
            "Do not edit paper files. Import the paper again.",
        )
    return record


def all_papers(home: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Every readable paper, and the files that could not be read with the reason."""
    rows: list[dict[str, Any]] = []
    left_out: dict[str, str] = {}
    for path in sorted(_folder(home).glob("*.json")):
        try:
            rows.append(load(home, path.stem))
        except SpineError as exc:
            left_out[path.name] = str(exc)
    return rows, left_out


def _links(home: Path) -> list[dict[str, str]]:
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


def link(home: Path, card: str, paper: str) -> None:
    """Note that a card draws on a paper. Both must exist; the card text is not changed."""
    row = {"card": card, "paper": load(home, paper)["paper_id"]}
    if row not in _links(home):
        path = home / "library" / LINKS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def papers_of(home: Path, card: str) -> list[dict[str, Any]]:
    """The papers linked to a card: facts only, never a verdict."""
    ids = sorted({row.get("paper", "") for row in _links(home) if row.get("card") == card})
    found: list[dict[str, Any]] = []
    for identity in ids:
        try:
            record = load(home, identity)
        except SpineError:
            found.append({"paper_id": identity, "readable": False})
            continue
        found.append(
            {
                **{k: record.get(k) for k in ("paper_id", "state", *FIELDS, "retracted")},
                "readable": True,
            }
        )
    return found
