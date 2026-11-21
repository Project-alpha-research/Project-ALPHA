"""The words a setup study or trade prints: evidence, its place in the setup's family, and a
family-adjusted random-date figure when the stored records allow one.

It reads the ledger; it computes no new statistic (the adjustment is the validated
``benjamini_hochberg``) and changes no stored number, id or seed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from alpha_cli.spine.errors import SpineError
from alpha_cli.spine.reading import OLD_SETUP_OUTCOMES, SETUP_WORDS, TOO_LITTLE, setup_evidence_of
from alpha_cli.spine.trial_reader import LedgerSnapshot, spine_snapshot
from alpha_validation.proportion import benjamini_hochberg

NOUNS = {"setup_study": "study", "setup_trade": "trade"}
AREAS = {"setup_study": "setup-studies", "setup_trade": "setup-trades"}
# The family is the counted runs of one kind whose idea text matches after case and spacing; a
# variant saved under another idea text is outside it, so the adjustment can be too weak.
VARIANTS = "Variants saved under another idea text are not counted."
NOT_CORRECTED = (
    "This random-date p-value is not corrected for the number of setup variants tried, "
    "so it cannot read as clear of chance."
)


def family_context(
    home: Path,
    kind: str,
    idea: str,
    run_id: str,
    snapshot: LedgerSnapshot | None = None,
) -> dict[str, Any]:
    """This run's place among the counted runs of the same kind on the same setup idea.

    The adjusted figure needs the stored random-date p of every counted run in the family;
    with one missing it is None. Pass ``snapshot`` to read the ledger once for many runs.
    """
    snapshot = snapshot or spine_snapshot(home)
    family = "setup:" + " ".join(idea.casefold().split())
    raws = [
        snapshot.raw_rows[(r.source_file, r.source_line)]
        for r in snapshot.records
        if r.kind == kind and r.family_id == family and r.counts_for_deflation
    ]
    ids = [raw.get("run_id") for raw in raws]
    # A run missing from the counted rows has no place and no figure; never another run's p.
    position = ids.index(run_id) + 1 if run_id in ids else None
    values = [raw.get("random_date_p") for raw in raws]
    numbers = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    adjusted = own = None
    if position is not None:
        own = values[position - 1]
        if numbers and len(numbers) == len(values):  # every counted study has its stored p
            adjusted = float(benjamini_hochberg(numbers).qvalues[position - 1])
    return {
        "kind": kind,
        "family_id": family,
        "studies": len(raws),
        "position": position,
        "random_date_p": own,
        "adjusted_random_date_p": adjusted,
    }


def extras(home: Path, kind: str, summary: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Keys added to the command output: the evidence word, the old-wording flag, the family."""
    word, old = setup_evidence_of(summary)
    return {
        "evidence": word,
        "old_wording": old,
        "family": family_context(home, kind, summary["idea"], run_id),
    }


def owner_lines(output: dict[str, Any]) -> list[str]:
    """Printed lines after the stored sentence. No verdict word, no grade."""
    family, word = output["family"], output["evidence"]
    noun = NOUNS[family["kind"]]
    head = f"Evidence strength: {word}."
    if word != TOO_LITTLE:
        head += " " + NOT_CORRECTED
    count, adjusted = family["studies"], family["adjusted_random_date_p"]
    if count is None:
        return [head, f"Setup {noun}: no ledger is recorded, so its family is not counted."]
    plural = noun if count == 1 else f"{noun}s" if noun == "trade" else "studies"
    place = (
        f"Setup {noun} {family['position']} of {count} recorded for this idea."
        if family["position"] is not None
        else f"Setup {noun}: not among the {count} {plural} recorded for this idea."
    )
    lines = [head, place]
    if adjusted is None:
        lines.append(f"Random-date figure: not adjusted for the {count} {plural} recorded.")
    else:
        lines.append(
            f"Random-date figure adjusted for the {count} {plural} recorded for this idea "
            f"(false-discovery method): {adjusted:.2%} (unadjusted: {family['random_date_p']:.2%})."
        )
    lines.append(VARIANTS)
    if output.get("old_wording"):
        lines.append("Old record: the outcome word stored with it is not shown (old wording).")
    return lines


def _read_one(home: Path, run_id: str, snapshot: LedgerSnapshot | None) -> dict[str, Any]:
    unknown = SpineError(
        "UNKNOWN_SETUP_OUTCOME",
        f"No stored setup study or trade has the id {run_id}.",
        "Run alpha setup study or alpha setup trade on a recorded find, then use its id.",
    )
    if not re.fullmatch(r"[0-9a-f]{16}", run_id):
        raise unknown
    found = [
        (kind, home / area / run_id / "summary.json")
        for kind, area in AREAS.items()
        if (home / area / run_id / "summary.json").is_file()
    ]
    if not found:
        raise unknown
    kind, path = found[0]
    summary = json.loads(path.read_text())
    outcome = summary.get("outcome")
    if summary.get("evidence") in SETUP_WORDS or outcome in OLD_SETUP_OUTCOMES:
        word, old = setup_evidence_of(summary)
    else:
        word, old = None, isinstance(outcome, str)
    idea = summary.get("idea")
    family = None
    if isinstance(idea, str) and idea.strip():
        family = family_context(home, kind, idea, run_id, snapshot)
        if not (home / "ledger/trials.jsonl").is_file():
            # No ledger is not an empty ledger: the count of trials is not recorded.
            family |= {"studies": None, "position": None}
    return {"id": run_id, "kind": kind, "evidence": word, "old_wording": old, "family": family}


def stored_readings(home: Path, run_ids: list[str]) -> list[dict[str, Any]]:
    """The readings of stored studies or trades, in the order asked, reading the ledger once.

    A record with no readable word has ``evidence`` None; one with no idea text has no family.
    With no ledger file the family count and place are None; an empty ledger counts 0.
    """
    snapshot = spine_snapshot(home) if run_ids else None
    return [_read_one(home, run_id, snapshot) for run_id in run_ids]
