"""The words a setup study or trade prints: evidence, its place in the setup's family, and a
family-adjusted random-date figure when the stored records allow one.

It reads the ledger; it computes no new statistic (the adjustment is the validated
``benjamini_hochberg``) and changes no stored number, id or seed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alpha_cli.spine.reading import TOO_LITTLE, setup_evidence_of
from alpha_cli.spine.trial_reader import spine_snapshot
from alpha_validation.proportion import benjamini_hochberg

NOUNS = {"setup_study": "study", "setup_trade": "trade"}
NOT_CORRECTED = (
    "This random-date p-value is not corrected for the number of setup variants tried, "
    "so it cannot read as clear of chance."
)


def family_context(home: Path, kind: str, idea: str, run_id: str) -> dict[str, Any]:
    """This run's place among the counted runs of the same kind on the same setup idea.

    The adjusted figure needs the stored random-date p of every counted run in the family;
    with one missing it is None.
    """
    snapshot = spine_snapshot(home)
    family = "setup:" + " ".join(idea.casefold().split())
    raws = [
        snapshot.raw_rows[(r.source_file, r.source_line)]
        for r in snapshot.records
        if r.kind == kind and r.family_id == family and r.counts_for_deflation
    ]
    ids = [raw.get("run_id") for raw in raws]
    position = ids.index(run_id) + 1 if run_id in ids else len(ids)
    values = [raw.get("random_date_p") for raw in raws]
    numbers = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    adjusted = None
    if numbers and len(numbers) == len(values):  # every counted study has its stored p
        adjusted = float(benjamini_hochberg(numbers).qvalues[position - 1])
    own = values[position - 1] if 0 < position <= len(values) else None
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
    lines = [
        head,
        f"Setup {noun} {family['position']} of {family['studies']} on this setup's family.",
    ]
    count, adjusted = family["studies"], family["adjusted_random_date_p"]
    plural = noun if count == 1 else f"{noun}s" if noun == "trade" else "studies"
    if adjusted is None:
        lines.append(f"Random-date figure: not adjusted for the {count} {plural} tried.")
    else:
        lines.append(
            f"Random-date figure after counting {count} {plural} of this setup: {adjusted:.2%} "
            f"(before counting: {family['random_date_p']:.2%})."
        )
    if output.get("old_wording"):
        lines.append("Old record: the outcome word stored with it is not shown (old wording).")
    return lines
