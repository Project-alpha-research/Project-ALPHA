"""Sentences that contradict a stored diagnostic flag; conservative, regex-based, no reasoning."""

from __future__ import annotations

import re

_FLAG = r"(?:(?:warning|red|major|serious|significant) )?flags?"
_SUBJECT = r"(?:it|they|this run|the run|the test|this test|the result|the rule|run [0-9a-f]{8,16})"
_NOT_MISSED = r"(?! (?:was |were )?(?:missed|ignored|hidden|dropped|lost|overlooked))"
_RAISED = r"(?:raised|fired|triggered|reported|found|present|shown|noted|recorded|set|attached)"
# A denial needs the run as its subject (or "there were") and a no-flags predicate, so a sentence
# such as "No flag was missed" is not a claim that the run has no flags.
GENERAL_DENIAL = "|".join(
    (
        rf"\bno {_FLAG} (?:was |were |had been |have been )?{_RAISED}\b",
        rf"\bzero {_FLAG} (?:was |were )?{_RAISED}\b",
        rf"\bno warnings\b{_NOT_MISSED}",
        r"\bnothing (?:was )?flagged\b",
        rf"^\W*no {_FLAG}(?: or warnings)?\W*$",
        rf"\b{_SUBJECT}\b[^.\n]{{0,30}}\b(?:no|zero) {_FLAG}\b{_NOT_MISSED}",
        rf"\b{_SUBJECT}\b[^.\n]{{0,40}}\bwithout (?:any )?{_FLAG}\b",
        r"\b(?:is|was|looks|came out|came back)\b[^.\n]{0,10}\bflag free\b",
        rf"\bthere (?:were|are|was|is) (?:no|zero) {_FLAG}\b{_NOT_MISSED}",
    )
)
CONTRADICTIONS = {
    "*": GENERAL_DENIAL,
    "below-benchmark": (
        r"\b(?:beat|beats|outperformed|outperforms) (?:the )?(?:benchmark|buy and hold)\b"
    ),
    **{
        f"fragile-to-{kind}": r"\b(?:robust|insensitive|held up|holds up|unaffected)\b[^.\n]{0,40}"
        + suffix
        for kind, suffix in (
            ("costs", r"\bcosts?\b"),
            ("parameters", r"\b(?:parameters?|settings)\b"),
            ("delay", r"\bdelay"),
        )
    },
    "concentrated-profit": r"\b(?:spread|evenly|broad)\b[^.\n]{0,40}\btrades\b",
    "drawdown-with-market": r"\b(?:unrelated to|independent of) (?:the )?market\b",
}


def flag_hits(
    phrases: str, run_id: str, stored_flags: list[dict[str, str]], others: list[str]
) -> list[tuple[int, str, str]]:
    """Return (offset, flag code, detail) for each run/flag/sentence contradiction."""
    hits = []
    offset = 0
    for sentence in re.split(r"(?<=[.!?])\s+|\n", phrases):
        start = phrases.find(sentence, offset)
        offset = start + len(sentence)
        if run_id[:8] not in sentence and any(other[:8] in sentence for other in others):
            continue  # the sentence names a different cited run, so it is not about this one
        denied = re.search(CONTRADICTIONS["*"], sentence)
        negated = re.search(r"\b(?:not|never|no longer|failed to)\b|n't", sentence)
        seen = set()
        for flag in stored_flags:
            code = flag["flag"]
            pattern = CONTRADICTIONS.get(code)
            if code not in seen and (
                denied or (not negated and pattern and re.search(pattern, sentence))
            ):
                seen.add(code)
                hits.append((start, code, flag["detail"]))
    return hits
